"""Run every model on every condition and save each conversation.

Each finished run is appended to generations.jsonl at once, so a disconnect
loses at most the runs in progress: start again and finished runs are skipped.
API models run several conversations in parallel and stop before the spending
limit in config.yaml (`budget_usd`) is passed.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

from .backends import is_api, load_model
from .common import append_jsonl, paths, read_jsonl
from .scenarios import load_benign, load_harmful

CONDITIONS = ("single", "crescendo", "benign")
TURN_EXTRAS = ("blocked", "finish_reason", "api_error", "prompt_tokens", "output_tokens",
               "reasoning_tokens", "cost_usd")


def run_id(model_key: str, condition: str, item_id: str, run: int) -> str:
    return f"{model_key}|{condition}|{item_id}|r{run}"


def plan(cfg: dict, conditions=CONDITIONS, limit: int | None = None) -> list[dict]:
    """Every (condition, item, run) to do for one model, in a fixed order."""
    g = cfg["generation"]
    jobs = []
    if {"single", "crescendo"} & set(conditions):
        harmful = load_harmful(cfg["data"]["harmful_scenarios"])[:limit]
        for s in harmful:
            for run in range(g["runs_per_condition"]):
                if "single" in conditions:
                    jobs.append({"condition": "single", "item": s, "run": run})
                if "crescendo" in conditions:
                    jobs.append({"condition": "crescendo", "item": s, "run": run})
    if "benign" in conditions:
        for b in load_benign(cfg["data"]["benign_prompts"])[:limit]:
            for run in range(g["runs_per_condition"]):
                jobs.append({"condition": "benign", "item": b, "run": run})
    return jobs


def _messages(system_prompt, history):
    return ([{"role": "system", "content": system_prompt}] if system_prompt else []) + history


def run_one(model, job: dict, cfg: dict) -> dict:
    g = cfg["generation"]
    seed = int(g["base_seed"]) + 1000 * job["run"]  # same seed for both models -> paired comparison
    item, cond = job["item"], job["condition"]
    if cond == "crescendo":
        user_turns = item.turns
    elif cond == "single":
        user_turns = [item.direct_prompt]
    else:
        user_turns = [item.prompt]

    history, turns, t0, stopped = [], [], time.time(), False
    for i, u in enumerate(user_turns, start=1):
        history.append({"role": "user", "content": u})
        out = model.chat(_messages(g.get("system_prompt"), history), seed=seed + i, kind=cond)
        history.append({"role": "assistant", "content": out["text"]})
        turns.append({"turn": i, "user": u, "assistant": out["text"],
                      "n_tokens": out["n_tokens"], "hit_max_tokens": out["hit_max_tokens"],
                      **{k: out[k] for k in TURN_EXTRAS if k in out}})
        if out.get("blocked"):
            # The provider blocked this request outright. Like a user who gets an error
            # in a chat app, the conversation ends here; later turns are not sent.
            stopped = True
            break
    return {
        "condition": cond,
        "item_id": item.id,
        "category": getattr(item, "category", None) or getattr(item, "type", ""),
        "goal": getattr(item, "intent", None) or item.prompt,
        "run": job["run"],
        "seed": seed,
        "turns": turns,
        "planned_turns": len(user_turns),
        "stopped_by_block": stopped,
        "cost_usd": round(sum(t.get("cost_usd", 0) for t in turns), 6),
        "seconds": round(time.time() - t0, 2),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def spent_usd(cfg: dict) -> float:
    return sum(r.get("cost_usd", 0) or 0 for r in read_jsonl(paths(cfg).generations) if not r.get("mock"))


def run_all(cfg: dict, mock: bool = False, model_keys=None, conditions=CONDITIONS,
            limit: int | None = None, log=print) -> None:
    p = paths(cfg)
    done = {r["run_id"] for r in read_jsonl(p.generations)}
    budget = cfg.get("budget_usd")
    spent = [spent_usd(cfg)]
    lock = threading.Lock()
    if budget is not None and not mock:
        log(f"spent so far: ${spent[0]:.2f} of the ${budget:.2f} limit")

    for mcfg in cfg["models"]:
        if model_keys and mcfg["key"] not in model_keys:
            continue
        jobs = [j for j in plan(cfg, conditions, limit)
                if run_id(mcfg["key"], j["condition"], j["item"].id, j["run"]) not in done]
        if not jobs:
            log(f"{mcfg['key']}: nothing to do (all runs already saved)")
            continue
        log(f"{mcfg['key']}: {len(jobs)} runs to do")
        model = load_model(mcfg, cfg["generation"], mock=mock)
        workers = int(cfg.get("api_concurrency", 6)) if (is_api(mcfg) and not mock) else 1
        n_done = [0]

        def work(job):
            rec = run_one(model, job, cfg)
            rec = {"run_id": run_id(mcfg["key"], job["condition"], job["item"].id, job["run"]),
                   "model_key": mcfg["key"], "model_id": mcfg.get("api_model") or mcfg.get("hf_id"),
                   "family": mcfg.get("family", "main"), "generation": mcfg.get("generation"),
                   "mock": mock, **rec}
            with lock:
                append_jsonl(p.generations, rec)
                spent[0] += rec["cost_usd"] if not mock else 0
                n_done[0] += 1
                if n_done[0] % 10 == 0 or n_done[0] == len(jobs):
                    log(f"  {mcfg['key']}: {n_done[0]}/{len(jobs)} runs saved"
                        + (f", ${spent[0]:.2f} spent in total" if is_api(mcfg) and not mock else ""))

        try:
            queue = list(jobs)
            with ThreadPoolExecutor(max_workers=workers) as ex:
                running = set()
                while queue or running:
                    while queue and len(running) < workers:
                        if budget is not None and not mock and spent[0] >= budget:
                            log(f"STOPPED: spending limit ${budget:.2f} reached. Raise budget_usd in "
                                f"config.yaml to continue; finished runs are kept.")
                            queue.clear()
                            break
                        running.add(ex.submit(work, queue.pop(0)))
                    if not running:
                        break
                    finished, running = wait(running, return_when=FIRST_COMPLETED)
                    for f in finished:
                        f.result()  # re-raise errors (bad key, wrong model id, ...)
        finally:
            model.unload()
