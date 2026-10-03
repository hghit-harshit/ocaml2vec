"""Display categories for the Phase 8 figures (config/categories.json).

Presentation only: nothing here affects triples, training or encoding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .inventory import REPO, Inventory

PATH = REPO / "config" / "categories.json"


@dataclass(frozen=True)
class Categories:
    order: dict[str, list[str]]              # level -> categories, display order
    of: dict[str, dict[str, str]]            # level -> entity -> category
    status: dict[str, dict[str, str]]        # level -> entity -> note (e.g. unused)

    def members(self, level: str, category: str) -> list[str]:
        return [e for e, c in self.of[level].items() if c == category]


def load(path: Path = PATH) -> Categories:
    d = json.loads(path.read_text())
    order, of = {}, {}
    for level in ("lambda", "cmm"):
        order[level] = list(d[level])
        if not order[level]:
            raise ValueError(f"{level}: no categories")
        of[level] = {}
        for cat, ents in d[level].items():
            for e in ents:
                if e in of[level]:
                    raise ValueError(f"{level}: {e} is in both {of[level][e]!r} and {cat!r}")
                of[level][e] = cat
    status = {lv: dict(d.get("status", {}).get(lv, {})) for lv in ("lambda", "cmm")}
    return Categories(order, of, status)


def problems(cats: Categories, inv: Inventory, trained: dict[str, list[str]]) -> list[str]:
    """Coverage check: every inventory entity, merged family name and trained
    entity has a category; nothing else does."""
    out = []
    for level in ("lambda", "cmm"):
        lv = inv.level(level)
        known = set(lv.entities) | set(lv.merge_candidates)
        mapped = set(cats.of[level])
        for e in sorted((known | set(trained[level])) - mapped):
            out.append(f"{level}: {e} has no category")
        for e in sorted(mapped - known):
            out.append(f"{level}: {e} is not an inventory entity or merge family")
        for e in sorted(set(cats.status[level]) - mapped):
            out.append(f"{level}: status for uncategorised {e}")
    return out


def unused_families(inv: Inventory, level: str, merges: dict[str, list[str]]) -> set[str]:
    """Merge-family names whose family did not merge: listed in the map (so
    coverage stays total) but with no vector, never plotted (D8.0)."""
    return set(inv.level(level).merge_candidates) - set(merges)
