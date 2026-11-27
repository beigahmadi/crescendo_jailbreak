"""Shared helpers: config, paths and JSONL files."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import yaml

KIT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Paths:
    root: Path

    @property
    def generations(self) -> Path:
        return self.root / "generations.jsonl"

    @property
    def judgments(self) -> Path:
        return self.root / "judgments.jsonl"

    @property
    def labels_dir(self) -> Path:
        return self.root / "labels"

    @property
    def analysis_dir(self) -> Path:
        return self.root / "analysis"

    def ensure(self) -> "Paths":
        for p in (self.root, self.labels_dir, self.analysis_dir):
            p.mkdir(parents=True, exist_ok=True)
        return self


def load_config(path: str | os.PathLike | None = None, results_dir: str | None = None) -> dict:
    path = Path(path) if path else KIT_ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if results_dir:
        cfg["results_dir"] = results_dir
    # resolves relative data paths against the kit folder
    for k, v in cfg.get("data", {}).items():
        if v and not os.path.isabs(v):
            cfg["data"][k] = str(KIT_ROOT / v)
    rd = cfg.get("results_dir", "results")
    cfg["results_dir"] = rd if os.path.isabs(rd) else str(KIT_ROOT / rd)
    return cfg


def paths(cfg: dict) -> Paths:
    return Paths(Path(cfg["results_dir"])).ensure()


def read_jsonl(path: Path) -> Iterator[dict]:
    if not Path(path).exists():
        return
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # a half-written last line after a Colab disconnect: skip it
                print(f"[warn] skipping unreadable line {i + 1} in {path}")


def append_jsonl(path: Path, rec: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def write_jsonl(path: Path, recs: Iterable[dict]) -> None:
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)
