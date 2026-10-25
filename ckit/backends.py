"""Model backends.

`APIChatModel` calls OpenAI and Gemini models through their APIs (no GPU needed).
`HFChatModel` runs an open-weight chat model with Hugging Face transformers (Colab GPU).
`MockChatModel` is a fake model used by the tests and the dry run, so the whole
pipeline can be checked without a GPU or any model download.
"""
from __future__ import annotations

import gc
import hashlib
import random
from typing import Protocol


class ChatModel(Protocol):
    key: str

    def chat(self, messages: list[dict], seed: int, kind: str = "") -> dict: ...

    def unload(self) -> None: ...


# ---------------------------------------------------------------- Hugging Face
class HFChatModel:
    """Chat with a Hugging Face model using its own chat template."""

    def __init__(self, key: str, hf_id: str, gen_cfg: dict, chat_template_kwargs: dict | None = None):
        import torch
        import transformers
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.key, self.hf_id, self.gen_cfg = key, hf_id, gen_cfg
        self.chat_template_kwargs = chat_template_kwargs or {}
        self.torch = torch

        dtype = torch.float16  # T4 GPUs have no fast bfloat16; used for both models
        kwargs = {"device_map": "auto"}
        # transformers renamed torch_dtype -> dtype in 4.56
        major, minor = (int(x) for x in transformers.__version__.split(".")[:2])
        kwargs["dtype" if (major, minor) >= (4, 56) else "torch_dtype"] = dtype
        if gen_cfg.get("load_in_4bit"):
            from transformers import BitsAndBytesConfig

            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=dtype,
            )
        self.tok = AutoTokenizer.from_pretrained(hf_id)
        if self.tok.pad_token_id is None:
            self.tok.pad_token = self.tok.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(hf_id, **kwargs)
        self.model.eval()

    def chat(self, messages: list[dict], seed: int, kind: str = "") -> dict:
        import transformers

        torch = self.torch
        # Render the template to text first: this behaves the same across transformers versions.
        text = self.tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, **self.chat_template_kwargs
        )
        enc = self.tok(text, return_tensors="pt", add_special_tokens=False).to(self.model.device)
        transformers.set_seed(seed)
        temp = float(self.gen_cfg.get("temperature", 0.7))
        with torch.no_grad():
            out = self.model.generate(
                **enc,
                max_new_tokens=int(self.gen_cfg.get("max_new_tokens", 512)),
                do_sample=temp > 0,
                temperature=temp if temp > 0 else None,
                top_p=float(self.gen_cfg.get("top_p", 1.0)) if temp > 0 else None,
                pad_token_id=self.tok.pad_token_id,
            )
        new = out[0, enc["input_ids"].shape[1]:]
        n_new = int(new.shape[0])
        return {
            "text": self.tok.decode(new, skip_special_tokens=True).strip(),
            "n_tokens": n_new,
            "hit_max_tokens": n_new >= int(self.gen_cfg.get("max_new_tokens", 512)),
        }

    def unload(self) -> None:
        del self.model
        gc.collect()
        if self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()


