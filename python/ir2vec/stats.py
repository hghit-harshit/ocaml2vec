"""Corpus statistics (BUILD_SPEC Phase 3.2): per level, the frequency of every
opcode, type, operand kind and extern name, and each entity's participation
in (pre-merge) triples, which drives the rare-family merge decision."""

from __future__ import annotations

from collections import Counter

from .inventory import LEVELS, Inventory
from .triples import TripleSummary, kept_instrs, owned_nodes, unit_triples

SCHEMA_ENTITIES = {"lambda": 151, "cmm": 78}   # schema §3, before 5.5.1 (D0.15)


def _occurrences(level: str, unit: dict, opcodes: Counter, types: Counter,
                 kinds: Counter) -> None:
    for f in unit["functions"]:
        if level == "lambda":
            for n in owned_nodes(f):
                opcodes[n["op"]] += 1
                types[n["type"] or "-"] += 1
                kinds.update(p["leaf"] for p in n["positions"] if "leaf" in p)
        else:
            for b in f["blocks"]:
                for i in kept_instrs(b, count_synthetic=False):
                    opcodes[i["op"]] += 1
                    types[i["type"] or "-"] += 1
                    kinds.update(o["kind"] for o in i["operands"])


def compute(corpus, inv: Inventory) -> dict:
    out: dict = {"ocaml": inv.ocaml, "inventory_sha256": inv.sha256,
                 "corpus_sha256": corpus.sha256(), "packages": corpus.packages()}
    externs: dict[str, Counter] = {}
    ext_packages: dict[str, set[str]] = {}
    for level in LEVELS:
        lv = inv.level(level)
        vocab, relations = set(lv.entities), set(lv.relations)
        summary = TripleSummary(level)
        opcodes, types, kinds, ext, counts = Counter(), Counter(), Counter(), Counter(), Counter()
        n_functions = 0
        for pkg, unit in corpus.units(level):
            summary.n_units += 1
            for t in unit_triples(level, unit, {}, count_synthetic=False):
                summary.add(t, vocab, relations)
            _occurrences(level, unit, opcodes, types, kinds)
            for f in unit["functions"]:
                n_functions += 1
                for k, v in f["counts"].items():
                    if k.startswith("EXT:"):
                        ext[k[4:]] += v
                        ext_packages.setdefault(k[4:], set()).add(pkg)
                    else:
                        counts[k] += v
        externs[level] = ext
        seen = set(summary.entity_triples)
        out[level] = {
            **summary.to_json(),
            "n_functions": n_functions,
            "opcodes": dict(opcodes.most_common()),
            "types": dict(types.most_common()),
            "operand_kinds": dict(kinds.most_common()),
            "count_features": dict(sorted(counts.items())),
            "inventory_entities": len(lv.entities),
            "schema_entities": SCHEMA_ENTITIES[level],
            "never_seen": sorted(set(lv.entities) - seen),
        }
    combined = externs["lambda"] + externs["cmm"]
    out["externs"] = {"lambda": dict(externs["lambda"].most_common()),
                      "cmm": dict(externs["cmm"].most_common()),
                      "combined": dict(combined.most_common()),
                      # document frequency: distinct packages using the name (D4.3)
                      "packages": {n: len(ext_packages[n]) for n in sorted(ext_packages)}}
    return out
