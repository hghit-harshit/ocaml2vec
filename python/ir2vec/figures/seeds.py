"""§8.1 Seed scatter plots: the counterpart of IR2Vec's Figure 6.

Each comparison panel fits a 2-component PCA on the points it plots; the title
gives both components' explained variance. Named groups use categorical slots
1-3 (legend: full-dimensional distinctness d, member count); everything else in
the panel is a grey context layer. Low-confidence entities are hollow. An
"all entities" facet grid (one facet per category, over the grey context) and a
rarity control panel (colour = log10 training triples, ignoring category)
complete each level.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import common as C

CHUNK_MARKERS = {"byte": "o", "16": "s", "32": "^", "64": "D", "word": "P", "single": "h",
                 "double": "X", "narrow": "*"}


def _cat(lv, *names):
    return [n for n in lv.names if lv.category[n] in names]


def panels(lv) -> list[tuple[str, list[tuple[str, list[str]]], list[str]]]:
    """(title, [(group label, members)], context members)"""
    ops_all = [n for n in lv.names if lv.category[n] not in ("types", "operand kinds")]
    everything = list(lv.names)

    def rest(*groups):
        taken = {m for g in groups for m in g}
        return [n for n in everything if n not in taken]

    if lv.level == "lambda":
        i, f = _cat(lv, "int arithmetic"), _cat(lv, "float arithmetic")
        conv, b = _cat(lv, "conversions"), _cat(lv, "boxed-int")
        ctl, ok = _cat(lv, "control forms"), _cat(lv, "operand kinds")
        eff = _cat(lv, "effects")
        prims = [n for n in ops_all if n not in ctl]
        return [
            ("types", [("types", _cat(lv, "types"))], []),
            ("int vs float arithmetic", [("int arithmetic", i), ("float arithmetic", f)], []),
            ("conversions vs int vs float arithmetic",
             [("int arithmetic", i), ("float arithmetic", f), ("conversions", conv)], []),
            ("arithmetic vs operand kinds", [("int + float arithmetic", i + f), ("operand kinds", ok)], []),
            ("int vs boxed-int arithmetic", [("int arithmetic", i), ("boxed-int", b)], []),
            ("control forms vs primitives", [("control forms", ctl), ("primitives", prims)], []),
            ("effects vs the rest", [("effects", eff)], rest(eff)),
        ]
    i, f = _cat(lv, "int arithmetic"), _cat(lv, "float arithmetic")
    conv, calls = _cat(lv, "conversions"), _cat(lv, "calls and allocation")
    struct = _cat(lv, "structural")
    return [
        ("types", [("types", _cat(lv, "types"))], []),
        ("int vs float arithmetic", [("int arithmetic", i), ("float arithmetic", f)], []),
        ("conversions vs int vs float arithmetic",
         [("int arithmetic", i), ("float arithmetic", f), ("conversions", conv)], []),
        ("loads vs stores", [("loads", _cat(lv, "loads")), ("stores", _cat(lv, "stores"))], []),
        ("calls and allocation vs arithmetic", [("calls and allocation", calls),
                                                ("int + float arithmetic", i + f)], []),
        ("structural opcodes vs operations",
         [("structural", struct), ("operations", [n for n in ops_all if n not in struct])], []),
    ]


def _chunk(name: str) -> str:
    suffix = name.split("_", 1)[1] if "_" in name else ""
    for key in ("byte", "word", "single", "double", "narrow", "16", "32", "64"):
        if suffix.startswith(key):
            return key
    return "?"


def _slug(title: str) -> str:
    return title.replace(" + ", "_").replace(" vs ", "_vs_").replace(" ", "_").replace("-", "_")


def draw_panel(lv, title, groups, context, out_dir: Path) -> Path:
    plt = C.setup()
    members = [m for _, g in groups for m in g] + list(context)
    X = lv.vecs[[lv.idx(m) for m in members]]
    Y, ratio = C.pca2(X)
    pos = {m: Y[k] for k, m in enumerate(members)}
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    rows = []
    for m in context:
        x, y = pos[m]
        ax.scatter([x], [y], s=28, facecolors="none" if m in lv.low else C.CONTEXT,
                   edgecolors=C.CONTEXT, linewidths=1.0, zorder=1)
        ax.annotate(m, (x, y), fontsize=5.5, color=C.INK2, xytext=(3, 2),
                    textcoords="offset points", zorder=1)
        rows.append([m, lv.category[m], "context", x, y, m in lv.low, lv.triples[m]])
    chunked = lv.level == "cmm" and title == "loads vs stores"
    for k, (label, g) in enumerate(groups):
        colour = C.SERIES[k]
        d = C.group_distinctness(lv, g)
        dlabel = f"d = {d:.2f}" if np.isfinite(d) else "d = n/a"
        ax.scatter([], [], s=40, color=colour, label=f"{label} ({dlabel}, n = {len(g)})")
        for m in g:
            x, y = pos[m]
            marker = CHUNK_MARKERS.get(_chunk(m), "o") if chunked else "o"
            hollow = m in lv.low
            ax.scatter([x], [y], s=48, marker=marker, facecolors="none" if hollow else colour,
                       edgecolors=colour, linewidths=1.4, zorder=3)
            ax.annotate(m, (x, y), fontsize=6.5, color=C.INK, xytext=(4, 3),
                        textcoords="offset points", zorder=4)
            rows.append([m, lv.category[m], label, x, y, hollow, lv.triples[m]])
    if chunked:
        present = {_chunk(m) for _, g in groups for m in g}
        for key, mk in CHUNK_MARKERS.items():
            if key not in present:
                continue
            ax.scatter([], [], marker=mk, s=36, color=C.INK2, label=f"chunk: {key}")
    ax.scatter([], [], s=40, facecolors="none", edgecolors=C.INK2, label="hollow: low-confidence")
    ax.set_title(f"{lv.level.capitalize()} seeds — {title}\nPCA on the {len(members)} plotted "
                 f"points: PC1 {ratio[0]:.1%}, PC2 {ratio[1]:.1%} of variance "
                 f"({ratio.sum():.1%} shown)", fontsize=9)
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.margins(0.12)
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
    fig.text(0.01, 0.005, C.caption_text(lv, "d = full-dimensional cosine distinctness (Phase 7); "
                                             "the projection only illustrates it"),
             fontsize=6, color=C.INK2)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    base = out_dir / f"seeds_{lv.level}_{lv.model}_{_slug(title)}"
    C.save(fig, base)
    C.write_tsv(base.with_suffix(".tsv"),
                ["entity", "category", "group", "pc1", "pc2", "low_confidence", "triples"],
                rows + [[e, "", s, "", "", "", ""] for e, s in lv.excluded],
                [lv.caption(), f"PCA explained variance: PC1 {ratio[0]:.6f}, PC2 {ratio[1]:.6f}"])
    return base


def draw_facets(lv, out_dir: Path) -> Path:
    """All entities: one facet per category, highlighted over the grey rest.
    One PCA over all plotted entities, shared by every facet."""
    from ..categories import load as load_cats
    plt = C.setup()
    order = [c for c in load_cats().order[lv.level] if any(lv.category[n] == c for n in lv.names)]
    Y, ratio = C.pca2(lv.vecs)
    ncol = 4
    nrow = -(-len(order) // ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(4.0 * ncol, 3.6 * nrow), sharex=True, sharey=True)
    axes = np.atleast_1d(axes).ravel()
    for ax, cat in zip(axes, order):
        ax.scatter(Y[:, 0], Y[:, 1], s=10, color=C.CONTEXT, zorder=1)
        members = [k for k, n in enumerate(lv.names) if lv.category[n] == cat]
        d = C.group_distinctness(lv, [lv.names[k] for k in members])
        for k in members:
            hollow = lv.names[k] in lv.low
            ax.scatter([Y[k, 0]], [Y[k, 1]], s=30, facecolors="none" if hollow else C.SERIES[0],
                       edgecolors=C.SERIES[0], linewidths=1.2, zorder=3)
            ax.annotate(lv.names[k], (Y[k, 0], Y[k, 1]), fontsize=5, xytext=(2, 2),
                        textcoords="offset points", zorder=4)
        ax.set_title(f"{cat} (n = {len(members)}, d = {d:.2f})" if np.isfinite(d)
                     else f"{cat} (n = {len(members)})", fontsize=8)
    for ax in axes[len(order):]:
        ax.set_visible(False)
    fig.suptitle(f"{lv.level.capitalize()} seeds — all {len(lv.names)} entities, one facet per "
                 f"category (shared PCA: PC1 {ratio[0]:.1%}, PC2 {ratio[1]:.1%}; "
                 f"{ratio.sum():.1%} of variance shown; hollow = low-confidence)", fontsize=10)
    fig.text(0.01, 0.005, lv.caption(), fontsize=7, color=C.INK2)
    fig.tight_layout(rect=(0, 0.025, 1, 0.97))
    base = out_dir / f"seeds_{lv.level}_{lv.model}_all_entities"
    C.save(fig, base)
    C.write_tsv(base.with_suffix(".tsv"),
                ["entity", "category", "pc1", "pc2", "low_confidence", "triples"],
                [[n, lv.category[n], Y[k, 0], Y[k, 1], n in lv.low, lv.triples[n]]
                 for k, n in enumerate(lv.names)]
                + [[e, s, "", "", "", ""] for e, s in lv.excluded],
                [lv.caption(), f"PCA explained variance: PC1 {ratio[0]:.6f}, PC2 {ratio[1]:.6f}"])
    return base


def draw_rarity(lv, out_dir: Path) -> Path:
    """Rarity control: every plotted entity coloured by log10(training triples),
    ignoring category, so a category cluster can be checked against rarity."""
    import matplotlib.colors as mcolors
    plt = C.setup()
    Y, ratio = C.pca2(lv.vecs)
    counts = np.array([max(lv.triples[n], 1) for n in lv.names], dtype=float)
    logc = np.log10(counts)
    cmap = mcolors.LinearSegmentedColormap.from_list("ir2vec_blue", C.BLUE_RAMP)
    fig, ax = plt.subplots(figsize=(7.4, 6.2))
    sc = ax.scatter(Y[:, 0], Y[:, 1], c=logc, cmap=cmap, s=36, edgecolors=C.INK2,
                    linewidths=0.4, zorder=2)
    for k, n in enumerate(lv.names):
        if n in lv.low:
            ax.scatter([Y[k, 0]], [Y[k, 1]], s=90, facecolors="none", edgecolors=C.SERIES[1],
                       linewidths=1.0, zorder=3)
        ax.annotate(n, (Y[k, 0], Y[k, 1]), fontsize=5.2, xytext=(3, 2),
                    textcoords="offset points", color=C.INK, zorder=4)
    ax.scatter([], [], s=90, facecolors="none", edgecolors=C.SERIES[1],
               label=f"low-confidence (< 1,000 triples): {len(lv.low & set(lv.names))}")
    cb = fig.colorbar(sc, ax=ax, fraction=0.04)
    cb.set_label("log10(training triples of the vector)")
    ax.legend(loc="upper left", fontsize=7)
    ax.set_title(f"{lv.level.capitalize()} seeds — rarity control (colour = training "
                 f"frequency, not category)\nPCA on all {len(lv.names)} entities: PC1 "
                 f"{ratio[0]:.1%}, PC2 {ratio[1]:.1%} ({ratio.sum():.1%} of variance shown)",
                 fontsize=9)
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    fig.text(0.01, 0.005, lv.caption(), fontsize=6, color=C.INK2)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    base = out_dir / f"seeds_{lv.level}_{lv.model}_rarity"
    C.save(fig, base)
    C.write_tsv(base.with_suffix(".tsv"),
                ["entity", "category", "pc1", "pc2", "triples", "log10_triples", "low_confidence"],
                [[n, lv.category[n], Y[k, 0], Y[k, 1], lv.triples[n], logc[k], n in lv.low]
                 for k, n in enumerate(lv.names)]
                + [[e, s, "", "", "", "", ""] for e, s in lv.excluded],
                [lv.caption(), f"PCA explained variance: PC1 {ratio[0]:.6f}, PC2 {ratio[1]:.6f}"])
    return base


def draw_all(lv, out_dir: Path = C.OUT_DIR) -> list[Path]:
    out = [draw_panel(lv, t, g, ctx, out_dir) for t, g, ctx in panels(lv)]
    out += [draw_facets(lv, out_dir), draw_rarity(lv, out_dir)]
    return out
