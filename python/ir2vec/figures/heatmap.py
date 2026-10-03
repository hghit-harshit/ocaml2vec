"""§8.2 Cosine-similarity heatmap: full-dimensional, no projection loss.

Rows and columns are ordered by category (display order), then by name, with
category boundaries drawn. Category structure should appear as blocks along
the diagonal; `block_contrast` (mean within-category minus mean
between-category cosine) quantifies it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..categories import load as load_cats
from . import common as C


def ordered(lv) -> list[str]:
    order = load_cats().order[lv.level]
    return sorted(lv.names, key=lambda n: (order.index(lv.category[n]), n))


def block_contrast(lv, names: list[str], S: np.ndarray) -> tuple[float, float]:
    cat = np.array([lv.category[n] for n in names])
    same = cat[:, None] == cat[None, :]
    off = ~np.eye(len(names), dtype=bool)
    return float(S[same & off].mean()), float(S[~same].mean())


def draw(lv, out_dir: Path = C.OUT_DIR) -> Path:
    import matplotlib.colors as mcolors
    plt = C.setup()
    names = ordered(lv)
    S = C.cosine_matrix(lv.vecs[[lv.idx(n) for n in names]])
    within, between = block_contrast(lv, names, S)
    cmap = mcolors.LinearSegmentedColormap.from_list("ir2vec_div", C.DIVERGING)
    n = len(names)
    size = 4.0 + 0.085 * n
    fig, ax = plt.subplots(figsize=(size + 1.6, size))
    im = ax.imshow(S, cmap=cmap, vmin=-1, vmax=1, interpolation="nearest")
    ax.grid(False)
    ticks = [f"{m}°" if m in lv.low else m for m in names]
    ax.set_xticks(range(n), ticks, rotation=90, fontsize=4.5)
    ax.set_yticks(range(n), ticks, fontsize=4.5)
    cats = [lv.category[m] for m in names]
    edges = [k for k in range(1, n) if cats[k] != cats[k - 1]]
    for k in edges:
        ax.axhline(k - 0.5, color=C.INK, linewidth=0.8)
        ax.axvline(k - 0.5, color=C.INK, linewidth=0.8)
    starts = [0] + edges
    ends = edges + [n]
    for s0, e0 in zip(starts, ends):
        ax.text(n + 0.5, (s0 + e0 - 1) / 2, cats[s0], fontsize=6, va="center", color=C.INK)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.16)
    cb.set_label("cosine similarity")
    ax.set_title(f"{lv.level.capitalize()} seeds — cosine similarity, {lv.model} "
                 f"(full {lv.vecs.shape[1]}-D, no projection)\nmean within-category "
                 f"{within:.3f} vs between-category {between:.3f}; ° = low-confidence",
                 fontsize=9)
    fig.text(0.01, 0.005, lv.caption(), fontsize=6, color=C.INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    base = out_dir / f"heatmap_{lv.level}_{lv.model}"
    C.save(fig, base)
    rows = [[names[i], lv.category[names[i]], *S[i]] for i in range(n)]
    C.write_tsv(base.with_suffix(".tsv"), ["entity", "category", *names], rows,
                [lv.caption(), f"row/column order = category display order, then name",
                 f"within-category mean cosine {within:.6f}; between {between:.6f}",
                 "excluded (no own vector): " + "; ".join(f"{e} ({s})" for e, s in lv.excluded)])
    return base
