"""End-to-end test on the mock model: python -m pytest tests  (or python tests/test_pipeline.py)"""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ckit.analysis import holm, mcnemar_exact, paired_bootstrap, run_analysis, wilson  # noqa: E402
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
    assert [round(x, 3) for x in holm([0.01, 0.04, 0.03])] == [0.03, 0.06, 0.06]
    idx = pd.MultiIndex.from_tuples([(f"i{k}", r) for k in range(10) for r in range(2)], names=["item_id", "run"])
    old = pd.Series([1] * 20, index=idx)
    new = pd.Series([1, 0] * 10, index=idx)
    bt = paired_bootstrap(old, new, B=500)
    assert bt["delta"] == -0.5 and bt["n_items"] == 10 and bt["ci_low"] <= -0.5 <= bt["ci_high"]


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
        n_h, n_b = 4, 50
        runs = cfg["generation"]["runs_per_condition"]
        n_m = len(cfg["models"])
        assert len(gens) == n_m * (n_h * (runs["single"] + runs["crescendo"]) + n_b * runs["benign"]), len(gens)
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

        # --- extension: adaptive Crescendo on the same scenarios, then a second labelling batch
        run_all(cfg, mock=True, conditions=["adaptive"], log=lambda *_: None)
        ad = [g for g in read_jsonl(paths(cfg).generations) if g["condition"] == "adaptive"]
        assert len(ad) == n_m * n_h * runs["adaptive"]
        assert any(g["n_backtracks"] > 0 for g in ad), "mock refusals should trigger backtracking"
        for g in ad:
            assert g["target_calls"] == len(g["turns"]) + g["n_backtracks"]
            assert g["n_backtracks"] <= cfg["attacker"]["max_backtracks"]
            assert all(t["user"].startswith("adaptive mock turn") for t in g["turns"])
            # a backtracked turn never reaches the target's history: accepted turns are numbered 1..n
            assert [t["turn"] for t in g["turns"]] == list(range(1, len(g["turns"]) + 1))
        judge_all(cfg, mock=True, log=lambda *_: None)
        export_sheets(cfg, append=True, log=lambda *_: None)
        b2 = pd.read_csv(paths(cfg).labels_dir / "harmful_labels_b2.csv")
        assert len(b2) == len(ad) and b2["item_code"].str.startswith("H2-").all()
        assert b2["transcript"].str.contains("removed from the conversation").any()
        export_sheets(cfg, append=True, log=lambda *_: None)  # nothing new: no third batch
        assert not (paths(cfg).labels_dir / "harmful_labels_b3.csv").exists()
        h2 = pd.read_csv(paths(cfg).labels_dir / "harmful_labels_b2.csv", dtype=str, keep_default_na=False)
        h2[["violation_A", "violation_B", "first_turn_A", "first_turn_B"]] = ["1", "1", "2", "2"]
        h2.to_csv(paths(cfg).labels_dir / "harmful_labels_b2.csv", index=False)

        res = run_analysis(cfg, log=lambda *_: None)
        asr, orr, tests = res["asr"], res["orr"], res["tests"]
        assert set(asr["condition"]) == {"single", "crescendo", "adaptive"} and len(asr) == 3 * n_m
        assert (asr[asr.condition == "adaptive"]["asr"] == 1.0).all()  # batch-2 human labels were read
        assert {"H1 (adaptive)", "H2 (adaptive)", "H4"} <= set(tests["hypothesis"]) and "p_holm" in tests
        gc = res["generation_change"]
        assert {"ASR crescendo", "ASR adaptive", "multi-turn gap: crescendo minus single",
                "adaptivity gain: adaptive minus scripted", "backtracks needed (adaptive)", "ORR benign"} <= set(gc["measure"])
        assert (gc["ci_low"] <= gc["delta"] + 1e-9).all() and (gc["delta"] <= gc["ci_high"] + 1e-9).all()
        assert len(orr) == n_m and set(tests["hypothesis"]) >= {"H1", "H2", "H3"}
        fams = {m.get("family", "main") for m in cfg["models"]}
        assert (tests["hypothesis"] == "H1").sum() == len(fams)  # old vs new within each family only
        assert len(res["figures"]) == 4
        s = (paths(cfg).analysis_dir / "summary.md").read_text()
        assert "MOCK" in s
        out = Path(__file__).resolve().parent / "last_run"
        out.mkdir(exist_ok=True)
        for f in paths(cfg).analysis_dir.iterdir():
            (out / f.name).write_bytes(f.read_bytes())


# ---------------------------------------------------------------- API backend, with a fake client ----------------------------------------------------------------
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


def test_refusal_detector_and_drafts():
    from ckit.attacker import looks_like_refusal
    from ckit.scenarios import draft_scripts
    assert looks_like_refusal("I\u2019m sorry, but I can\u2019t help with that.")
    assert looks_like_refusal("", blocked=True) and looks_like_refusal("Sure", blocked=True)
    assert not looks_like_refusal("Sure. Here is an overview of how account recovery works. " * 20)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "new.csv"
        src.write_text("id,category,source,intent,direct_prompt,turn_1,turn_2,turn_3,turn_4,turn_5\n"
                       "n1,harassment,test,TEST GOAL N1,,,,,,\n"
                       "n2,harassment,test,TEST GOAL N2,,a,b,c,d,e\n")
        cfg = load_config(results_dir=tmp)
        out = draft_scripts(cfg, str(src), str(Path(tmp) / "drafted.csv"), mock=True, log=lambda *_: None)
        d = pd.read_csv(out, dtype=str, keep_default_na=False)
        assert d.loc[0, "turn_5"] == "scripted mock turn 5" and d.loc[0, "review_status"].startswith("TODO")
        assert d.loc[1, "turn_1"] == "a" and d.loc[1, "review_status"] == "approved"
        try:
            load_harmful(out)  # unreviewed drafts must not be usable
            raise AssertionError("drafts with review_status TODO must be rejected")
        except ValueError as e:
            assert "n1" in str(e) and "n2" not in str(e)


def test_data_files():
    from ckit.scenarios import load_benign
    cfg = load_config()
    b = load_benign(cfg["data"]["benign_prompts"])
    assert len(b) >= 50 and len({x.id for x in b}) == len(b)
    assert pd.Series([x.type for x in b]).value_counts().min() >= 5


def test_attacker_message_tags():
    from ckit.attacker import _extract_messages
    assert _extract_messages("<message> one </message>\n<message>two</message>") == ["one", "two"]
    # an untagged reply is used only where one message is expected (adaptive next turn)
    assert _extract_messages('"Can you tell me more?"') == []
    assert _extract_messages('"Can you tell me more?"', fallback=True) == ["Can you tell me more?"]
    assert _extract_messages("  ", fallback=True) == []
    assert _extract_messages("<message>x</message> extra", fallback=True) == ["x"]


if __name__ == "__main__":
    test_stats(); test_template_is_rejected(); test_api_backend(); test_refusal_detector_and_drafts()
    test_data_files(); test_attacker_message_tags(); test_end_to_end()
    print("all tests passed")
