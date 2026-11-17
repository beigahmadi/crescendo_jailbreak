"""End-to-end test on the mock model: python -m pytest tests  (or python tests/test_pipeline.py)"""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ckit.analysis import mcnemar_exact, run_analysis, wilson  # noqa: E402
from ckit.common import load_config, paths, read_jsonl  # noqa: E402
from ckit.generate import run_all  # noqa: E402
from ckit.judge import judge_all, xstest_strmatch  # noqa: E402
from ckit.labels import cohen_kappa, export_sheets  # noqa: E402
from ckit.scenarios import load_harmful  # noqa: E402


def test_stats():
    lo, hi = wilson(5, 10)
    assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77
    assert wilson(0, 0) != wilson(0, 0)  # nan
    r = mcnemar_exact(pd.Series([1, 1, 1, 0, 0]), pd.Series([0, 0, 1, 0, 1]))
    assert (r["a_only"], r["b_only"]) == (2, 1)
    assert cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    assert xstest_strmatch("I'm sorry, I can't") == 2 and xstest_strmatch("Sure! Here") == 1


def test_template_is_rejected():
    # uses its own template copy, so it still works after you replace data/scenarios_harmful.csv
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "template.csv"
        f.write_text("id,category,source,intent,direct_prompt,turn_1,turn_2,turn_3,turn_4,turn_5\n"
                     "h01,TODO category,TODO,<approved intent 1: TODO>,,TODO,TODO,TODO,TODO,TODO\n")
        try:
            load_harmful(str(f))
        except ValueError as e:
            assert "placeholders" in str(e)
        else:
            raise AssertionError("template scenarios should not validate")


def _fill_labels(cfg, rng):
    """Pretend to be two annotators who mostly agree with the judge."""
    d = paths(cfg).labels_dir
    jt = {}
    for r in read_jsonl(paths(cfg).judgments):
        if "score" in r:
            jt.setdefault(r["run_id"], []).append((r["turn"], r["score"]))
    key = pd.read_csv(d / "_key_harmful.csv")
    h = pd.read_csv(d / "harmful_labels.csv", dtype=str, keep_default_na=False)
    for i, row in h.iterrows():
        rid = key.set_index("item_code").loc[row["item_code"], "run_id"]
        sc = sorted(jt[rid])
        v = int(max(s for _, s in sc) >= 0.5)
        ft = next((t for t, s in sc if s >= 0.5), "")
        h.loc[i, ["violation_A", "first_turn_A"]] = [str(v), str(ft)]
        vb = v if rng.random() > 0.1 else 1 - v
        h.loc[i, ["violation_B", "first_turn_B"]] = [str(vb), str(ft) if vb else ""]
        if vb != v:
            h.loc[i, ["final_violation", "final_first_turn"]] = [str(v), str(ft)]
    h.to_csv(d / "harmful_labels.csv", index=False)
    b = pd.read_csv(d / "benign_labels.csv", dtype=str, keep_default_na=False)
    for i, row in b.iterrows():
        c = xstest_strmatch(row["response"])
        b.loc[i, ["class_A", "class_B"]] = [str(c), str(c if rng.random() > 0.1 else 3)]
    b.to_csv(d / "benign_labels.csv", index=False)


def test_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = load_config(results_dir=tmp)
        cfg["data"]["harmful_scenarios"] = str(ROOT / "tests/fixtures/scenarios_test.csv")
        run_all(cfg, mock=True, limit=None, log=lambda *_: None)
        gens = list(read_jsonl(paths(cfg).generations))
        n_h, n_b = 4, 30
        runs = cfg["generation"]["runs_per_condition"]
        n_m = len(cfg["models"])
        assert len(gens) == n_m * runs * (2 * n_h + n_b), len(gens)
        # resume: a second call does nothing
        run_all(cfg, mock=True, log=lambda *_: None)
        assert len(list(read_jsonl(paths(cfg).generations))) == len(gens)
        assert all(len(g["turns"]) == 5 for g in gens if g["condition"] == "crescendo")
        # paired design: both models see identical user turns and seeds
        by = {}
        for g in gens:
            by.setdefault((g["condition"], g["item_id"], g["run"]), []).append(g)
        for pair in by.values():
            assert len(pair) == n_m
            assert [t["user"] for t in pair[0]["turns"]] == [t["user"] for t in pair[1]["turns"]]
            assert pair[0]["seed"] == pair[1]["seed"]

        judge_all(cfg, mock=True, log=lambda *_: None)
        export_sheets(cfg, log=lambda *_: None)
        try:
            export_sheets(cfg, log=lambda *_: None)
            raise AssertionError("must not overwrite label sheets")
        except FileExistsError:
            pass
        sheet = pd.read_csv(paths(cfg).labels_dir / "harmful_labels.csv")
        assert not any(m in " ".join(sheet.columns) for m in ("model", "llama"))  # blinded
        _fill_labels(cfg, random.Random(1))

        res = run_analysis(cfg, log=lambda *_: None)
        asr, orr, tests = res["asr"], res["orr"], res["tests"]
        assert set(asr["condition"]) == {"single", "crescendo"} and len(asr) == 2 * n_m
        assert len(orr) == n_m and set(tests["hypothesis"]) >= {"H1", "H2", "H3"}
        fams = {m.get("family", "main") for m in cfg["models"]}
        assert (tests["hypothesis"] == "H1").sum() == len(fams)  # old vs new within each family only
        assert len(res["figures"]) == 3
        s = (paths(cfg).analysis_dir / "summary.md").read_text()
        assert "MOCK" in s
        out = Path(__file__).resolve().parent / "last_run"
        out.mkdir(exist_ok=True)
        for f in paths(cfg).analysis_dir.iterdir():
            (out / f.name).write_bytes(f.read_bytes())


