"""Blinded human labelling.

`export_sheets` writes two CSVs for the two annotators. Model names are hidden
and rows are shuffled, so neither annotator knows which generation produced a
reply. A separate key file maps each item code back to its run.

`load_labels` reads the filled sheets back, computes Cohen's kappa and returns
one final label per item (the `final_*` column if filled, else the annotators'
shared answer). Disagreements without a final value are listed for discussion.
"""
from __future__ import annotations

import random

import pandas as pd

from .common import paths, read_jsonl


def judge_table(cfg: dict) -> pd.DataFrame:
    """Per harmful run: max StrongREJECT score and first turn at/over threshold."""
    thr = cfg["judge"]["success_threshold"]
    rows = [r for r in read_jsonl(paths(cfg).judgments) if "score" in r]
    if not rows:
        return pd.DataFrame(columns=["run_id", "judge_max", "judge_final", "judge_first_turn", "judge_scores"])
    df = pd.DataFrame(rows).drop_duplicates(["run_id", "turn", "judge"], keep="last")
    out = []
    for rid, g in df.sort_values("turn").groupby("run_id"):
        over = g.loc[g["score"] >= thr, "turn"]
        out.append({"run_id": rid, "judge_max": g["score"].max(),
                    "judge_final": float(g["score"].iloc[-1]),
                    "judge_first_turn": int(over.min()) if len(over) else None,
                    "judge_scores": [round(s, 3) for s in g["score"]]})
    return pd.DataFrame(out)


def benign_auto_table(cfg: dict) -> pd.DataFrame:
    rows = [r for r in read_jsonl(paths(cfg).judgments) if "label" in r]
    if not rows:
        return pd.DataFrame(columns=["run_id", "auto_class", "auto_judge"])
    df = pd.DataFrame(rows).drop_duplicates(["run_id", "judge"], keep="last")
    # prefer the LLM classifier if both exist
    df["pri"] = (df["judge"] == "xstest_llm").astype(int)
    df = df.sort_values("pri").drop_duplicates("run_id", keep="last")
    return df.rename(columns={"label": "auto_class", "judge": "auto_judge"})[["run_id", "auto_class", "auto_judge"]]


def _transcript(turns) -> str:
    parts = []
    for t in turns:
        parts.append(f"USER {t['turn']}: {t['user']}")
        reply = t["assistant"] or ("[no reply: request blocked by the provider]" if t.get("blocked")
                                   else "[empty reply]")
        parts.append(f"MODEL {t['turn']}: {reply}")
    return "\n\n".join(parts)


def export_sheets(cfg: dict, force: bool = False, log=print) -> None:
    p = paths(cfg)
    L = cfg["labelling"]
    rng = random.Random(L.get("seed", 7))
    gens = list(read_jsonl(p.generations))
    jt = judge_table(cfg)
    jt = jt.set_index("run_id") if len(jt) else None

    targets = {"harmful": p.labels_dir / "harmful_labels.csv", "benign": p.labels_dir / "benign_labels.csv"}
    if not force and any(t.exists() for t in targets.values()):
        raise FileExistsError(
            "Label sheets already exist in results/labels. They may contain your work, so they were "
            "not overwritten. Pass force=True only if you really want fresh, empty sheets.")

    # ---- harmful: every flagged run + a random sample of the others
    harm = [g for g in gens if g["condition"] != "benign"]
    flagged, other = [], []
    for g in harm:
        jm = jt.loc[g["run_id"], "judge_max"] if jt is not None and g["run_id"] in jt.index else None
        (flagged if jm is not None and jm >= cfg["judge"]["success_threshold"] else other).append(g)
    k = round(len(other) * L.get("sample_fraction_unflagged", 0.25))
    chosen = flagged + rng.sample(other, k)
    rng.shuffle(chosen)
    hs, hk = [], []
    for i, g in enumerate(chosen, start=1):
        code = f"H{i:03d}"
        hs.append({"item_code": code, "goal": g["goal"], "n_turns": len(g["turns"]),
                   "transcript": _transcript(g["turns"]),
                   "violation_A": "", "first_turn_A": "", "violation_B": "", "first_turn_B": "",
                   "final_violation": "", "final_first_turn": "", "notes": ""})
        hk.append({"item_code": code, "run_id": g["run_id"], "flagged": g in flagged})
    pd.DataFrame(hs).to_csv(targets["harmful"], index=False)
    pd.DataFrame(hk).to_csv(p.labels_dir / "_key_harmful.csv", index=False)

    # ---- benign: all responses (or the same sampling rule)
    ben = [g for g in gens if g["condition"] == "benign"]
    if not L.get("label_all_benign", True):
        ben = rng.sample(ben, round(len(ben) * L.get("sample_fraction_unflagged", 0.25)))
    rng.shuffle(ben)
    bs, bk = [], []
    for i, g in enumerate(ben, start=1):
        code = f"B{i:03d}"
        t = g["turns"][0]
        bs.append({"item_code": code, "prompt": t["user"],
                   "response": t["assistant"] or ("[no reply: request blocked by the provider]" if t.get("blocked") else "[empty reply]"),
                   "class_A": "", "class_B": "", "final_class": "", "notes": ""})
        bk.append({"item_code": code, "run_id": g["run_id"]})
    pd.DataFrame(bs).to_csv(targets["benign"], index=False)
    pd.DataFrame(bk).to_csv(p.labels_dir / "_key_benign.csv", index=False)
    log(f"wrote {len(hs)} harmful items ({len(flagged)} flagged + {k} sampled) and {len(bs)} benign items "
        f"to {p.labels_dir}")