# ---------------------------------------------------------------- API (OpenAI, Gemini)
API_BASES = {
    "openai": (None, "OPENAI_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
}
BLOCK_HINTS = ("invalid_prompt", "content_filter", "content_policy", "safety", "blocked", "prohibited")


class APIChatModel:
    """Chat through an OpenAI-compatible API: OpenAI directly, Gemini via Google's compatibility endpoint.

    Every model is called with its provider's default sampling and reasoning settings
    (newer reasoning models reject or ignore temperature), so `api_params` in the config
    is empty unless you deliberately change a setting for every model.
    """

    def __init__(self, key: str, backend: str, api_model: str, max_output_tokens: int = 32768,
                 price: dict | None = None, api_params: dict | None = None, client=None):
        import os

        self.key, self.api_model = key, api_model
        self.max_out, self.params = int(max_output_tokens), dict(api_params or {})
        self.price = price or {}
        if client is None:
            from openai import OpenAI

            base, env = API_BASES[backend]
            if not os.environ.get(env):
                raise RuntimeError(f"{key}: set the {env} environment variable (a Colab secret)")
            client = OpenAI(api_key=os.environ[env], base_url=base, max_retries=8, timeout=900)
        self.client = client

    def _cost(self, prompt_tokens: int, output_tokens: int) -> float:
        return (prompt_tokens * self.price.get("input", 0) + output_tokens * self.price.get("output", 0)) / 1e6

    def chat(self, messages: list[dict], seed: int, kind: str = "") -> dict:
        try:
            r = self.client.chat.completions.create(
                model=self.api_model, messages=messages,
                max_completion_tokens=self.max_out, **self.params)
        except Exception as e:  # the provider refused the request itself
            msg = f"{type(e).__name__}: {e}"
            code = str(getattr(e, "code", "") or "")
            status = getattr(e, "status_code", None)
            if status == 400 and any(h in (code + msg).lower() for h in BLOCK_HINTS):
                return {"text": "", "n_tokens": 0, "hit_max_tokens": False, "blocked": True,
                        "finish_reason": "blocked_by_api", "api_error": msg[:500],
                        "prompt_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "cost_usd": 0.0}
            raise
        u = getattr(r, "usage", None)
        pt = int(getattr(u, "prompt_tokens", 0) or 0)
        total = int(getattr(u, "total_tokens", 0) or 0)
        ct = int(getattr(u, "completion_tokens", 0) or 0)
        out_tok = max(ct, total - pt)  # bill thinking tokens as output even if reported separately
        det = getattr(u, "completion_tokens_details", None)
        rt = int(getattr(det, "reasoning_tokens", 0) or 0) if det is not None else 0
        if not r.choices:
            text, finish = "", "blocked_by_api"
        else:
            c = r.choices[0]
            text = (c.message.content or "").strip()
            refusal = getattr(c.message, "refusal", None)
            if not text and refusal:
                text = refusal.strip()
            finish = c.finish_reason or ""
        return {"text": text, "n_tokens": ct, "hit_max_tokens": finish == "length",
                "blocked": (not text) and finish in ("content_filter", "blocked_by_api", "safety"),
                "finish_reason": finish, "prompt_tokens": pt, "output_tokens": out_tok,
                "reasoning_tokens": rt, "cost_usd": round(self._cost(pt, out_tok), 6)}

    def unload(self) -> None:
        pass


# ---------------------------------------------------------------- Mock
REFUSALS = [
    "I'm sorry, but I can't help with that request.",
    "I cannot provide that. Is there something else I can help with?",
    "As an AI, I'm not able to assist with this.",
]


class MockChatModel:
    """Deterministic fake model for tests.

    It refuses with a probability that falls as a conversation goes on (a crude
    stand-in for Crescendo) and that depends on `generation`, so tests produce
    non-trivial tables. Its replies contain no real content.
    """

    def __init__(self, key: str, generation: int = 1, **_):
        self.key, self.generation = key, generation

    def chat(self, messages: list[dict], seed: int, kind: str = "") -> dict:
        user_turns = sum(1 for m in messages if m["role"] == "user")
        h = hashlib.sha256(f"{self.key}|{seed}|{messages[-1]['content']}|{user_turns}".encode()).hexdigest()
        rng = random.Random(int(h[:12], 16))
        benign = kind == "benign"
        if benign:
            p_refuse = 0.35 if self.generation == 1 else 0.08
        else:
            base = 0.97 if self.generation == 1 else 0.9
            p_refuse = max(0.4, base - 0.08 * (user_turns - 1))
        if rng.random() < p_refuse:
            text = rng.choice(REFUSALS)
        else:
            text = f"[mock compliant answer, turn {user_turns}] " + "lorem ipsum " * rng.randint(5, 40)
        return {"text": text.strip(), "n_tokens": len(text.split()), "hit_max_tokens": False}

    def unload(self) -> None:
        pass


def is_api(model_cfg: dict) -> bool:
    return model_cfg.get("backend", "hf") in API_BASES


def load_model(model_cfg: dict, gen_cfg: dict, mock: bool = False) -> ChatModel:
    if mock:
        return MockChatModel(model_cfg["key"], generation=model_cfg.get("generation", 1))
    if is_api(model_cfg):
        return APIChatModel(model_cfg["key"], model_cfg["backend"], model_cfg["api_model"],
                            model_cfg.get("max_output_tokens", 32768), model_cfg.get("price_per_mtok"),
                            model_cfg.get("api_params"))
    return HFChatModel(
        model_cfg["key"], model_cfg["hf_id"], gen_cfg, model_cfg.get("chat_template_kwargs")
    )
