"""Cmm encoders (schema §2.8; BUILD_SPEC Phase 5).

  I = Wo*op + Wt*type + Wa * sum_j A_j

cmm_fa: A_j is the sum of the vectors of operand j's reaching definitions, or
its operand-kind vector if it has none (a parameter, the exception variable of
a handler, a constant, a symbol). cmm_sym (control): every A_j is the
operand-kind vector.

  1. Reaching definitions: iterative dataflow over the CFG (normal and
     exceptional edges), needed only for multiply-defined variables (mutable,
     join and handler variables); any other variable has at most one def.
  2. A synthetic COPY is transparent (D2.3): its value is its operand's A, and
     it is excluded from sums (unless count_synthetic).
  3. Cycles: the shared engine (SCCs + exact linear solves).
  4. Liveness (D2.15): an instruction counts if it is a terminator, has a side
     effect, or defines a variable that is live after it.
  5. block = sum of counted instructions; function = sum of blocks.
  6. Calls, pass 2: F += Wc * F_callee(pass 1) per direct call to a function
     of this unit (Capply whose operand 0 is SYM_FUNC naming one).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import engine
from .vocab import Vocabulary, Weights


@dataclass
class FunctionVector:
    name: str
    vector: np.ndarray            # after pass 2
    pass1: np.ndarray
    n_instrs: int
    n_counted: int
    direct_calls: list[str]
    stats: engine.SolveStats


def _flat(func: dict) -> list[tuple[int, int, dict]]:
    return [(b["id"], k, i) for b in func["blocks"] for k, i in enumerate(b["instrs"])]


def _preds(func: dict) -> dict[int, list[tuple[int, bool]]]:
    """block -> [(predecessor, via an exceptional edge)]"""
    preds: dict[int, list[tuple[int, bool]]] = {b["id"]: [] for b in func["blocks"]}
    for b in func["blocks"]:
        for s in b["succ"]:
            preds[s].append((b["id"], False))
        for s in b["exn_succ"]:
            preds[s].append((b["id"], True))
    return preds


def reaching_definitions(func: dict) -> dict[int, list[list[int] | None]]:
    """instr id -> per operand: reaching definition ids (None: not a variable)."""
    multi = set(func["mutable_vars"]) | set(func["join_vars"]) | set(func["handler_params"])
    defs_of: dict[str, list[int]] = {}
    for b in func["blocks"]:
        for i in b["instrs"]:
            if i["dst"]:
                defs_of.setdefault(i["dst"], []).append(i["id"])
    blocks = {b["id"]: b for b in func["blocks"]}
    order = sorted(blocks)
    gen: dict[int, dict[str, int]] = {}
    for bid in order:
        g: dict[str, int] = {}
        for i in blocks[bid]["instrs"]:
            if i["dst"] in multi:
                g[i["dst"]] = i["id"]                       # last def in the block
        gen[bid] = g
    preds = _preds(func)
    # IN/OUT: var -> frozenset of def ids (multi vars only)
    IN = {b: {} for b in order}
    OUT = {b: {v: frozenset([d]) for v, d in gen[b].items()} for b in order}
    changed = True
    while changed:
        changed = False
        for bid in order:
            new_in: dict[str, set[int]] = {}
            for p, exceptional in preds[bid]:
                # an exception may leave p before its own definitions run
                for src in ((IN[p], OUT[p]) if exceptional else (OUT[p],)):
                    for v, ds in src.items():
                        new_in.setdefault(v, set()).update(ds)
            new_in_f = {v: frozenset(ds) for v, ds in new_in.items()}
            new_out = dict(new_in_f)
            new_out.update({v: frozenset([d]) for v, d in gen[bid].items()})
            if new_in_f != IN[bid] or new_out != OUT[bid]:
                IN[bid], OUT[bid], changed = new_in_f, new_out, True
    result: dict[int, list[list[int] | None]] = {}
    for bid in order:
        cur = {v: set(ds) for v, ds in IN[bid].items()}
        for i in blocks[bid]["instrs"]:
            per = []
            for o in i["operands"]:
                v = o.get("var")
                if v is None:
                    per.append(None)
                elif v in multi:
                    per.append(sorted(cur.get(v, ())))
                else:
                    per.append(list(defs_of.get(v, [])))   # 0 (parameter) or 1 def
            result[i["id"]] = per
            if i["dst"] in multi:
                cur[i["dst"]] = {i["id"]}
    return result


def live_instructions(func: dict) -> set[int]:
    """Instruction ids that count: terminators, side effects, live dsts."""
    blocks = {b["id"]: b for b in func["blocks"]}
    succs = {b["id"]: b["succ"] + b["exn_succ"] for b in func["blocks"]}
    live_in: dict[int, frozenset[str]] = {b: frozenset() for b in blocks}
    changed = True
    while changed:
        changed = False
        for bid in sorted(blocks, reverse=True):
            live = set().union(*(live_in[s] for s in succs[bid])) if succs[bid] else set()
            for i in reversed(blocks[bid]["instrs"]):
                live.discard(i["dst"])
                live.update(o["var"] for o in i["operands"] if "var" in o)
            f = frozenset(live)
            if f != live_in[bid]:
                live_in[bid], changed = f, True
    counted: set[int] = set()
    for bid, b in blocks.items():
        live = set().union(*(live_in[s] for s in succs[bid])) if succs[bid] else set()
        for i in reversed(b["instrs"]):
            if i["terminator"] or i["side_effect"] or (i["dst"] and i["dst"] in live):
                counted.add(i["id"])
            live.discard(i["dst"])
            live.update(o["var"] for o in i["operands"] if "var" in o)
    return counted


def _system(func: dict, vocab: Vocabulary, w: Weights, flow: bool,
            count_synthetic: bool) -> tuple[engine.System, list[dict]]:
    flat = _flat(func)
    instrs = [i for _, _, i in flat]
    pos = {i["id"]: k for k, i in enumerate(instrs)}
    rd = reaching_definitions(func) if flow else {}
    base = np.zeros((len(instrs), vocab.dim))
    deps: list[list[tuple[int, float, bool]]] = [[] for _ in instrs]
    for k, i in enumerate(instrs):
        transparent = (i.get("synthetic") and i["op"] == "COPY" and not count_synthetic)
        per = rd.get(i["id"], [None] * len(i["operands"])) if flow else [None] * len(i["operands"])
        if transparent:
            # X = A(operand): weight 1, no opcode or type of its own
            (o,), (ds,) = i["operands"], per
            if ds:
                deps[k].extend((pos[d], 1.0, False) for d in ds)
            else:
                base[k] = vocab(o["kind"])
            continue
        b = w.Wo * vocab(i["op"])
        if i["type"] is not None:
            b = b + w.Wt * vocab(i["type"])
        for o, ds in zip(i["operands"], per):
            if ds:
                deps[k].extend((pos[d], w.Wa, True) for d in ds)
            else:
                b = b + w.Wa * vocab(o["kind"])
        base[k] = b
    return engine.System(base, deps), instrs


def encode_unit(unit: dict, vocab: Vocabulary, w: Weights, flow: bool,
                count_synthetic: bool = False) -> list[FunctionVector]:
    local = {f["name"] for f in unit["functions"]}
    out: list[FunctionVector] = []
    for f in unit["functions"]:
        system, instrs = _system(f, vocab, w, flow, count_synthetic)
        X, stats = engine.solve(system, w.Wa)
        counted = live_instructions(f)
        keep = [k for k, i in enumerate(instrs) if i["id"] in counted
                and not (i.get("synthetic") and i["op"] == "COPY" and not count_synthetic)]
        pass1 = X[keep].sum(axis=0) if keep else np.zeros(vocab.dim)
        calls = [i["operands"][0]["sym"] for i in instrs
                 if i["op"] == "Capply" and i["operands"]
                 and i["operands"][0]["kind"] == "SYM_FUNC"
                 and i["operands"][0].get("sym") in local]
        out.append(FunctionVector(f["name"], pass1, pass1, len(instrs), len(keep), calls, stats))
    by_name = {fv.name: fv for fv in out}
    for fv in out:                                   # pass 2 on pass-1 vectors only
        fv.vector = fv.pass1 + w.Wc * sum((by_name[c].pass1 for c in fv.direct_calls),
                                           np.zeros(vocab.dim))
    return out


def cmm_sym(unit: dict, vocab: Vocabulary, w: Weights, count_synthetic: bool = False):
    return encode_unit(unit, vocab, w, flow=False, count_synthetic=count_synthetic)


def cmm_fa(unit: dict, vocab: Vocabulary, w: Weights, count_synthetic: bool = False):
    return encode_unit(unit, vocab, w, flow=True, count_synthetic=count_synthetic)
