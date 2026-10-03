"""(head, relation, tail) triples, schema §1.5 / §2.5 (BUILD_SPEC Phase 3.4).

Duplicates are kept: frequency is signal. Two filters shape what counts as a
node / instruction, and every consumer (triples, stats, encoders) uses them:
  - Lambda ownership (D1.3): a node whose "owner" is another record (the root
    copy of a nested function's Lfunction node) is skipped; its owner's stub
    carries the node, including the cross-record Child0 edge.
  - Cmm synthetic COPYs (D2.3): skipped unless count_synthetic; Next and Succ
    bridge over them. Synthetic JUMPs are real control transfers and count.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

Triple = tuple[str, str, str]

CMM_BRANCHES = frozenset({"BR", "SWITCH", "JUMP"})


def positional(prefix: str, i: int) -> str:
    return f"{prefix}{i}" if i < 4 else f"{prefix}4+"


# ---------------------------------------------------------------- views ---

def owned_nodes(func: dict) -> Iterator[dict]:
    for n in func["nodes"]:
        if n.get("owner") in (None, func["fid"]):
            yield n


def is_skipped(instr: dict, count_synthetic: bool) -> bool:
    return (not count_synthetic) and instr.get("synthetic", False) and instr["op"] == "COPY"


def kept_instrs(block: dict, count_synthetic: bool) -> list[dict]:
    return [i for i in block["instrs"] if not is_skipped(i, count_synthetic)]


# -------------------------------------------------------------- triples ---

def lambda_triples(unit: dict, merge: dict[str, str]) -> Iterator[Triple]:
    m = lambda op: merge.get(op, op)  # noqa: E731
    records = {f["fid"]: {n["id"]: n for n in f["nodes"]} for f in unit["functions"]}
    for f in unit["functions"]:
        here = records[f["fid"]]
        for n in owned_nodes(f):
            head = m(n["op"])
            if n["type"] is not None:
                yield head, "Type", n["type"]
            for p in n["positions"]:
                if "child" in p:
                    target = records[p["func"]] if "func" in p else here
                    yield head, positional("Child", p["i"]), m(target[p["child"]]["op"])
                else:
                    yield head, positional("Arg", p["i"]), p["leaf"]
            for arm in f["cases"].get(str(n["id"]), ()):
                yield head, "Case", m(here[arm["child"]]["op"]) if "child" in arm else arm["leaf"]


def cmm_triples(unit: dict, merge: dict[str, str], count_synthetic: bool) -> Iterator[Triple]:
    m = lambda op: merge.get(op, op)  # noqa: E731
    for f in unit["functions"]:
        kept = {b["id"]: kept_instrs(b, count_synthetic) for b in f["blocks"]}
        first = {bid: m(ins[0]["op"]) for bid, ins in kept.items()}
        for b in f["blocks"]:
            ins = kept[b["id"]]
            for k, i in enumerate(ins):
                head = m(i["op"])
                if i["type"] is not None:
                    yield head, "Type", i["type"]
                for j, o in enumerate(i["operands"]):
                    yield head, positional("Arg", j), o["kind"]
                if k + 1 < len(ins):
                    yield head, "Next", m(ins[k + 1]["op"])
                if i["op"] in CMM_BRANCHES:
                    for s in b["succ"]:
                        yield head, "Succ", first[s]
                elif i["op"] == "Craise":
                    for s in b["exn_succ"]:
                        yield head, "Succ", first[s]


def unit_triples(level: str, unit: dict, merge: dict[str, str],
                 count_synthetic: bool) -> Iterator[Triple]:
    if level == "lambda":
        return lambda_triples(unit, merge)
    return cmm_triples(unit, merge, count_synthetic)


# ------------------------------------------------------------- summary ---

@dataclass
class TripleSummary:
    level: str
    n_triples: int = 0
    n_units: int = 0
    relations: Counter = field(default_factory=Counter)
    entity_triples: Counter = field(default_factory=Counter)   # head or tail
    unknown: Counter = field(default_factory=Counter)

    def add(self, t: Triple, vocab: set[str], relations: set[str]) -> None:
        h, r, tl = t
        self.n_triples += 1
        self.relations[r] += 1
        self.entity_triples[h] += 1
        self.entity_triples[tl] += 1
        for e in (h, tl):
            if e not in vocab:
                self.unknown[e] += 1
        if r not in relations:
            self.unknown[f"relation:{r}"] += 1

    def to_json(self) -> dict:
        return {"level": self.level, "n_triples": self.n_triples, "n_units": self.n_units,
                "relations": dict(sorted(self.relations.items())),
                "entity_triples": dict(sorted(self.entity_triples.items())),
                "distinct_entities": len(self.entity_triples),
                "unknown": dict(sorted(self.unknown.items()))}


def vocabulary(entities: Iterable[str], merge: dict[str, str]) -> set[str]:
    """Training entities after merges: members replaced by their family."""
    return {merge.get(e, e) for e in entities}


def write_tsv(path: Path, triples: Iterable[Triple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="\n") as fh:
        for h, r, t in triples:
            fh.write(f"{h}\t{r}\t{t}\n")


def read_tsv(path: Path) -> list[Triple]:
    with path.open() as fh:
        return [tuple(line.rstrip("\n").split("\t")) for line in fh]  # type: ignore[misc]