# ---------------------------------------------------------------- API backend, with a fake client
class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeClient:
    """Imitates openai.OpenAI().chat.completions.create for the cases we must handle."""

    def __init__(self, mode):
        self.mode, self.calls = mode, []
        self.chat = _Obj(completions=_Obj(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if self.mode == "blocked":
            err = Exception("Error code: 400 - Invalid prompt: flagged as potentially violating our usage policy")
            err.status_code, err.code = 400, "invalid_prompt"
            raise err
        if self.mode == "flagged":
            err = Exception("Error code: 400 - This content was flagged for possible cybersecurity risk.")
            err.status_code, err.code = 400, None
            raise err
        if self.mode == "badparam":
            err = Exception("Error code: 400 - Unsupported parameter: 'max_completion_tokens'")
            err.status_code, err.code = 400, "unsupported_parameter"
            raise err
        usage = _Obj(prompt_tokens=100, completion_tokens=900, total_tokens=1000,
                     completion_tokens_details=_Obj(reasoning_tokens=800))
        if self.mode == "nomessage":
            return _Obj(choices=[_Obj(message=None, finish_reason=None)], usage=usage)
        if self.mode == "filtered":
            msg, fin = _Obj(content=None, refusal=None), "content_filter"
        elif self.mode == "refusal":
            msg, fin = _Obj(content=None, refusal="I can't help with that."), "stop"
        else:
            msg, fin = _Obj(content="Sure, here is an answer.", refusal=None), "stop"
        return _Obj(choices=[_Obj(message=msg, finish_reason=fin)], usage=usage)


def test_api_backend():
    from ckit.backends import APIChatModel
    from ckit.generate import run_one
    from ckit.scenarios import HarmfulScenario

    price = {"input": 2.0, "output": 10.0}
    m = APIChatModel("x", "openai", "gpt-x", 32768, price, client=_FakeClient("ok"))
    out = m.chat([{"role": "user", "content": "hi"}], seed=1)
    assert out["text"] == "Sure, here is an answer." and out["reasoning_tokens"] == 800
    assert abs(out["cost_usd"] - (100 * 2 + 900 * 10) / 1e6) < 1e-12
    call = m.client.calls[0]
    assert "temperature" not in call and call["max_completion_tokens"] == 32768  # provider defaults

    assert APIChatModel("x", "openai", "m", client=_FakeClient("refusal")).chat(
        [{"role": "user", "content": "q"}], 1)["text"] == "I can't help with that."
    f = APIChatModel("x", "gemini", "m", client=_FakeClient("filtered")).chat([{"role": "user", "content": "q"}], 1)
    assert f["blocked"] and f["text"] == ""
    assert APIChatModel("x", "openai", "m", client=_FakeClient("flagged")).chat(
        [{"role": "user", "content": "q"}], 1)["blocked"]
    nm = APIChatModel("x", "gemini", "m", client=_FakeClient("nomessage")).chat([{"role": "user", "content": "q"}], 1)
    assert nm["blocked"] and nm["text"] == "" and nm["finish_reason"] == "blocked_by_api"
    b = APIChatModel("x", "openai", "m", client=_FakeClient("blocked"))
    assert b.chat([{"role": "user", "content": "q"}], 1)["blocked"]
    try:
        APIChatModel("x", "openai", "m", client=_FakeClient("badparam")).chat([{"role": "user", "content": "q"}], 1)
        raise AssertionError("a configuration error must not be hidden as a block")
    except Exception as e:
        assert "Unsupported parameter" in str(e)

    # a provider block ends a Crescendo conversation
    cfg = load_config()
    s = HarmfulScenario("t1", "test", "TEST GOAL", "TEST GOAL", ["a", "b", "c", "d", "e"])
    rec = run_one(b, {"condition": "crescendo", "item": s, "run": 0}, cfg)
    assert rec["stopped_by_block"] and len(rec["turns"]) == 1 and rec["planned_turns"] == 5
    assert xstest_strmatch("") == 2  # an empty reply counts as a refusal


if __name__ == "__main__":
    test_stats(); test_template_is_rejected(); test_api_backend(); test_end_to_end()
    print("all tests passed")
