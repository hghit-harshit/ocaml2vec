"""§8.3 Distinctness bar charts: the Phase 7 numbers, plotted.

Values come from `metrics.distinctness` (the same function as
`ir2vec check distinctness`), so the bars reproduce Report §6 exactly. A
second figure compares alpha = 1.0 and 0.75 (vocab/exp/, D5.1). The 0.1 flag
line is drawn on both.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import inventory, metrics
from . import common as C

FLAG = metrics.DISTINCTNESS_FLAG


def scores(path: Path) -> tuple[dict, dict]:
    meta, names, vecs = metrics.load_vocab(path)
    d = metrics.distinctness(meta["level"], inventory.load(), names, vecs)
    return meta, {g: v["score"] for g, v in d.items() if not g.startswith("_")}


def _grouped(ax, groups, series: list[tuple[str, dict]]):
    x = np.arange(len(groups))
    width = 0.8 / len(series)
    for k, (label, sc) in enumerate(series):
        vals = [sc[g] for g in groups]
        bars = ax.bar(x + (k - (len(series) - 1) / 2) * width, vals, width * 0.92,
                      color=C.SERIES[k], label=label, zorder=2)
        for b, v in zip(bars, vals):
            ax.annotate(f"{v:.2f}", (b.get_x() + b.get_width() / 2, v), ha="center",
                        va="bottom", fontsize=6, color=C.INK, xytext=(0, 1),
                        textcoords="offset points")
    ax.axhline(FLAG, color=C.INK, linestyle="--", linewidth=1)
    ax.annotate(f"collapse flag ({FLAG})", (x[-1] + 0.45, FLAG), fontsize=6, ha="right",
                va="bottom", color=C.INK)
    ax.set_xticks(x, groups, rotation=20, ha="right")
    ax.set_ylabel("distinctness (within-group ÷ all-pairs cosine distance)")
    ax.set_ylim(0, 1.22)
    ax.legend(loc="upper left", fontsize=7, ncol=len(series))


def draw_models(out_dir: Path = C.OUT_DIR) -> Path:
    plt = C.setup()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    rows, caps = [], []
    for ax, level in zip(axes, ("lambda", "cmm")):
        series = []
        for model in ("complex", "transe"):
            path = C.vocab_path(level, model)
            meta, sc = scores(path)
            series.append((f"{model} (α = {meta.get('sampling_alpha')})", sc))
            caps.append(f"{level}.{model} sha256 {C._sha(path)[:12]}")
            rows += [[level, model, meta.get("sampling_alpha"), g, v] for g, v in sc.items()]
        groups = list(series[0][1])
        _grouped(ax, groups, series)
        ax.set_title(f"{level.capitalize()}: ComplEx vs TransE", fontsize=9)
    fig.suptitle("Sibling-group distinctness (schema §4), full-dimensional; "
                 "no group below the 0.1 flag", fontsize=10)
    fig.text(0.01, 0.005, " · ".join(caps), fontsize=6, color=C.INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    base = out_dir / "distinctness_models"
    C.save(fig, base)
    C.write_tsv(base.with_suffix(".tsv"), ["level", "model", "alpha", "group", "score"], rows,
                ["values from metrics.distinctness (= ir2vec check distinctness, Report §6)"])
    return base


def draw_alpha(out_dir: Path = C.OUT_DIR) -> Path:
    plt = C.setup()
    exp = inventory.REPO / "vocab" / "exp"
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.4))
    rows, caps = [], []
    for r, model in enumerate(("complex", "transe")):
        for c, level in enumerate(("lambda", "cmm")):
            series = []
            for a in ("1.0", "0.75"):
                path = exp / f"a{a}" / f"{level}.{model}.json"
                _meta, sc = scores(path)
                series.append((f"α = {a}", sc))
                caps.append(f"a{a}/{level}.{model} {C._sha(path)[:10]}")
                rows += [[level, model, a, g, v] for g, v in sc.items()]
            _grouped(axes[r, c], list(series[0][1]), series)
            axes[r, c].set_title(f"{level.capitalize()} · {model}: α = 1.0 vs 0.75", fontsize=9)
    fig.suptitle("Frequency smoothing (D5.1): distinctness at α = 1.0 and α = 0.75", fontsize=10)
    fig.text(0.01, 0.005, " · ".join(caps), fontsize=5.5, color=C.INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    base = out_dir / "distinctness_alpha"
    C.save(fig, base)
    C.write_tsv(base.with_suffix(".tsv"), ["level", "model", "alpha", "group", "score"], rows,
                ["values from metrics.distinctness on vocab/exp/a{1.0,0.75} (D5.1 comparison)"])
    return base
