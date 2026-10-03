"""Lambda encoders (schema §1.8; BUILD_SPEC Phase 5).

  node      = Wo*op + Wt*type + Wa * sum over *value* positions of the operand
  operand   = a leaf's operand-kind vector, or a child's computed kind
              ("kind": VAR_<child Type>, D1.11)
  function  = sum of the nodes the record owns (a nested function's root is
              owned by its parent's stub, D1.3)
  module    = sum of all records (module_init included)

lambda_fa differs only for leaves with def references (a let-bound Lvar, or a
Lmutvar and its Lmutlet/Lassign definitions): such an operand is the sum of
its defining nodes' vectors, solved through the shared engine.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..triples import owned_nodes
from . import engine
from .vocab import Vocabulary, Weights


@dataclass
class FunctionVector:
    fid: str
    name: str
    kind: str
    vector: np.ndarray
    n_nodes: int
    stats: engine.SolveStats


def _system(func: dict, vocab: Vocabulary, w: Weights, flow: bool) -> tuple[engine.System, list[int]]:
    nodes = list(owned_nodes(func))
    item = {n["id"]: k for k, n in enumerate(nodes)}
    base = np.zeros((len(nodes), vocab.dim))
    deps: list[list[tuple[int, float, bool]]] = [[] for _ in nodes]
    for k, n in enumerate(nodes):
        b = w.Wo * vocab(n["op"])
        if n["type"] is not None:
            b = b + w.Wt * vocab(n["type"])
        for p in n["positions"]:
            if p["role"] != "value":
                continue
            defs = [item[d] for d in (p.get("def") or ()) if d in item] if flow else []
            if defs:
                deps[k].extend((j, w.Wa, True) for j in defs)
            else:
                b = b + w.Wa * vocab(p["leaf"] if "leaf" in p else p["kind"])
        base[k] = b
    return engine.System(base, deps), [n["id"] for n in nodes]


def encode_unit(unit: dict, vocab: Vocabulary, w: Weights, flow: bool) -> list[FunctionVector]:
    out = []
    for f in unit["functions"]:
        system, _ids = _system(f, vocab, w, flow)
        X, stats = engine.solve(system, w.Wa)
        out.append(FunctionVector(f["fid"], f["name"], f["kind"],
                                  X.sum(axis=0) if len(X) else np.zeros(vocab.dim),
                                  system.n, stats))
    return out


def lambda_sym(unit: dict, vocab: Vocabulary, w: Weights) -> list[FunctionVector]:
    return encode_unit(unit, vocab, w, flow=False)


def lambda_fa(unit: dict, vocab: Vocabulary, w: Weights) -> list[FunctionVector]:
    return encode_unit(unit, vocab, w, flow=True)
