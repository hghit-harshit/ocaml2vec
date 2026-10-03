"""§8.4 Nearest-neighbour table: top-3 per entity by full-dimensional cosine.

Rendered as a sectioned table image (one section per category) plus a .tsv.
Only entities with their own vector take part, as queries or as neighbours.
The headline number is the top-1 same-category rate against its chance level
(the rate expected if neighbours were drawn uniformly from the other entities).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..categories import load as load_cats
from . import common as C

K = 3


def top_k(lv, k: int = K) -> dict[str, list[tuple[str, float]]]:
    S = C.cosine_matrix(lv.vecs)
    out = {}
    for i, n in enumerate(lv.names):
        # descending cosine, ties by name: deterministic
        cand = sorted((j for j in range(len(lv.names)) if j != i),
                      key=lambda j: (-round(float(S[i, j]), 12), lv.names[j]))
        out[n] = [(lv.names[j], float(S[i, j])) for j in cand[:k]]
    return out


def same_category_rate(lv, nn) -> tuple[float, float]:
    """(observed top-1 same-category rate, chance rate)."""
    names = lv.names
    size = {}
    for n in names:
        size[lv.category[n]] = size.get(lv.category[n], 0) + 1
    obs = np.mean([lv.category[nn[n][0][0]] == lv.category[n] for n in names])
    chance = np.mean([(size[lv.category[n]] - 1) / (len(names) - 1) for n in names])
    return float(obs), float(chance)


def per_category(lv, nn) -> dict[str, tuple[int, int]]:
    out: dict[str, list[int]] = {}
    for n in lv.names:
        hit = lv.category[nn[n][0][0]] == lv.category[n]
        out.setdefault(lv.category[n], [0, 0])
        out[lv.category[n]][0] += int(hit)
        out[lv.category[n]][1] += 1
    return {c: (h, t) for c, (h, t) in out.items()}


def _sections(lv) -> list[tuple[str, list[str]]]:
    order = load_cats().order[lv.level]
    return [(c, sorted(n for n in lv.names if lv.category[n] == c))
            for c in order if any(lv.category[n] == c for n in lv.names)]


def _columns(sections, ncols: int):
    """Split whole sections into columns of roughly equal line count."""
    total = sum(len(m) + 2 for _, m in sections)
    cols, cur, acc = [], [], 0
    for s in sections:
        cur.append(s)
        acc += len(s[1]) + 2
        if acc >= total / ncols * (len(cols) + 1) and len(cols) < ncols - 1:
            cols.append(cur)
            cur = []
    cols.append(cur)
    return cols


def draw(lv, out_dir: Path = C.OUT_DIR) -> Path:
    plt = C.setup()
    nn = top_k(lv)
    obs, chance = same_category_rate(lv, nn)
    pc = per_category(lv, nn)
    sections = _sections(lv)
    ncols = 3
    cols = _columns(sections, ncols)
    lines = max(sum(len(m) + 2 for _, m in col) for col in cols)
    lh = 0.125                                                # inches per line
    fig = plt.figure(figsize=(19, lines * lh + 1.3))
    H = lines * lh + 1.3
    fig.text(0.01, 1 - 0.18 / H, f"{lv.level.capitalize()} seeds — top-{K} nearest neighbours by "
             f"cosine, {lv.model} (full {lv.vecs.shape[1]}-D)", fontsize=10, va="top")
    fig.text(0.01, 1 - 0.42 / H,
             f"top-1 neighbour in the same category: {obs:.1%} of {len(lv.names)} entities "
             f"(chance {chance:.1%}).  ° = low-confidence.  bold = neighbour in the query's "
             f"category; grey = other category.", fontsize=8, va="top", color=C.INK2)
    y0 = 1 - 0.75 / H
    for c, col in enumerate(cols):
        x = 0.01 + c * (0.99 / ncols)
        y = y0
        for cat, members in col:
            h, t = pc[cat]
            fig.text(x, y, f"{cat}  (top-1 same category {h}/{t})", fontsize=7.5,
                     weight="bold", va="top")
            y -= lh / H
            for n in members:
                q = f"{n}°" if n in lv.low else n
                fig.text(x + 0.005, y, q, fontsize=6.3, va="top", family="DejaVu Sans Mono")
                xx = x + 0.095
                for m, s in nn[n]:
                    same = lv.category[m] == cat
                    lab = f"{m}{'°' if m in lv.low else ''} {s:.2f}"
                    fig.text(xx, y, lab, fontsize=6.3, va="top", family="DejaVu Sans Mono",
                             color=C.INK if same else C.INK2,
                             weight="bold" if same else "normal")
                    xx += 0.078
                y -= lh / H
            y -= lh / H
    fig.text(0.01, 0.12 / H, lv.caption(), fontsize=6, color=C.INK2)
    base = out_dir / f"neighbours_{lv.level}_{lv.model}"
    C.save(fig, base)
    rows = []
    for cat, members in sections:
        for n in members:
            r = [cat, n, "low" if n in lv.low else "", lv.triples[n]]
            for m, s in nn[n]:
                r += [m, lv.category[m], s]
            rows.append(r)
    hdr = ["category", "entity", "confidence", "triples"]
    for k in range(1, K + 1):
        hdr += [f"nn{k}", f"nn{k}_category", f"nn{k}_cosine"]
    C.write_tsv(base.with_suffix(".tsv"), hdr, rows,
                [lv.caption(), f"top-1 same-category rate {obs:.6f}; chance {chance:.6f}",
                 "excluded (no own vector): " + "; ".join(f"{e} ({s})" for e, s in lv.excluded)])
    return base
