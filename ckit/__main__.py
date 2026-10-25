"""Command line: python -m ckit <step> [options]

Steps, in order:
  check      validate the scenario and benign files
  generate   run the models (GPU) -> generations.jsonl
  judge      StrongREJECT + XSTest classifier -> judgments.jsonl
  labels     write blinded labelling sheets for both annotators
  analyze    tables, tests, figures and summary.md
  excerpt    print a redacted excerpt of one run, for the report
"""
from __future__ import annotations

import argparse

from .common import load_config, paths, read_jsonl


def redact(text: str, words: int = 25) -> str:
    w = text.split()
    return " ".join(w[:words]) + (" [... redacted]" if len(w) > words else "")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ckit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["check", "generate", "judge", "labels", "analyze", "excerpt"])
    ap.add_argument("--config", default=None)
    ap.add_argument("--results", default=None, help="results folder (overrides config)")
    ap.add_argument("--mock", action="store_true", help="use the fake model and judge (no GPU)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N scenarios/prompts (pilot)")
    ap.add_argument("--models", nargs="*", default=None, help="model keys to run (default: all)")
    ap.add_argument("--conditions", nargs="*", default=["single", "crescendo", "benign"])
    ap.add_argument("--force", action="store_true", help="labels: overwrite existing sheets")
    ap.add_argument("--run-id", default=None, help="excerpt: which run")
    ap.add_argument("--words", type=int, default=25)
    a = ap.parse_args(argv)
    cfg = load_config(a.config, a.results)

    if a.step == "check":
        from .scenarios import load_benign, load_harmful
        h = load_harmful(cfg["data"]["harmful_scenarios"])
        bn = load_benign(cfg["data"]["benign_prompts"])
        g = cfg["generation"]
        n_turns = sum(len(s.turns) for s in h)
        print(f"OK: {len(h)} harmful scenarios ({n_turns} Crescendo turns), {len(bn)} benign prompts")
        per_model = len(h) * 2 * g["runs_per_condition"] + len(bn) * g["runs_per_condition"]
        print(f"Plan: {per_model} runs per model x {len(cfg['models'])} models = {per_model * len(cfg['models'])} runs")
    elif a.step == "generate":
        from .generate import run_all
        run_all(cfg, mock=a.mock, model_keys=a.models, conditions=a.conditions, limit=a.limit)
    elif a.step == "judge":
        from .judge import judge_all
        judge_all(cfg, mock=a.mock)
    elif a.step == "labels":
        from .labels import export_sheets
        export_sheets(cfg, force=a.force)
    elif a.step == "analyze":
        from .analysis import run_analysis
        run_analysis(cfg)
    elif a.step == "excerpt":
        for r in read_jsonl(paths(cfg).generations):
            if r["run_id"] == a.run_id:
                for t in r["turns"]:
                    print(f"USER {t['turn']}: {t['user']}\nMODEL {t['turn']}: {redact(t['assistant'], a.words)}\n")
                break
        else:
            print("run not found")


if __name__ == "__main__":
    main()
