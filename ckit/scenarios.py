"""Load and check the scenario files."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

MAX_TURNS = 5
EXCLUDED_WORDS = (  # proposal: no weapons, CBRN or self-harm scenarios
    "weapon", "explosive", "bomb", "chemical", "biolog", "pathogen", "nuclear",
    "radiolog", "self-harm", "self harm", "suicide",
)


@dataclass
class HarmfulScenario:
    id: str
    category: str
    intent: str
    direct_prompt: str
    turns: list[str] = field(default_factory=list)
    source: str = ""


@dataclass
class BenignPrompt:
    id: str
    type: str
    prompt: str


def load_harmful(path: str) -> list[HarmfulScenario]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    need = {"id", "category", "intent"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    turn_cols = [f"turn_{i}" for i in range(1, MAX_TURNS + 1) if f"turn_{i}" in df.columns]
    if not turn_cols:
        raise ValueError(f"{path}: needs columns turn_1 ... turn_{MAX_TURNS}")

    problems, out = [], []
    for _, r in df.iterrows():
        rid = r["id"].strip()
        turns = [r[c].strip() for c in turn_cols if r[c].strip()]
        cells = " ".join(str(v) for v in r.values)
        if "TODO" in cells or "<approved" in cells:
            problems.append(f"{rid}: still contains template placeholders")
        if len(turns) < 2:
            problems.append(f"{rid}: a Crescendo script needs 2-{MAX_TURNS} turns, found {len(turns)}")
        low = (r["category"] + " " + r["intent"]).lower()
        hit = [w for w in EXCLUDED_WORDS if w in low]
        if hit:
            problems.append(f"{rid}: looks out of scope for the approved protocol ({', '.join(hit)})")
        out.append(HarmfulScenario(
            id=rid, category=r["category"].strip(), intent=r["intent"].strip(),
            direct_prompt=(r.get("direct_prompt", "") or r["intent"]).strip(),
            turns=turns, source=r.get("source", "").strip(),
        ))
    ids = [s.id for s in out]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        problems.append(f"duplicate ids: {dupes}")
    if problems:
        raise ValueError("Scenario file problems:\n  - " + "\n  - ".join(problems))
    return out


def load_benign(path: str) -> list[BenignPrompt]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    return [BenignPrompt(id=str(r["id"]), type=r["type"], prompt=r["prompt"]) for _, r in df.iterrows()]
