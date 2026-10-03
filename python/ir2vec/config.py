"""Frozen vocabulary config: config/vocab_config.json (BUILD_SPEC Phase 3.3).

Written only by `ir2vec freeze-config` (from the capped corpus, D4.4); every
other command reads it and never recomputes it. It fixes, with provenance:
  - the extern whitelist: ONE list shared by both levels, exactly 64 names:
    pins first (each with a reason), then names ranked by the number of
    packages using them (raw count breaks ties), each used by >= 3 packages
    (D3.5, D4.3); plus EXT_OTHER at encoding time;
  - the rare-family merges (a family merges only if every member is rare);
  - per level: impossible entities (hard error at inference, D4.1), the
    fallback map for untrained-but-possible entities (D4.2), the trained
    vocabulary, and low-confidence entities (< threshold triples, D4.5);
  - count_synthetic (D2.3).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .inventory import LEVELS, REPO, Inventory

CONFIG_VERSION = 2
DEFAULT_PATH = REPO / "config" / "vocab_config.json"
DEFAULT_THRESHOLD = 1000
WHITELIST_SIZE = 64
MIN_PACKAGES = 3

# Pinned externs, counted inside the 64 (D3.5). fnmatch patterns -> reason.
PINNED_EXTERNS: dict[str, str] = {
    "caml_atomic_*": "atomics are plain C calls in 5.5.1 (atomic fetch-and-add etc.) (D0.17)",
    "caml_modify": "GC write barrier (D0.17)",
    "caml_compare": "polymorphic comparison (D0.17)",
    "caml_equal": "polymorphic equality (D0.17)",
    "caml_string_compare": "string comparison (D0.17)",
    "caml_string_equal": "string equality (D0.17)",
    "caml_initialize": "GC initialising store (D3.11)",
    "caml_alloc_dummy": "recursive-value allocation (D3.11)",
    "caml_update_dummy": "recursive-value allocation (D3.11)",
    "caml_alloc_dummy_lazy": "recursive lazy-value allocation (D3.11)",
    "caml_update_dummy_lazy": "recursive lazy-value allocation (D3.11)",
    "caml_alloc_shr_check_gc": "major-heap allocation (D3.11)",
    "caml_obj_dup": "block copy (D3.11)",
}

# Never merged, even if rare: a distinctive part of this work (D4.5).
NEVER_MERGE = ("Pperform", "Presume", "Prunstack", "Preperform")


@dataclass
class VocabConfig:
    version: int = CONFIG_VERSION
    ocaml: str = ""
    inventory_sha256: str = ""
    corpus_sha256: str = ""
    selection: dict = field(default_factory=dict)         # cap parameters
    threshold: int = DEFAULT_THRESHOLD
    count_synthetic: bool = False
    extern_min_packages: int = MIN_PACKAGES
    pins: dict[str, str] = field(default_factory=dict)    # pattern -> reason
    pinned_resolved: dict[str, str] = field(default_factory=dict)  # name -> reason
    pinned_zero: list[str] = field(default_factory=list)  # pins absent from corpus
    extern_whitelist: list[str] = field(default_factory=list)
    merges: dict[str, dict[str, list[str]]] = field(
        default_factory=lambda: {"lambda": {}, "cmm": {}})
    family_frequencies: dict[str, dict[str, dict[str, int]]] = field(
        default_factory=lambda: {"lambda": {}, "cmm": {}})
    impossible: dict[str, dict[str, str]] = field(
        default_factory=lambda: {"lambda": {}, "cmm": {}})
    fallback_map: dict[str, dict[str, str]] = field(
        default_factory=lambda: {"lambda": {}, "cmm": {}})
    trained: dict[str, list[str]] = field(default_factory=lambda: {"lambda": [], "cmm": []})
    low_confidence: dict[str, dict[str, int]] = field(
        default_factory=lambda: {"lambda": {}, "cmm": {}})
    coverage: dict[str, dict[str, int]] = field(
        default_factory=lambda: {"lambda": {}, "cmm": {}})
    config_sha256: str = ""

    def merge_map(self, level: str) -> dict[str, str]:
        return {m: fam for fam, members in self.merges[level].items() for m in members}

    def body_sha256(self) -> str:
        body = asdict(self)
        body.pop("config_sha256")
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def save(self, path: Path = DEFAULT_PATH) -> None:
        self.config_sha256 = self.body_sha256()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "VocabConfig":
        if not path.exists():
            raise FileNotFoundError(
                f"{path}: no frozen vocab config; run `ir2vec freeze-config` first")
        d = json.loads(path.read_text())
        if d.get("version") != CONFIG_VERSION:
            raise ValueError(f"{path}: config version {d.get('version')}, expected "
                             f"{CONFIG_VERSION}; rerun `ir2vec freeze-config`")
        cfg = cls(**d)
        if cfg.config_sha256 != cfg.body_sha256():
            raise ValueError(f"{path}: config_sha256 does not match its contents")
        return cfg


_EXTERNAL = re.compile(r'\bexternal\b[^=]*=((?:\s*"[^"]*")+)')


def stdlib_externals(stdlib_dir: Path) -> set[str]:
    """Native names declared by `external` in the pinned stdlib's sources."""
    names: set[str] = set()
    for ml in sorted(stdlib_dir.glob("*.ml")):
        for m in _EXTERNAL.finditer(ml.read_text(errors="replace")):
            names.update(n for n in re.findall(r'"([^"]*)"', m.group(1))
                         if n.startswith("caml_"))
    return names