# ------------------------------------------------------------ reading back
def cohen_kappa(a, b) -> float:
    pairs = [(x, y) for x, y in zip(a, b) if pd.notna(x) and pd.notna(y)]
    if not pairs:
        return float("nan")
    cats = sorted({c for pr in pairs for c in pr})
    n = len(pairs)
    po = sum(x == y for x, y in pairs) / n
    pe = sum((sum(x == c for x, _ in pairs) / n) * (sum(y == c for _, y in pairs) / n) for c in cats)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def _num(s):
    return pd.to_numeric(s.replace("", pd.NA) if s.dtype == object else s, errors="coerce")


def load_labels(cfg: dict) -> dict:
    """Return final human labels per run plus agreement statistics."""
    p = paths(cfg)
    out = {"harmful": pd.DataFrame(columns=["run_id"]), "benign": pd.DataFrame(columns=["run_id"]),
           "agreement": {}, "unresolved": []}

    hf, hk = p.labels_dir / "harmful_labels.csv", p.labels_dir / "_key_harmful.csv"
    if hf.exists() and hk.exists():
        h = pd.read_csv(hf, dtype=str, keep_default_na=False).merge(pd.read_csv(hk), on="item_code")
        for c in ["violation_A", "violation_B", "final_violation", "first_turn_A", "first_turn_B", "final_first_turn"]:
            h[c] = _num(h[c])
        h["violation"] = h["final_violation"].where(
            h["final_violation"].notna(), h["violation_A"].where(h["violation_A"] == h["violation_B"]))
        both_yes = (h["violation_A"] == 1) & (h["violation_B"] == 1)
        h["first_turn"] = h["final_first_turn"].where(
            h["final_first_turn"].notna(),
            h["first_turn_A"].where(both_yes & (h["first_turn_A"] == h["first_turn_B"])))
        out["agreement"]["harmful_violation_kappa"] = cohen_kappa(h["violation_A"], h["violation_B"])
        out["agreement"]["harmful_n_double_labelled"] = int((h["violation_A"].notna() & h["violation_B"].notna()).sum())
        unres = h[h["violation"].isna() & h["violation_A"].notna() & h["violation_B"].notna()]
        out["unresolved"] += [f"{c}: annotators disagree on violation" for c in unres["item_code"]]
        unres_t = h[(h["violation"] == 1) & h["first_turn"].isna()]
        out["unresolved"] += [f"{c}: violation agreed, first turn not agreed" for c in unres_t["item_code"]]
        out["harmful"] = h[["run_id", "item_code", "violation", "first_turn", "violation_A", "violation_B"]]

    bf, bk = p.labels_dir / "benign_labels.csv", p.labels_dir / "_key_benign.csv"
    if bf.exists() and bk.exists():
        b = pd.read_csv(bf, dtype=str, keep_default_na=False).merge(pd.read_csv(bk), on="item_code")
        for c in ["class_A", "class_B", "final_class"]:
            b[c] = _num(b[c])
        b["human_class"] = b["final_class"].where(b["final_class"].notna(), b["class_A"].where(b["class_A"] == b["class_B"]))
        out["agreement"]["benign_class_kappa"] = cohen_kappa(b["class_A"], b["class_B"])
        out["agreement"]["benign_n_double_labelled"] = int((b["class_A"].notna() & b["class_B"].notna()).sum())
        unres = b[b["human_class"].isna() & b["class_A"].notna() & b["class_B"].notna()]
        out["unresolved"] += [f"{c}: annotators disagree on class" for c in unres["item_code"]]
        out["benign"] = b[["run_id", "item_code", "human_class", "class_A", "class_B"]]
    return out
