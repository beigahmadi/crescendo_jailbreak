"""Extend the benign XSTest sample, keeping every prompt already used.

    python tools/extend_xstest.py xstest_prompts.csv --per-type 5

xstest_prompts.csv comes from github.com/paul-rottger/xstest (CC BY 4.0).
The existing 30 prompts (3 per type) stay; extra safe prompts are drawn per
type with seed 419 until each type has --per-type prompts. 5 per type = 50.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

KIT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xstest_csv")
    ap.add_argument("--per-type", type=int, default=5)
    ap.add_argument("--current", default=str(KIT / "data/benign_xstest_sample.csv"))
    ap.add_argument("--out", default=str(KIT / "data/benign_xstest_sample.csv"))
    ap.add_argument("--seed", type=int, default=419)
    a = ap.parse_args()

    xs = pd.read_csv(a.xstest_csv)
    xs = xs[xs["label"] == "safe"].copy()
    xs["id"] = "xs" + xs["id"].astype(str)
    cur = pd.read_csv(a.current, dtype=str)
    rows = [cur]
    for t, d in xs.groupby("type"):
        have = cur[cur["type"] == t]
        need = a.per_type - len(have)
        if need > 0:
            pool = d[~d["id"].isin(cur["id"])]
            rows.append(pool.sample(need, random_state=a.seed)[["id", "type", "prompt"]])
    out = pd.concat(rows, ignore_index=True)
    order = list(dict.fromkeys(cur["type"]))
    out["_o"] = out["type"].map({t: i for i, t in enumerate(order)})
    out = out.sort_values("_o", kind="stable").drop(columns="_o")
    out.to_csv(a.out, index=False)
    print(f"{len(cur)} -> {len(out)} benign prompts written to {a.out}")


if __name__ == "__main__":
    main()