def resolve_pins(pins: dict[str, str], known: set[str]) -> dict[str, str]:
    """Exact names are always pinned; glob patterns expand over known names."""
    out: dict[str, str] = {}
    for pattern, reason in pins.items():
        if any(c in pattern for c in "*?["):
            for n in sorted(known):
                if fnmatch.fnmatchcase(n, pattern):
                    out.setdefault(n, reason)
        else:
            out.setdefault(pattern, reason)
    return dict(sorted(out.items()))


def build_whitelist(pinned: list[str], packages: Counter, count: Counter,
                    size: int = WHITELIST_SIZE, min_packages: int = MIN_PACKAGES) -> list[str]:
    """Pins first; then by #packages, raw count, name; each in >= min_packages."""
    if len(pinned) > size:
        raise ValueError(f"{len(pinned)} pinned externs exceed the whitelist size {size}")
    rest = sorted((n for n in packages if n not in pinned and packages[n] >= min_packages),
                  key=lambda n: (-packages[n], -count[n], n))
    wl = list(pinned) + rest[: size - len(pinned)]
    if len(wl) < size:
        raise ValueError(f"only {len(wl)} externs qualify for the {size}-name whitelist")
    return wl


def decide_merges(inv: Inventory, participation: dict[str, Counter], threshold: int
                  ) -> tuple[dict[str, dict[str, list[str]]], dict[str, dict[str, dict[str, int]]]]:
    """A family merges only if every member is in fewer than [threshold] triples."""
    merges: dict[str, dict[str, list[str]]] = {}
    freqs: dict[str, dict[str, dict[str, int]]] = {}
    for level in LEVELS:
        merges[level], freqs[level] = {}, {}
        for fam, members in inv.level(level).merge_candidates.items():
            f = {m: participation[level][m] for m in members}
            freqs[level][fam] = f
            if any(m in NEVER_MERGE for m in members):
                continue
            if all(n < threshold for n in f.values()):
                merges[level][fam] = list(members)
    return merges, freqs


class FreezeError(ValueError):
    pass


def resolve_vocabulary(inv: Inventory, level: str, participation: Counter,
                       merge: dict[str, str], threshold: int) -> dict:
    """Trained vocabulary, fallbacks and coverage numbers for one level."""
    lv = inv.level(level)
    bad = {e: participation[e] for e in lv.impossible if participation[e]}
    if bad:
        raise FreezeError(f"{level}: impossible entities occur in the corpus "
                          f"(hook or lowering bug): {bad}")
    post: Counter = Counter()
    for e, n in participation.items():
        post[merge.get(e, e)] += n
    possible = [e for e in lv.entities if e not in lv.impossible]
    trained = sorted({merge.get(e, e) for e in possible if post[merge.get(e, e)] > 0})
    fallback: dict[str, str] = {}
    missing = []
    for e in possible:
        if merge.get(e, e) in trained:
            continue
        cand = lv.fallback_candidates.get(e)
        target = merge.get(cand[0], cand[0]) if cand else None
        if target is None or target not in trained:
            missing.append(e)
        else:
            fallback[e] = target
    if missing:
        raise FreezeError(f"{level}: untrained entities without a trained fallback: {missing}")
    seen_pre = sum(1 for e in lv.entities if participation[e] > 0)
    return {
        "trained": trained,
        "fallback_map": dict(sorted(fallback.items())),
        "impossible": dict(sorted(lv.impossible.items())),
        "low_confidence": {e: post[e] for e in trained if post[e] < threshold},
        "coverage": {
            "inventory": len(lv.entities),
            "trained_entities": seen_pre,          # pre-merge entities with triples
            "trained_vocabulary": len(trained),    # post-merge vectors to learn
            "merged_away": sum(1 for e in possible if merge.get(e, e) != e),
            "fallback_mapped": len(fallback),
            "impossible": len(lv.impossible),
        },
    }


def freeze(inv: Inventory, stats: dict, corpus_sha256: str, stdlib_names: set[str],
           selection: dict | None = None, threshold: int = DEFAULT_THRESHOLD) -> VocabConfig:
    ext = stats["externs"]
    count, packages = Counter(ext["combined"]), Counter(ext["packages"])
    pinned = resolve_pins(PINNED_EXTERNS, set(count) | stdlib_names)
    participation = {lv: Counter(stats[lv]["entity_triples"]) for lv in LEVELS}
    merges, freqs = decide_merges(inv, participation, threshold)
    cfg = VocabConfig(
        ocaml=inv.ocaml, inventory_sha256=inv.sha256, corpus_sha256=corpus_sha256,
        selection=selection or {}, threshold=threshold, count_synthetic=False,
        pins=dict(PINNED_EXTERNS), pinned_resolved=pinned,
        pinned_zero=sorted(n for n in pinned if count[n] == 0),
        extern_whitelist=build_whitelist(list(pinned), packages, count),
        merges=merges, family_frequencies=freqs)
    for level in LEVELS:
        v = resolve_vocabulary(inv, level, participation[level],
                               cfg.merge_map(level), threshold)
        cfg.trained[level] = v["trained"]
        cfg.fallback_map[level] = v["fallback_map"]
        cfg.impossible[level] = v["impossible"]
        cfg.low_confidence[level] = v["low_confidence"]
        cfg.coverage[level] = v["coverage"]
    return cfg
