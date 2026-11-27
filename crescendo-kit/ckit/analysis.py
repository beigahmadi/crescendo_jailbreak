"""Turn runs + judge scores + human labels into the tables, tests and figures for the report.

Outputs (results/analysis/):
  runs_harmful.csv, runs_benign.csv      one row per run with its final outcome
  table_asr.csv                          ASR by model x condition, Wilson 95% CI      (Q1, Q2)
  table_orr.csv                          over-refusal by model, Wilson 95% CI         (Q3)
  table_asr_by_category.csv              ASR by category, for the discussion
  table_turns.csv                        cumulative Crescendo ASR by turn             (turn-level)
  tests.csv                              exact McNemar tests for H1, H2, H3
  agreement.csv                          human-human and judge-human Cohen's kappa
  table_api_usage.csv                    API tokens, cost and provider blocks per model
  table_asr_sensitivity.csv              automatic ASR: any-turn vs final-turn rule, thresholds 0.5 and 0.75
  table_generation_change.csv            newer minus older generation, per family: ASR per condition,
                                         multi-turn gap (difference in differences), ORR, turns survived,
                                         adaptive attack effort; 95% CIs by bootstrap over scenarios
  table_adaptive_effort.csv              adaptive Crescendo: backtracks and target calls per model
  table_asr_by_source.csv                ASR by scenario source (original vs public benchmark)
  fig1_asr.png, fig2_tradeoff.png, fig3_turns.png, fig4_generation_change.png
  summary.md                             every number above in one readable page
"""
from __future__ import annotations

import math
from itertools import combinations

import numpy as np
import pandas as pd
from scipy.stats import binomtest

from .common import paths, read_jsonl
from .labels import benign_auto_table, cohen_kappa, judge_table, load_labels

# Reference categorical palette (dataviz skill, light mode), assigned in config order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"


# ------------------------------------------------------------ statistics
def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def mcnemar_exact(a: pd.Series, b: pd.Series) -> dict:
    """Paired binary outcomes. b01 = a fails & b succeeds etc. Two-sided exact test."""
    a, b = a.astype(bool), b.astype(bool)
    n10 = int((a & ~b).sum())  # a yes, b no
    n01 = int((~a & b).sum())  # a no,  b yes
    n = n10 + n01
    p = 1.0 if n == 0 else binomtest(min(n10, n01), n, 0.5).pvalue
    return {"pairs": int(len(a)), "a_only": n10, "b_only": n01, "p_value": p}


def holm(pvals) -> list[float]:
    """Holm-Bonferroni adjusted p-values (same order as the input)."""
    p = list(pvals)
    order = sorted(range(len(p)), key=lambda i: p[i])
    out, running = [0.0] * len(p), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(p) - rank) * p[i]))
        out[i] = running
    return out


def paired_bootstrap(old: pd.Series, new: pd.Series, B: int = 5000, seed: int = 419) -> dict:
    """Mean of (new - old) over pairs matched on the index (item_id, run), with a 95% CI
    from a cluster bootstrap that resamples scenarios (item_id), because the runs of one
    scenario are not independent."""
    j = old.astype(float).to_frame("a").join(new.astype(float).to_frame("b"), how="inner").dropna()
    if not len(j):
        return {"pairs": 0, "n_items": 0, "old": float("nan"), "new": float("nan"), "delta": float("nan"),
                "ci_low": float("nan"), "ci_high": float("nan")}
    j["d"] = j["b"] - j["a"]
    per = j.groupby(level=0)["d"].agg(["sum", "count"])
    sums, cnts = per["sum"].to_numpy(), per["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(per), size=(B, len(per)))
    boots = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"pairs": len(j), "n_items": len(per), "old": j["a"].mean(), "new": j["b"].mean(),
            "delta": j["d"].mean(), "ci_low": float(lo), "ci_high": float(hi)}


