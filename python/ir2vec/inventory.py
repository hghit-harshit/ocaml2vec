"""Entity inventory, read from the build artifact docs/entities.<ocaml>.json.

Entity, relation and count-feature names are defined once, in the OCaml
extractor (extractor/src/entities.ml); Python never redefines them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OCAML = "5.5.1"
LEVELS = ("lambda", "cmm")


def entities_path(ocaml: str = DEFAULT_OCAML) -> Path:
    return REPO / "docs" / f"entities.{ocaml}.json"


@dataclass(frozen=True)
class LevelInventory:
    level: str
    opcodes: tuple[str, ...]
    types: tuple[str, ...]
    operand_kinds: tuple[str, ...]
    relations: tuple[str, ...]
    merge_candidates: dict[str, tuple[str, ...]]
    impossible: dict[str, str]                 # entity -> reason (D4.1)
    fallback_candidates: dict[str, tuple[str, str]]   # entity -> (target, reason)
    count_features: tuple[str, ...]      # fixed buckets, excluding externs
    n_extern_buckets: int

    @property
    def entities(self) -> tuple[str, ...]:
        return self.opcodes + self.types + self.operand_kinds

    @property
    def n_count_features(self) -> int:
        return len(self.count_features) + self.n_extern_buckets


@dataclass(frozen=True)
class Inventory:
    ocaml: str
    sha256: str
    lambda_: LevelInventory
    cmm: LevelInventory

    def level(self, level: str) -> LevelInventory:
        return {"lambda": self.lambda_, "cmm": self.cmm}[level]


def _names(group: dict) -> tuple[str, ...]:
    return tuple(group["names"])


def load(path: Path | None = None) -> Inventory:
    path = path or entities_path()
    raw = path.read_bytes()
    d = json.loads(raw)
    lam, cmm = d["lambda"], d["cmm"]

    def families(lv: dict) -> dict[str, tuple[str, ...]]:
        return {k: tuple(v) for k, v in lv["merge_candidates"].items()}

    def fallbacks(lv: dict) -> dict[str, tuple[str, str]]:
        return {k: (v["target"], v["reason"]) for k, v in lv["fallback_candidates"].items()}

    return Inventory(
        ocaml=d["ocaml"],
        sha256=hashlib.sha256(raw).hexdigest(),
        lambda_=LevelInventory(
            "lambda", _names(lam["forms"]) + _names(lam["primitives"]),
            _names(lam["types"]), _names(lam["operand_kinds"]),
            _names(lam["relations"]), families(lam), dict(lam["impossible"]),
            fallbacks(lam),
            tuple(lam["count_features"]["fixed"]),
            lam["count_features"]["extern_buckets"]),
        cmm=LevelInventory(
            "cmm", _names(cmm["operations"]) + _names(cmm["structural"]),
            _names(cmm["types"]), _names(cmm["operand_kinds"]),
            _names(cmm["relations"]), families(cmm), dict(cmm["impossible"]),
            fallbacks(cmm),
            tuple(cmm["count_features"]["fixed"]),
            cmm["count_features"]["extern_buckets"]),
    )
