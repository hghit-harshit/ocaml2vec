"""Shared plumbing for the Phase 8 figures (BUILD_SPEC §8, D8.x).

Honesty rules implemented here, used by every figure:
  - PCA with a fixed sign convention (largest-|loading| positive per component)
    and the explained variance of the shown components;
  - only entities with their own vector are plotted; fallback-mapped,
    impossible, merged-member and unused entities are listed in each .tsv with
    their status, and counted in the caption;
  - low-confidence entities (< threshold triples) use hollow markers;
  - every figure writes PNG + SVG (byte-deterministic) and a .tsv of its numbers;
  - captions carry model, alpha and the vocabulary hash.
Colours follow the dataviz reference palette: categorical slots 1-3 only
(validated all-pairs for scatter), a one-hue blue ramp for magnitude, and a
blue <-> red diverging map with a grey midpoint.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import categories as catmod
from ..config import VocabConfig
from ..inventory import REPO

OUT_DIR = REPO / "report" / "figures"
NL = chr(10)
ENTITIES_TSV = REPO / "report" / "entities.tsv"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
CONTEXT = "#c9c8c2"                                   # recessive: the "rest" layer
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]            # blue, orange, aqua (all-pairs valid)
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGING = ["#184f95", "#6da7ec", "#f0efec", "#ec8d8c", "#b3302f"]


def setup():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams.update({
        "svg.hashsalt": "ir2vec",            # stable element ids -> byte-identical SVG
        "font.family": "DejaVu Sans", "font.size": 8,
        "axes.edgecolor": INK2, "axes.labelcolor": INK2, "axes.titlecolor": INK,
        "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
        "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": 0.6,
        "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
        "legend.frameon": False, "axes.spines.top": False, "axes.spines.right": False,
    })
    return plt


def save(fig, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=150, metadata={"Software": None})
    fig.savefig(base.with_suffix(".svg"), metadata={"Date": None, "Creator": None})
    import matplotlib.pyplot as plt
    plt.close(fig)


def write_tsv(path: Path, header: list[str], rows: list[list], comments: list[str] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {c}" for block in comments for c in block.split(NL)] +["\t".join(header)]
    lines += ["\t".join(_fmt(x) for x in r) for r in rows]
    path.write_text("\n".join(lines) + "\n")


def _fmt(x) -> str:
    if isinstance(x, float):
        return f"{x:.6f}"
    return str(x)


# ------------------------------------------------------------- vocabulary ---

@dataclass
class LevelVocab:
    level: str
    model: str
    alpha: float
    sha: str
    names: list[str]                     # entities with their own vector (plotted)
    vecs: np.ndarray
    category: dict[str, str]
    low: set[str]                        # low-confidence (hollow markers)
    triples: dict[str, int]              # vector -> training triples (post-merge)
    excluded: list[tuple[str, str]]      # (entity, status) never plotted

    def idx(self, name: str) -> int:
        return self.names.index(name)

    def caption(self) -> str:
        n_fb = sum(s.startswith("fallback") for _, s in self.excluded)
        n_imp = sum(s == "impossible" for _, s in self.excluded)
        return (f"{self.level} · {self.model} · α = {self.alpha} · vocabulary sha256 "
                f"{self.sha[:12]} · not plotted: {n_fb} fallback-mapped, {n_imp} impossible "
                f"(no own vector; listed in the .tsv)" + NL + CATEGORY_NOTES[self.level])


# Category-map asymmetries the reader must know (D8.0), carried on every caption.
CATEGORY_NOTES = {
    "lambda": "categories: Praise is a control form here, Cmm's Craise is runtime; "
              "P_RAW_LOAD/P_RAW_STORE (merged) span strings, bytes and bigstrings",
    "cmm": "categories: Craise is runtime here, Lambda's Praise is a control form; "
           "Cload_narrow is unused (the family did not merge)",
}


def caption_text(lv: "LevelVocab", note: str) -> str:
    return f"{lv.caption()}\n{note}"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vocab_path(level: str, model: str) -> Path:
    return REPO / "vocab" / f"{level}.{model}.json"


def _entity_triples() -> dict[str, dict[str, int]]:
    if not ENTITIES_TSV.exists():
        raise FileNotFoundError(f"{ENTITIES_TSV}: run `ir2vec check entities` first")
    out: dict[str, dict[str, int]] = {"lambda": {}, "cmm": {}}
    lines = ENTITIES_TSV.read_text().splitlines()[1:]
    for line in lines:
        level, _e, _n, vector, vector_triples, _status = line.split("\t")
        if vector:
            out[level][vector] = int(vector_triples)
    return out


def load_level(level: str, path: Path, cfg: VocabConfig) -> LevelVocab:
    raw = path.read_bytes()
    d = json.loads(raw)
    meta = d["metadata"]
    if meta["level"] != level:
        raise ValueError(f"{path}: a {meta['level']} vocabulary, expected {level}")
    cats = catmod.load()
    names = list(d["entities"])
    missing = [n for n in names if n not in cats.of[level]]
    if missing:
        raise ValueError(f"{level}: entities without a category: {missing}")
    excluded = []
    merge = cfg.merge_map(level)
    for e in cats.of[level]:
        if e in names:
            continue
        if e in cfg.impossible[level]:
            excluded.append((e, "impossible"))
        elif e in cfg.fallback_map[level]:
            excluded.append((e, f"fallback -> {cfg.fallback_map[level][e]}"))
        elif e in merge:
            excluded.append((e, f"merged into {merge[e]}"))
        elif e in cats.status[level]:
            excluded.append((e, cats.status[level][e]))
        else:
            excluded.append((e, "no vector"))
    tri = _entity_triples()[level]
    return LevelVocab(level, meta["model"], meta.get("sampling_alpha", 1.0),
                      hashlib.sha256(raw).hexdigest(), names,
                      np.asarray([d["entities"][n] for n in names], dtype=np.float64),
                      {n: cats.of[level][n] for n in names},
                      set(cfg.low_confidence[level]), {n: tri.get(n, 0) for n in names},
                      sorted(excluded))


# ------------------------------------------------------------------- math ---

def pca2(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """2-component PCA (numpy SVD) with a fixed sign convention: the
    largest-magnitude loading of each component is positive. Returns the
    projected points and the explained-variance ratio of the two components."""
    Xc = X - X.mean(axis=0)
    _U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    comps = Vt[:2].copy()
    for k in range(comps.shape[0]):
        j = int(np.argmax(np.abs(comps[k])))
        if comps[k, j] < 0:
            comps[k] = -comps[k]
    var = S ** 2
    ratio = var[:2] / var.sum() if var.sum() > 0 else np.zeros(2)
    return Xc @ comps.T, ratio


def cosine_matrix(X: np.ndarray) -> np.ndarray:
    V = X / np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-12)
    S = V @ V.T
    np.fill_diagonal(S, 1.0)
    return (S + S.T) / 2


def group_distinctness(lv: LevelVocab, members: list[str]) -> float:
    """Phase 7 distinctness of an arbitrary group, over this level's vocabulary."""
    dist = 1.0 - cosine_matrix(lv.vecs)
    iu = np.triu_indices(len(lv.names), k=1)
    overall = float(dist[iu].mean())
    idx = [lv.idx(m) for m in members if m in lv.names]
    if len(idx) < 2:
        return float("nan")
    sub = dist[np.ix_(idx, idx)]
    j = np.triu_indices(len(idx), k=1)
    return float(sub[j].mean()) / overall
