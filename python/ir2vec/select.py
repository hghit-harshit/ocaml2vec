"""Per-package cap on the training corpus (D4.4): $CORPUS/selection.json.

No package may contribute more than `cap` of the selected units. The largest
per-package allowance x with  x <= cap * sum_p min(n_p, x)  is found exactly;
a package over x keeps its x units with the smallest SHA-256(unit name), so the
sample is reproducible and the same at both levels. Coverage beats balance:
if capping would leave an entity with no triples, the first excluded unit (in
hash order) containing it is added back as an exemption.

Order of operations: select -> stats -> freeze-config -> triples.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .inventory import LEVELS
from .triples import unit_triples

SELECTION_VERSION = 1
DEFAULT_CAP = 0.15


def unit_hash(stem: str) -> str:
    return hashlib.sha256(stem.encode()).hexdigest()


def max_units(counts: list[int], cap: float) -> int:
    """Largest x with x <= cap * sum(min(n, x)); every package fits if possible."""
    if not counts:
        return 0
    feasible = lambda x: x <= cap * sum(min(n, x) for n in counts)  # noqa: E731
    lo, hi = 0, max(counts)
    if feasible(hi):
        return hi
    while lo < hi:                      # feasible(lo) holds; find the last feasible
        mid = (lo + hi + 1) // 2
        if feasible(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def unit_entities(corpus, package: str, stem: str) -> set[str]:
    out: set[str] = set()
    for level in LEVELS:
        path = corpus.root / "json" / package / f"{stem}.{level}.json"
        unit = json.loads(path.read_text())
        for h, _r, t in unit_triples(level, unit, {}, count_synthetic=False):
            out.add(f"{level}:{h}")
            out.add(f"{level}:{t}")
    return out


def select(corpus, cap: float = DEFAULT_CAP) -> dict:
    """[corpus] must be a raw Corpus (no selection applied)."""
    stems = {p: corpus.stems(p) for p in corpus.packages()}
    x = max_units([len(s) for s in stems.values()], cap)
    if x == 0:
        raise ValueError(f"cap {cap:.0%} is infeasible for {len(stems)} packages "
                         f"(needs at least {int(1 / cap) + 1})")
    chosen = {p: sorted(s, key=unit_hash)[:x] for p, s in stems.items()}

    covered: set[str] = set()
    for p, ss in chosen.items():
        for s in ss:
            covered |= unit_entities(corpus, p, s)
    excluded = [(p, s) for p in stems
                for s in sorted(set(stems[p]) - set(chosen[p]), key=unit_hash)]
    excluded_entities = {(p, s): unit_entities(corpus, p, s) for p, s in excluded}
    exemptions = []
    for p, s in excluded:                       # deterministic: manifest, then hash order
        gain = excluded_entities[(p, s)] - covered
        if gain:
            chosen[p].append(s)
            covered |= gain
            exemptions.append({"package": p, "unit": s, "entities": sorted(gain)})

    total = sum(len(v) for v in chosen.values())
    return {
        "version": SELECTION_VERSION,
        "cap": cap,
        "max_units_per_package": x,
        "selected_units": total,
        "raw_units": sum(len(v) for v in stems.values()),
        "packages": {p: {"units": len(stems[p]), "selected": sorted(chosen[p], key=unit_hash),
                         "share": round(len(chosen[p]) / total, 4) if total else 0.0}
                     for p in stems},
        "exemptions": exemptions,
    }


def write(selection: dict, path: Path) -> None:
    path.write_text(json.dumps(selection, indent=1) + "\n")
