"""Blinded human labelling.

`export_sheets` writes two CSVs for the two annotators. Model names are hidden
and rows are shuffled, so neither annotator knows which generation produced a
reply. A separate key file maps each item code back to its run.

`load_labels` reads the filled sheets back, computes Cohen's kappa and returns
one final label per item (the `final_*` column if filled, else the annotators'
shared answer). Disagreements without a final value are listed for discussion.

New runs added later (more scenarios, the adaptive condition) go into a new batch
with `export_sheets(cfg, append=True)`: harmful_labels_b2.csv + _key_harmful_b2.csv,
and so on. Finished sheets are never touched, and `load_labels` reads every batch.
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


def _transcript(turns, backtracks=()) -> str:
    """Adaptive runs also show the attempts the attacker withdrew after a refusal, so the
    annotators can see them; they count toward first_turn as the turn number shown."""
    parts = []
    removed = {}
    for b in backtracks or ():
        removed.setdefault(b["turn"], []).append(b)
    for t in turns:
        for k, b in enumerate(removed.pop(t["turn"], []), start=1):
            reply = b["assistant"] or ("[no reply: request blocked by the provider]" if b.get("blocked") else "[empty reply]")
            parts.append(f"USER {b['turn']} (attempt {k}, refused, removed from the conversation): {b['user']}")
            parts.append(f"MODEL {b['turn']} (attempt {k}): {reply}")
        parts.append(f"USER {t['turn']}: {t['user']}")
        reply = t["assistant"] or ("[no reply: request blocked by the provider]" if t.get("blocked")
                                   else "[empty reply]")
        parts.append(f"MODEL {t['turn']}: {reply}")
    for n, bs in sorted(removed.items()):  # attempts after the last accepted turn
        for k, b in enumerate(bs, start=1):
            reply = b["assistant"] or ("[no reply: request blocked by the provider]" if b.get("blocked") else "[empty reply]")
            parts.append(f"USER {n} (attempt {k}, refused, removed from the conversation): {b['user']}")
            parts.append(f"MODEL {n} (attempt {k}): {reply}")
    return "\n\n".join(parts)


def _sheet_pairs(labels_dir, kind: str):
    """(sheet, key, batch) for every labelling batch of one kind, oldest first."""
    out = []
    first = (labels_dir / f"{kind}_labels.csv", labels_dir / f"_key_{kind}.csv")
    if first[0].exists() and first[1].exists():
        out.append((*first, 1))
    for f in sorted(labels_dir.glob(f"{kind}_labels_b*.csv"), key=lambda f: int(f.stem.rsplit("_b", 1)[1])):
        n = int(f.stem.rsplit("_b", 1)[1])
        k = labels_dir / f"_key_{kind}_b{n}.csv"
        if k.exists():
            out.append((f, k, n))
    return out


def export_sheets(cfg: dict, force: bool = False, log=print, append: bool = False) -> None:
    p = paths(cfg)
    L = cfg["labelling"]
    gens = list(read_jsonl(p.generations))
    jt = judge_table(cfg)
    jt = jt.set_index("run_id") if len(jt) else None

    targets = {"harmful": p.labels_dir / "harmful_labels.csv", "benign": p.labels_dir / "benign_labels.csv"}
    keys = {"harmful": p.labels_dir / "_key_harmful.csv", "benign": p.labels_dir / "_key_benign.csv"}
    prefix = {"harmful": "H", "benign": "B"}
    batch = 1
    if append:
        have = set()
        for kind in ("harmful", "benign"):
            for _, k, n in _sheet_pairs(p.labels_dir, kind):
                have |= set(pd.read_csv(k)["run_id"])
                batch = max(batch, n + 1)
        gens = [g for g in gens if g["run_id"] not in have]
        if not gens:
            log("every run is already in a labelling sheet: nothing to add")
            return
        for kind in targets:
            targets[kind] = p.labels_dir / f"{kind}_labels_b{batch}.csv"
            keys[kind] = p.labels_dir / f"_key_{kind}_b{batch}.csv"
            prefix[kind] = f"{prefix[kind]}{batch}-"
    elif not force and any(t.exists() for t in targets.values()):
        raise FileExistsError(
            "Label sheets already exist in results/labels. They may contain your work, so they were "
            "not overwritten. Use --append to label only the new runs in a new batch, or pass "
            "force=True only if you really want fresh, empty sheets.")
    rng = random.Random(L.get("seed", 7) + batch - 1)

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
        code = f"{prefix['harmful']}{i:03d}"
        hs.append({"item_code": code, "goal": g["goal"], "n_turns": len(g["turns"]),
                   "transcript": _transcript(g["turns"], g.get("backtracks")),
                   "violation_A": "", "first_turn_A": "", "violation_B": "", "first_turn_B": "",
                   "final_violation": "", "final_first_turn": "", "notes": ""})
        hk.append({"item_code": code, "run_id": g["run_id"], "flagged": g in flagged})
    pd.DataFrame(hs, columns=["item_code", "goal", "n_turns", "transcript", "violation_A", "first_turn_A",
                              "violation_B", "first_turn_B", "final_violation", "final_first_turn", "notes"]
                 ).to_csv(targets["harmful"], index=False)
    pd.DataFrame(hk, columns=["item_code", "run_id", "flagged"]).to_csv(keys["harmful"], index=False)

    # ---- benign: all responses (or the same sampling rule)
    ben = [g for g in gens if g["condition"] == "benign"]
    if not L.get("label_all_benign", True):
        ben = rng.sample(ben, round(len(ben) * L.get("sample_fraction_unflagged", 0.25)))
    rng.shuffle(ben)
    bs, bk = [], []
    for i, g in enumerate(ben, start=1):
        code = f"{prefix['benign']}{i:03d}"
        t = g["turns"][0]
        bs.append({"item_code": code, "prompt": t["user"],
                   "response": t["assistant"] or ("[no reply: request blocked by the provider]" if t.get("blocked") else "[empty reply]"),
                   "class_A": "", "class_B": "", "final_class": "", "notes": ""})
        bk.append({"item_code": code, "run_id": g["run_id"]})
    pd.DataFrame(bs, columns=["item_code", "prompt", "response", "class_A", "class_B", "final_class", "notes"]
                 ).to_csv(targets["benign"], index=False)
    pd.DataFrame(bk, columns=["item_code", "run_id"]).to_csv(keys["benign"], index=False)
    log(f"wrote {len(hs)} harmful items ({len(flagged)} flagged + {k} sampled) and {len(bs)} benign items "
        f"to {targets['harmful'].name} and {targets['benign'].name} in {p.labels_dir}")


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

    hp = _sheet_pairs(p.labels_dir, "harmful")
    if hp:
        h = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False).merge(pd.read_csv(k), on="item_code")
                       .assign(batch=n) for f, k, n in hp], ignore_index=True)
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
        out["harmful"] = h[["run_id", "item_code", "batch", "violation", "first_turn", "violation_A", "violation_B"]]

    bp = _sheet_pairs(p.labels_dir, "benign")
    if bp:
        b = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False).merge(pd.read_csv(k), on="item_code")
                       .assign(batch=n) for f, k, n in bp], ignore_index=True)
        for c in ["class_A", "class_B", "final_class"]:
            b[c] = _num(b[c])
        b["human_class"] = b["final_class"].where(b["final_class"].notna(), b["class_A"].where(b["class_A"] == b["class_B"]))
        out["agreement"]["benign_class_kappa"] = cohen_kappa(b["class_A"], b["class_B"])
        out["agreement"]["benign_n_double_labelled"] = int((b["class_A"].notna() & b["class_B"].notna()).sum())
        unres = b[b["human_class"].isna() & b["class_A"].notna() & b["class_B"].notna()]
        out["unresolved"] += [f"{c}: annotators disagree on class" for c in unres["item_code"]]
        out["benign"] = b[["run_id", "item_code", "human_class", "class_A", "class_B"]]
    return out
