"""The shared encoding engine (BUILD_SPEC Phase 5, schema §2.8).

Every encoder reduces a function to a linear system over its instructions:

    X_i = B_i + sum_j C_ij X_j

B_i is the instruction's own part (Wo*op + Wt*type + Wa * the operand-kind
vectors of operands without definitions); C_ij counts, weighted, the operand
slots of i that definition j reaches (Wa per slot; 1 for a transparent
synthetic COPY, D2.3). The dependency graph i -> j is split into strongly
connected components (Tarjan), processed dependencies-first: a singleton is
computed directly; a cyclic component S is solved exactly, all dimensions at
once, as (I - C_SS) X_S = B_S + C_S,out X_out. Values are never rounded. If
cond(I - C_SS) > 1e12 the Wa-weighted entries are recomputed with Wa - delta
(delta += 0.01) and the retry is logged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger("ir2vec.encode")

COND_LIMIT = 1e12
DELTA_STEP = 0.01


@dataclass
class System:
    base: np.ndarray                                   # (n, d)
    deps: list[list[tuple[int, float, bool]]]          # i -> [(j, coef, is_wa)]

    @property
    def n(self) -> int:
        return len(self.deps)


@dataclass
class SolveStats:
    cyclic_sccs: int = 0
    cyclic_sizes: list[int] = field(default_factory=list)
    max_residual: float = 0.0
    retries: list[dict] = field(default_factory=list)


def sccs(deps: list[list[tuple[int, float, bool]]]) -> list[list[int]]:
    """Tarjan, iterative and index-ordered (deterministic). Components are
    returned dependencies-first: every component a node depends on precedes it."""
    n = len(deps)
    index, low, on_stack = [-1] * n, [0] * n, [False] * n
    stack, out, counter = [], [], 0
    for root in range(n):
        if index[root] != -1:
            continue
        work = [(root, 0)]
        while work:
            v, k = work.pop()
            if k == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on_stack[v] = True
            succ = deps[v]
            while k < len(succ):
                w = succ[k][0]
                k += 1
                if index[w] == -1:
                    work.append((v, k))
                    work.append((w, 0))
                    break
                if on_stack[w]:
                    low[v] = min(low[v], index[w])
            else:
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on_stack[w] = False
                        comp.append(w)
                        if w == v:
                            break
                    out.append(sorted(comp))
                if work:
                    u = work[-1][0]
                    low[u] = min(low[u], low[v])
    return out


def solve(system: System, wa: float) -> tuple[np.ndarray, SolveStats]:
    n, d = system.base.shape
    X = np.zeros((n, d))
    stats = SolveStats()
    for comp in sccs(system.deps):
        members = set(comp)
        cyclic = len(comp) > 1 or any(j == comp[0] for j, _, _ in system.deps[comp[0]])
        if not cyclic:
            i = comp[0]
            X[i] = system.base[i] + sum((c * X[j] for j, c, _ in system.deps[i]), np.zeros(d))
            continue
        pos = {v: a for a, v in enumerate(comp)}
        delta = 0.0
        while True:
            scale = (wa - delta) / wa if wa else 1.0
            A = np.eye(len(comp))
            rhs = system.base[comp].copy()
            for a, i in enumerate(comp):
                for j, c, is_wa in system.deps[i]:
                    c = c * scale if is_wa else c
                    if j in members:
                        A[a, pos[j]] -= c
                    else:
                        rhs[a] += c * X[j]
            cond = np.linalg.cond(A)
            if cond <= COND_LIMIT:
                break
            delta += DELTA_STEP
            stats.retries.append({"size": len(comp), "cond": float(cond), "wa": wa - delta})
            log.warning("ill-conditioned SCC of size %d (cond %.3g): retry with Wa = %.3f",
                        len(comp), cond, wa - delta)
            if delta >= wa:
                raise ArithmeticError(f"SCC of size {len(comp)} stays singular for every Wa")
        X[comp] = np.linalg.solve(A, rhs)
        stats.cyclic_sccs += 1
        stats.cyclic_sizes.append(len(comp))
        stats.max_residual = max(stats.max_residual,
                                 float(np.abs(X[comp] - (rhs + (np.eye(len(comp)) - A) @ X[comp])).max()))
    return X, stats


def residual(system: System, X: np.ndarray) -> float:
    """max |X - (B + C X)| over the whole system (with the nominal weights)."""
    worst = 0.0
    for i, deps in enumerate(system.deps):
        v = system.base[i] + sum((c * X[j] for j, c, _ in deps), np.zeros(X.shape[1]))
        worst = max(worst, float(np.abs(X[i] - v).max()))
    return worst