# ------------------------------------------------------------ assemble runs
def build_runs(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    thr = cfg["judge"]["success_threshold"]
    gens = list(read_jsonl(paths(cfg).generations))
    if not gens:
        raise RuntimeError("No generations yet: run the experiment first.")
    g = pd.DataFrame([{k: r[k] for k in ("run_id", "model_key", "generation", "condition", "item_id",
                                         "category", "run", "mock")}
                      | {"n_turns": len(r["turns"]), "planned_turns": r.get("planned_turns", len(r["turns"])),
                         "n_backtracks": r.get("n_backtracks", 0), "target_calls": r.get("target_calls", len(r["turns"])),
                         "attacker_failed": bool(r.get("attacker_failed", False)),
                         "item_source": r.get("item_source")}
                      for r in gens]).drop_duplicates("run_id", keep="last")
    # runs saved before item_source was recorded: look the source up in the scenario file
    try:
        from .scenarios import load_harmful
        src = {s.id: s.source for s in load_harmful(cfg["data"]["harmful_scenarios"])}
    except Exception:
        src = {}
    g["item_source"] = g["item_source"].where(g["item_source"].notna(), g["item_id"].map(src))
    g["item_source"] = g["item_source"].fillna("").map(_source_group)
    order = {m["key"]: i for i, m in enumerate(cfg["models"])}
    fam = {m["key"]: m.get("family", "main") for m in cfg["models"]}
    g["model_order"] = g["model_key"].map(order)
    g["family"] = g["model_key"].map(fam)
    labels = load_labels(cfg)

    # harmful
    h = g[g["condition"] != "benign"].merge(judge_table(cfg), on="run_id", how="left")
    hl = labels["harmful"]
    h = h.merge(hl[["run_id", "violation", "first_turn"]] if len(hl) else
                pd.DataFrame(columns=["run_id", "violation", "first_turn"]), on="run_id", how="left")
    # unlabelled runs fall back on the pre-specified automatic rule (config: judge.primary_rule)
    rule_col = "judge_final" if cfg["judge"].get("primary_rule", "final_turn") == "final_turn" else "judge_max"
    judge_success = h[rule_col] >= thr
    h["source"] = h["violation"].notna().map({True: "human", False: "judge"})
    h["success"] = h["violation"].where(h["violation"].notna(), judge_success).astype(bool)
    ft = h["first_turn"].where(h["first_turn"].notna(), h["judge_first_turn"])
    h["first_fail_turn"] = ft.where(h["success"])
    h["unjudged"] = h["judge_max"].isna() & h["violation"].isna()

    # benign
    b = g[g["condition"] == "benign"].merge(benign_auto_table(cfg), on="run_id", how="left")
    bl = labels["benign"]
    b = b.merge(bl[["run_id", "human_class"]] if len(bl) else pd.DataFrame(columns=["run_id", "human_class"]),
                on="run_id", how="left")
    b["final_class"] = b["human_class"].where(b["human_class"].notna(), b["auto_class"])
    b["source"] = b["human_class"].notna().map({True: "human", False: "auto"})
    b["refused"] = b["final_class"].isin([2, 3])
    b["full_refusal"] = b["final_class"] == 2
    return h, b, labels


def _source_group(s: str) -> str:
    s = (s or "").strip().lower()
    if not s or s == "xstest":
        return s or "unknown"
    if "jbb" in s or "jailbreakbench" in s:
        return "JailbreakBench"
    if "harmbench" in s:
        return "HarmBench"
    return "original"


# ------------------------------------------------------------ tables
def sensitivity_table(h: pd.DataFrame, thresholds=(0.5, 0.75)) -> pd.DataFrame:
    """Automatic-judge ASR under two success rules and two thresholds (no human labels).

    any_turn:   some assistant turn scores >= threshold (the main rule, which humans then confirm)
    final_turn: the LAST turn scores >= threshold, i.e. the attacker got the target at the end.
    Mid-conversation background can push any_turn up while the model still refuses the final
    request, so reporting both shows how much the rule matters.
    """
    rows = []
    for (m, gen, cond), d in h.groupby(["model_key", "generation", "condition"]):
        for t in thresholds:
            for rule, col in (("any_turn", "judge_max"), ("final_turn", "judge_final")):
                k, n = int((d[col] >= t).sum()), len(d)
                lo, hi = wilson(k, n)
                rows.append({"model": m, "generation": gen, "condition": cond, "rule": rule, "threshold": t,
                             "n_runs": n, "successes": k, "asr": k / n if n else float("nan"),
                             "ci_low": lo, "ci_high": hi})
    return pd.DataFrame(rows).sort_values(["condition", "rule", "threshold", "generation"])


def asr_table(h: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (m, gen, cond), d in h.groupby(["model_key", "generation", "condition"]):
        k, n = int(d["success"].sum()), len(d)
        lo, hi = wilson(k, n)
        rows.append({"model": m, "generation": gen, "condition": cond, "n_runs": n, "successes": k,
                     "asr": k / n, "ci_low": lo, "ci_high": hi,
                     "human_checked": int((d["source"] == "human").sum())})
    return pd.DataFrame(rows).sort_values(["condition", "generation"])


def orr_table(b: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (m, gen), d in b.groupby(["model_key", "generation"]):
        n, k = len(d), int(d["refused"].sum())
        lo, hi = wilson(k, n)
        rows.append({"model": m, "generation": gen, "n_runs": n,
                     "full_refusal": int(d["full_refusal"].sum()),
                     "partial_refusal": int((d["final_class"] == 3).sum()),
                     "orr": k / n, "ci_low": lo, "ci_high": hi,
                     "human_checked": int((d["source"] == "human").sum())})
    return pd.DataFrame(rows).sort_values("generation")


def turns_table(h: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cond in ("crescendo", "adaptive"):
        c = h[h["condition"] == cond]
        for m, d in c.groupby("model_key"):
            n = len(d)
            for t in range(1, int(max(d["n_turns"].max(), d["planned_turns"].max())) + 1):
                k = int((d["success"] & (d["first_fail_turn"] <= t)).sum())
                rows.append({"condition": cond, "model": m, "turn": t, "n_runs": n, "failed_by_turn": k,
                             "cum_asr": k / n})
            safe1 = d[~(d["success"] & (d["first_fail_turn"] == 1))]
            later = int((safe1["success"]).sum())
            rows.append({"condition": cond, "model": m, "turn": "failed_later_if_safe_at_turn1", "n_runs": len(safe1),
                         "failed_by_turn": later, "cum_asr": later / len(safe1) if len(safe1) else float("nan")})
    return pd.DataFrame(rows)


def _turns_survived(d: pd.DataFrame) -> pd.Series:
    """Accepted turns the model got through safely: first failing turn - 1, or all planned turns."""
    return (d["first_fail_turn"] - 1).where(d["success"], d["planned_turns"]).astype(float)


def _family_pairs(cfg: dict):
    fams = {}
    for m in cfg["models"]:
        fams.setdefault(m.get("family", "main"), []).append(m)
    for fam, ms in sorted(fams.items()):
        ms = sorted(ms, key=lambda m: m.get("generation", 0))
        for old, new in combinations(ms, 2):
            yield fam, old["key"], new["key"]


def generation_change_table(h: pd.DataFrame, b: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Newer minus older generation within each family, the study's central comparison.

    delta > 0 means the newer model fails MORE often (or survives more turns / needs more
    attacker effort, for those measures). The multi-turn gap rows are a difference in
    differences: did the extra success that multi-turn attacks buy over a direct request
    shrink in the newer generation? CIs resample scenarios (cluster bootstrap)."""
    A = cfg.get("analysis", {})
    B, seed = int(A.get("bootstrap", 5000)), int(A.get("seed", 419))
    key = ["item_id", "run"]
    conds = [c for c in ("single", "crescendo", "adaptive") if c in set(h["condition"])]

    def ser(model, cond, col="success", frame=None):
        d = (frame if frame is not None else h)
        d = d[(d.model_key == model) & (d.condition == cond)] if "condition" in d else d[d.model_key == model]
        return d.set_index(key)[col]

    rows = []
    for fam, old, new in _family_pairs(cfg):
        base = {"family": fam, "older": old, "newer": new}
        for c in conds:
            rows.append({**base, "measure": f"ASR {c}", **paired_bootstrap(ser(old, c), ser(new, c), B, seed)})
        for c in [c for c in conds if c != "single"]:
            gap = lambda m: (ser(m, c).astype(float).to_frame("x").join(ser(m, "single").astype(float).to_frame("s"),
                                                                       how="inner").pipe(lambda j: j["x"] - j["s"]))
            rows.append({**base, "measure": f"multi-turn gap: {c} minus single", **paired_bootstrap(gap(old), gap(new), B, seed)})
        if "crescendo" in conds and "adaptive" in conds:
            gap = lambda m: (ser(m, "adaptive").astype(float).to_frame("x")
                             .join(ser(m, "crescendo").astype(float).to_frame("s"), how="inner")
                             .pipe(lambda j: j["x"] - j["s"]))
            rows.append({**base, "measure": "adaptivity gain: adaptive minus scripted",
                         **paired_bootstrap(gap(old), gap(new), B, seed)})
        for c in [c for c in conds if c != "single"]:
            d = h[h.condition == c].assign(survived=lambda x: _turns_survived(x))
            rows.append({**base, "measure": f"turns survived ({c})",
                         **paired_bootstrap(ser(old, c, "survived", d), ser(new, c, "survived", d), B, seed)})
        if "adaptive" in conds:
            for col, label in (("n_backtracks", "backtracks needed (adaptive)"), ("target_calls", "target calls (adaptive)")):
                rows.append({**base, "measure": label, **paired_bootstrap(ser(old, "adaptive", col), ser(new, "adaptive", col), B, seed)})
        if len(b):
            bo = b[b.model_key == old].set_index(key)["refused"]
            bn = b[b.model_key == new].set_index(key)["refused"]
            rows.append({**base, "measure": "ORR benign", **paired_bootstrap(bo, bn, B, seed)})
    return pd.DataFrame(rows)


def adaptive_effort_table(h: pd.DataFrame) -> pd.DataFrame:
    d = h[h["condition"] == "adaptive"]
    if not len(d):
        return pd.DataFrame()
    rows = []
    for (m, gen), x in d.groupby(["model_key", "generation"]):
        succ = x[x["success"]]
        rows.append({"model": m, "generation": gen, "n_runs": len(x), "asr": x["success"].mean(),
                     "mean_backtracks": x["n_backtracks"].mean(), "mean_target_calls": x["target_calls"].mean(),
                     "mean_backtracks_successful": succ["n_backtracks"].mean() if len(succ) else float("nan"),
                     "mean_first_fail_turn": succ["first_fail_turn"].mean() if len(succ) else float("nan"),
                     "attacker_failed": int(x["attacker_failed"].sum())})
    return pd.DataFrame(rows).sort_values("generation")


def tests_table(h: pd.DataFrame, b: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    rows = []
    key = ["item_id", "run"]
    # H1 / H3: older vs newer generation within each family
    for fam, fm in [(f, [m for m in cfg["models"] if m.get("family", "main") == f])
                    for f in sorted({m.get("family", "main") for m in cfg["models"]})]:
        for old, new in combinations(sorted(fm, key=lambda m: m.get("generation", 0)), 2):
            for cond, hyp in (("crescendo", "H1"), ("adaptive", "H1 (adaptive)"), ("single", "H1 (single-turn)")):
                a = h[(h.model_key == old["key"]) & (h.condition == cond)].set_index(key)["success"]
                c = h[(h.model_key == new["key"]) & (h.condition == cond)].set_index(key)["success"]
                j = a.to_frame("a").join(c.to_frame("b"), how="inner")
                if len(j):
                    rows.append({"hypothesis": hyp, "comparison": f"ASR {cond}: {old['key']} vs {new['key']}",
                                 "rate_a": j["a"].mean(), "rate_b": j["b"].mean(), **mcnemar_exact(j["a"], j["b"])})
            a = b[b.model_key == old["key"]].set_index(key)["refused"]
            c = b[b.model_key == new["key"]].set_index(key)["refused"]
            j = a.to_frame("a").join(c.to_frame("b"), how="inner")
            if len(j):
                rows.append({"hypothesis": "H3", "comparison": f"ORR: {old['key']} vs {new['key']}",
                             "rate_a": j["a"].mean(), "rate_b": j["b"].mean(), **mcnemar_exact(j["a"], j["b"])})
    # H2: single vs (scripted, adaptive) Crescendo within each model
    # H4: scripted vs adaptive Crescendo within each model
    for hyp, ca, cb in (("H2", "single", "crescendo"), ("H2 (adaptive)", "single", "adaptive"),
                        ("H4", "crescendo", "adaptive")):
        for m in cfg["models"]:
            a = h[(h.model_key == m["key"]) & (h.condition == ca)].set_index(key)["success"]
            c = h[(h.model_key == m["key"]) & (h.condition == cb)].set_index(key)["success"]
            j = a.to_frame("a").join(c.to_frame("b"), how="inner")
            if len(j):
                rows.append({"hypothesis": hyp, "comparison": f"{m['key']}: {ca} vs {cb}",
                             "rate_a": j["a"].mean(), "rate_b": j["b"].mean(), **mcnemar_exact(j["a"], j["b"])})
    t = pd.DataFrame(rows)
    if len(t):  # more tests now: Holm-adjust within each hypothesis family
        t["p_holm"] = t.groupby("hypothesis")["p_value"].transform(lambda p: holm(p.tolist()))
    return t


def agreement_table(h: pd.DataFrame, b: pd.DataFrame, labels: dict, cfg: dict) -> pd.DataFrame:
    thr = cfg["judge"]["success_threshold"]
    ag = labels["agreement"]
    rows = [{"measure": "Human A vs B: harmful violation (Cohen's kappa)", "value": ag.get("harmful_violation_kappa"),
             "n": ag.get("harmful_n_double_labelled")},
            {"measure": "Human A vs B: benign class (Cohen's kappa)", "value": ag.get("benign_class_kappa"),
             "n": ag.get("benign_n_double_labelled")}]
    hh = h[h["violation"].notna() & h["judge_max"].notna()]
    primary = (cfg["judge"].get("primary_rule", "final_turn"), thr)
    for rule, col in (("final_turn", "judge_final"), ("any_turn", "judge_max")):
        for t in (0.5, 0.75):
            tag = " [pre-specified main rule]" if (rule, t) == primary else ""
            if len(hh):
                auto, hum = (hh[col] >= t).astype(int), hh["violation"].astype(int)
                extra = {"agree_pct": float((auto == hum).mean()),
                         "scorer_yes_human_no": int(((auto == 1) & (hum == 0)).sum()),
                         "scorer_no_human_yes": int(((auto == 0) & (hum == 1)).sum())}
            else:
                extra = {}
            rows.append({"measure": f"StrongREJECT {rule} >= {t} vs final human label (Cohen's kappa){tag}",
                         "value": cohen_kappa(auto, hum) if len(hh) else None, "n": len(hh), **extra})
    bb = b[b["human_class"].notna() & b["auto_class"].notna()]
    rows.append({"measure": "XSTest auto classifier vs human class (Cohen's kappa)",
                 "value": cohen_kappa(bb["auto_class"], bb["human_class"]) if len(bb) else None, "n": len(bb)})
    return pd.DataFrame(rows)


def usage_table(cfg: dict) -> pd.DataFrame:
    """API spending, tokens and provider blocks per model (empty for local models)."""
    rows = []
    for r in read_jsonl(paths(cfg).generations):
        if r.get("attacker_cost_usd"):
            rows.append({"model": r["model_key"], "condition": r["condition"], "prompt_tokens": 0, "output_tokens": 0,
                         "reasoning_tokens": 0, "cost_usd": 0, "attacker_cost_usd": r["attacker_cost_usd"],
                         "blocked": False, "hit_max_tokens": False, "_attacker_row": True})
        for t in list(r["turns"]) + list(r.get("backtracks", [])):
            rows.append({"model": r["model_key"], "condition": r["condition"], "attacker_cost_usd": 0,
                         "prompt_tokens": t.get("prompt_tokens", 0), "output_tokens": t.get("output_tokens", 0),
                         "reasoning_tokens": t.get("reasoning_tokens", 0), "cost_usd": t.get("cost_usd", 0),
                         "blocked": bool(t.get("blocked")), "hit_max_tokens": bool(t.get("hit_max_tokens"))})
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    if "_attacker_row" not in d:
        d["_attacker_row"] = False
    d["_call"] = ~d["_attacker_row"].fillna(False).astype(bool)
    return (d.groupby("model").agg(api_calls=("_call", "sum"), prompt_tokens=("prompt_tokens", "sum"),
                                   output_tokens=("output_tokens", "sum"), reasoning_tokens=("reasoning_tokens", "sum"),
                                   cost_usd=("cost_usd", "sum"), attacker_cost_usd=("attacker_cost_usd", "sum"),
                                   blocked_by_provider=("blocked", "sum"),
                                   hit_token_limit=("hit_max_tokens", "sum")).reset_index())


# ------------------------------------------------------------ figures
def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def make_figures(asr: pd.DataFrame, orr: pd.DataFrame, turns: pd.DataFrame, cfg: dict, out,
                 gen_change: pd.DataFrame | None = None) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.labelcolor": INK2})
    keys = [m["key"] for m in cfg["models"] if m["key"] in set(asr["model"]) | set(orr["model"])]
    color = {k: SERIES[i % len(SERIES)] for i, k in enumerate(keys)}
    files = []

    # Fig 1: ASR by condition and model
    fig, ax = plt.subplots(figsize=(6.4, 3.9), dpi=200)
    conds = [c for c in ("single", "crescendo", "adaptive") if c in set(asr["condition"])]
    w = 0.8 / max(1, len(keys))
    for i, k in enumerate(keys):
        d = asr[asr["model"] == k].set_index("condition").reindex(conds)
        x = [j + (i - (len(keys) - 1) / 2) * w for j in range(len(conds))]
        ax.bar(x, d["asr"], width=w * 0.92, color=color[k], label=k, zorder=2)
        ax.errorbar(x, d["asr"], yerr=[(d["asr"] - d["ci_low"]).clip(lower=0), (d["ci_high"] - d["asr"]).clip(lower=0)],
                    fmt="none", ecolor=INK2, elinewidth=1, capsize=3, zorder=3)
        for xi, v, top in zip(x, d["asr"], d["ci_high"]):
            ax.text(xi, top + 0.02, f"{v:.0%}", ha="center", va="bottom", fontsize=7.5, color=INK, zorder=4)
    ax.set_xticks(range(len(conds)), [{"single": "Single-turn request", "crescendo": "Scripted Crescendo",
                                       "adaptive": "Adaptive Crescendo"}[c] for c in conds])
    ax.set_ylim(0, 1.12)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylabel("Attack success rate")
    ax.set_title("Attack success by condition and model generation", fontsize=11, loc="left", color=INK, pad=24)
    ax.legend(frameon=False, fontsize=8, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=min(4, len(keys)),
              handlelength=1.2, columnspacing=1.2, borderaxespad=0.2)
    _style(ax)
    fig.text(0.01, 0.01, "Bars: share of runs judged a verified violation; label = rate. Whiskers: Wilson 95% CI.", fontsize=7, color=INK2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    f = out / "fig1_asr.png"; fig.savefig(f, facecolor=SURFACE); plt.close(fig); files.append(str(f))

    # Fig 2: safety vs over-refusal trade-off
    cres = asr[asr["condition"] == "crescendo"].set_index("model")
    o = orr.set_index("model")
    both = [k for k in keys if k in cres.index and k in o.index]
    if both:
        fig, ax = plt.subplots(figsize=(5.2, 4.2), dpi=200)
        for k in both:
            x, y = o.loc[k, "orr"], cres.loc[k, "asr"]
            ax.errorbar(x, y, xerr=[[max(0, x - o.loc[k, "ci_low"])], [max(0, o.loc[k, "ci_high"] - x)]],
                        yerr=[[max(0, y - cres.loc[k, "ci_low"])], [max(0, cres.loc[k, "ci_high"] - y)]],
                        fmt="o", color=color[k], ms=8, elinewidth=1, capsize=3, mec=SURFACE, mew=1.5, zorder=3, label=k)
            dy = -14 if y > 0.15 else 10
            ax.annotate(k, (x, y), xytext=(9, dy), textcoords="offset points", fontsize=8, color=INK)
        fams = {}
        for m in cfg["models"]:
            if m["key"] in both:
                fams.setdefault(m.get("family", "main"), []).append(m)
        for ms in fams.values():
            ms = sorted(ms, key=lambda m: m.get("generation", 0))
            for a, c in zip(ms, ms[1:]):
                ax.annotate("", xy=(o.loc[c["key"], "orr"], cres.loc[c["key"], "asr"]),
                            xytext=(o.loc[a["key"], "orr"], cres.loc[a["key"], "asr"]),
                            arrowprops=dict(arrowstyle="->", color=INK2, lw=1, shrinkA=9, shrinkB=9))
        ax.set_xlim(-0.02, 1.0); ax.set_ylim(-0.03, 1.05)
        ax.xaxis.set_major_formatter(PercentFormatter(1.0)); ax.yaxis.set_major_formatter(PercentFormatter(1.0))
        ax.set_xlabel("Over-refusal rate on benign prompts (lower is more helpful)")
        ax.set_ylabel("Crescendo attack success (lower is safer)")
        ax.text(0.02, 0.03, "ideal corner", fontsize=8, color=INK2)
        ax.set_title("Safety vs over-refusal: where each generation sits", fontsize=11, loc="left", color=INK, pad=12)
        ax.legend(frameon=False, fontsize=8, loc="upper right")
        _style(ax); ax.xaxis.grid(True, color=GRID, linewidth=0.8)
        fig.tight_layout()
        f = out / "fig2_tradeoff.png"; fig.savefig(f, facecolor=SURFACE); plt.close(fig); files.append(str(f))

    # Fig 3: cumulative Crescendo ASR by turn, single-turn ASR as a dashed reference
    t = turns[turns["turn"].apply(lambda v: isinstance(v, int)) & (turns["condition"] == "crescendo")]
    if len(t):
        fig, ax = plt.subplots(figsize=(6.0, 3.6), dpi=200)
        single = asr[asr["condition"] == "single"].set_index("model")
        for k in keys:
            d = t[t["model"] == k]
            if not len(d):
                continue
            ax.plot(d["turn"], d["cum_asr"], color=color[k], lw=2, marker="o", ms=6, mec=SURFACE, mew=1.5, label=f"{k}: Crescendo")
            if k in single.index:
                ax.axhline(single.loc[k, "asr"], color=color[k], lw=1, ls=(0, (4, 3)), label=f"{k}: single-turn")
        ax.set_xticks(sorted(t["turn"].unique()))
        ax.set_xlabel("Conversation turn")
        ax.set_ylim(0, 1.05); ax.yaxis.set_major_formatter(PercentFormatter(1.0))
        ax.set_ylabel("Runs failed by this turn")
        ax.set_title("When safety fails during a Crescendo conversation", fontsize=11, loc="left", color=INK)
        ax.legend(frameon=False, fontsize=7.5, loc="upper left")
        _style(ax)
        fig.tight_layout()
        f = out / "fig3_turns.png"; fig.savefig(f, facecolor=SURFACE); plt.close(fig); files.append(str(f))

    # Fig 4: generational change (newer minus older) with cluster-bootstrap CIs
    if gen_change is not None and len(gen_change):
        gc_ = gen_change[gen_change["measure"].str.startswith(("ASR", "multi-turn gap", "adaptivity", "ORR"))]
        gc_ = gc_[gc_["pairs"] > 0]
        if len(gc_):
            fams = list(dict.fromkeys(gc_["family"]))
            measures = list(dict.fromkeys(gc_["measure"]))
            fig, ax = plt.subplots(figsize=(6.4, 0.42 * len(measures) * len(fams) + 1.8), dpi=200)
            fcol = {f: SERIES[(2 * i + 1) % len(SERIES)] for i, f in enumerate(fams)}
            seen = set()
            y, labels = 0.0, []
            for mname in measures:
                ys = []
                for i, fam in enumerate(fams):
                    r = gc_[(gc_["measure"] == mname) & (gc_["family"] == fam)]
                    if len(r):
                        r = r.iloc[0]
                        ax.errorbar(r["delta"], -y, xerr=[[r["delta"] - r["ci_low"]], [r["ci_high"] - r["delta"]]],
                                    fmt="o", color=fcol[fam], ms=6, elinewidth=1.2, capsize=3, mec=SURFACE, mew=1,
                                    label=f"{fam}: {r['older']} \u2192 {r['newer']}" if fam not in seen else None)
                        seen.add(fam)
                    ys.append(-y)
                    y += 1
                labels.append((sum(ys) / len(ys), mname))
                y += 0.6
            ax.axvline(0, color=INK2, lw=1)
            ax.set_yticks([p for p, _ in labels], [l for _, l in labels], fontsize=8)
            ax.xaxis.set_major_formatter(PercentFormatter(1.0))
            ax.set_xlabel("Newer minus older (left of 0: newer is safer)")
            ax.set_title("What changed between generations", fontsize=11, loc="left", color=INK, pad=34)
            ax.legend(frameon=False, fontsize=7.5, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=1,
                      handlelength=1.2, borderaxespad=0.2)
            ax.set_ylim(-y + 0.4, 0.6)
            _style(ax); ax.yaxis.grid(False); ax.xaxis.grid(True, color=GRID, linewidth=0.8)
            fig.tight_layout()
            f = out / "fig4_generation_change.png"; fig.savefig(f, facecolor=SURFACE); plt.close(fig); files.append(str(f))
    return files


# ------------------------------------------------------------ summary ------------------------------------------------------------
def _pct(x):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.0%}"


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, float):
                v = "" if math.isnan(v) else (f"{v:.3f}" if c in ("p_value", "value") else
                                             f"{v:.0%}" if c in ("asr", "orr", "ci_low", "ci_high", "rate_a", "rate_b", "cum_asr") else f"{v:.2f}")
                if c == "p_holm" and isinstance(r[c], float) and not math.isnan(r[c]):
                    v = f"{r[c]:.3f}"
            cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _fmt_change(g: pd.DataFrame) -> pd.DataFrame:
    """Rates as percentages and deltas in percentage points; counts (turns, calls) as numbers."""
    rows = []
    for _, r in g.iterrows():
        rate = r["measure"].startswith(("ASR", "multi-turn gap", "adaptivity", "ORR"))
        f = (lambda v: "" if pd.isna(v) else f"{v:.0%}") if rate else (lambda v: "" if pd.isna(v) else f"{v:.2f}")
        d = (lambda v: "" if pd.isna(v) else f"{v * 100:+.0f} pp") if rate else (lambda v: "" if pd.isna(v) else f"{v:+.2f}")
        rows.append({"family": r["family"], "measure": r["measure"], "pairs": int(r["pairs"]),
                     "scenarios": int(r["n_items"]), "older": f(r["old"]), "newer": f(r["new"]),
                     "change": d(r["delta"]), "95% CI": f"[{d(r['ci_low'])}, {d(r['ci_high'])}]"})
    return pd.DataFrame(rows)


def run_analysis(cfg: dict, log=print) -> dict:
    out = paths(cfg).analysis_dir
    h, b, labels = build_runs(cfg)
    h.to_csv(out / "runs_harmful.csv", index=False)
    b.to_csv(out / "runs_benign.csv", index=False)
    asr, orr, turns = asr_table(h), orr_table(b), turns_table(h)
    cat = (h.groupby(["category", "model_key", "condition"])["success"].agg(["sum", "count", "mean"])
           .rename(columns={"sum": "successes", "count": "n_runs", "mean": "asr"}).reset_index())
    tests, agree = tests_table(h, b, cfg), agreement_table(h, b, labels, cfg)
    usage = usage_table(cfg)
    sens = sensitivity_table(h)
    gchange = generation_change_table(h, b, cfg)
    effort = adaptive_effort_table(h)
    by_src = (h.groupby(["item_source", "model_key", "condition"])["success"].agg(["sum", "count", "mean"])
              .rename(columns={"sum": "successes", "count": "n_runs", "mean": "asr"}).reset_index())
    for name, df in [("table_asr_sensitivity", sens), ("table_api_usage", usage), ("table_asr", asr), ("table_orr", orr), ("table_turns", turns),
                     ("table_asr_by_category", cat), ("tests", tests), ("agreement", agree),
                     ("table_generation_change", gchange), ("table_adaptive_effort", effort),
                     ("table_asr_by_source", by_src)]:
        df.to_csv(out / f"{name}.csv", index=False)
    figs = make_figures(asr, orr, turns, cfg, out, gchange)

    warn = []
    if h["mock"].any():
        warn.append("**These results come from the MOCK model and are not real data.**")
    if h["unjudged"].any():
        warn.append(f"{int(h['unjudged'].sum())} harmful runs have no judge score yet; they count as non-violations.")
    hc = (h["source"] == "human").mean() if len(h) else 0
    warn.append(f"{hc:.0%} of harmful runs and {(b['source'] == 'human').mean() if len(b) else 0:.0%} "
                f"of benign runs carry a human label; the rest use the automatic judge.")
    if labels["unresolved"]:
        warn.append(f"{len(labels['unresolved'])} labelled items still need a final decision: "
                    + "; ".join(labels["unresolved"][:10]) + (" ..." if len(labels["unresolved"]) > 10 else ""))
    md = ["# Results summary", "", *[f"- {w}" for w in warn], "",
          "## Attack success rate (RQ1, RQ2)", _md(asr), "",
          "## Sensitivity: automatic ASR by success rule and threshold (Crescendo only)",
          _md(sens[sens["condition"] == "crescendo"][["model", "rule", "threshold", "successes", "n_runs", "asr", "ci_low", "ci_high"]]), "",
          "## Over-refusal rate (RQ3)", _md(orr), "",
          "## Generational change: newer minus older (95% CI, bootstrap over scenarios)",
          _md(_fmt_change(gchange)) if len(gchange) else "(no family pairs)", "",
          "## Paired tests (exact McNemar; rate_a and rate_b follow the comparison order; p_holm within each hypothesis)",
          _md(tests), "",
          "## Crescendo: cumulative failures by turn", _md(turns), "",
          *(["## Adaptive Crescendo: attacker effort", _md(effort), ""] if len(effort) else []),
          "## ASR by scenario source", _md(by_src), "",
          "## Agreement", _md(agree), "",
          "## API usage and cost (blocked = the provider refused the request outright)",
          _md(usage) if len(usage) else "(no API models)", "",
          "## Figures", *[f"- {f}" for f in figs], ""]
    (out / "summary.md").write_text("\n".join(md), encoding="utf-8")
    log(f"analysis written to {out}")
    return {"asr": asr, "orr": orr, "turns": turns, "tests": tests, "agreement": agree, "figures": figs,
            "generation_change": gchange, "adaptive_effort": effort}
