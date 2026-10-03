"""Seed-vocabulary lookup with the frozen config's rules (D4.1, D4.2, D5.4).

Merges and fallbacks apply at *lookup* only: entity identity is never
rewritten, so counts, reports and triples keep the original name. Every
fallback use is counted. An impossible entity is a hard error (a hook or
lowering bug). An unknown entity is counted, logged and reported with the
result; it contributes a zero vector, and `ir2vec embed` fails on it unless
explicitly allowed.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..config import VocabConfig
from ..inventory import REPO

log = logging.getLogger("ir2vec.encode")

WEIGHTS_PATH = REPO / "config" / "weights.json"


class ImpossibleEntity(RuntimeError):
    pass


@dataclass(frozen=True)
class Weights:
    Wo: float
    Wt: float
    Wa: float
    Wc: float

    @classmethod
    def load(cls, path: Path = WEIGHTS_PATH) -> "Weights":
        return cls(**json.loads(path.read_text()))


@dataclass
class Vocabulary:
    level: str
    path: Path
    vectors: dict[str, np.ndarray]
    merge: dict[str, str]
    fallback: dict[str, str]
    impossible: dict[str, str]
    metadata: dict
    fallbacks_used: Counter = field(default_factory=Counter)
    unknown: Counter = field(default_factory=Counter)

    @property
    def dim(self) -> int:
        return len(next(iter(self.vectors.values())))

    @classmethod
    def load(cls, path: Path, cfg: VocabConfig) -> "Vocabulary":
        d = json.loads(Path(path).read_text())
        meta = d["metadata"]
        if meta.get("config_sha256") != cfg.config_sha256:
            raise ValueError(f"{path}: trained under config {meta.get('config_sha256', '?')[:12]}, "
                             f"but the frozen config is {cfg.config_sha256[:12]}")
        level = meta["level"]
        return cls(level=level, path=Path(path),
                   vectors={k: np.asarray(v, dtype=np.float64) for k, v in d["entities"].items()},
                   merge=cfg.merge_map(level), fallback=dict(cfg.fallback_map[level]),
                   impossible=dict(cfg.impossible[level]), metadata=meta)

    def __call__(self, entity: str) -> np.ndarray:
        if entity in self.impossible:
            raise ImpossibleEntity(f"{self.level} entity {entity} cannot occur on this compiler "
                                   f"path ({self.impossible[entity]}): hook or lowering bug")
        key = self.merge.get(entity, entity)
        if key in self.vectors:
            return self.vectors[key]
        if entity in self.fallback:
            self.fallbacks_used[entity] += 1
            return self.vectors[self.fallback[entity]]
        if not self.unknown[entity]:
            log.warning("unknown %s entity %r: zero vector (reported)", self.level, entity)
        self.unknown[entity] += 1
        return np.zeros(self.dim)

    def report(self) -> dict:
        return {"vocabulary": str(self.path), "model": self.metadata.get("model"),
                "fallbacks_used": dict(sorted(self.fallbacks_used.items())),
                "unknown": dict(sorted(self.unknown.items()))}
