"""§8.6 Function-level projection of the corpus: learned blocks only.

The plotted vector is L2(lambda_sym) ⊕ L2(cmm_fa), the 256 learned
dimensions, never the 438-D final vector: its count features contain
CALL_SELF, ALLOC and the arity signature directly, so colouring by recursion,
allocation or arity would separate by construction and prove nothing.

Rows: aligned functions of the selected corpus. module_init rows (one per
unit, aligned to the unit's entry function) are excluded: a module
initialiser is a different kind of object from a function. Labels come from the IR,
not from the vector:
  recursive  - Lambda count CALL_SELF > 0
  allocating - an owned Pmakeblock / Pmakearray node or a Calloc instruction
               (partly visible to the learned blocks by construction: those
               entities contribute their own seed vectors)
  arity      - the Lambda signature block (ARITY_1 / ARITY_2 / ARITY_3 or 4P)
  effects    - an owned Pperform / Presume / Prunstack / Preperform node
  package    - the opam package (style and domain; treat sceptically)
PCA is fitted on every row; the plot shows a deterministic hash sample
(sha256 of "package/unit/fid", recorded in the .tsv).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from ..config import VocabConfig
from ..corpus import Corpus
from ..embed import embed_units, l2
from ..encode.vocab import Weights
from ..triples import owned_nodes
from . import common as C

ALLOC_OPS = {"Pmakeblock", "Pmakearray"}
CMM_ALLOC_OPS = {"Calloc"}
EFFECT_OPS = {"Pperform", "Presume", "Prunstack", "Preperform"}
ARITY = ["1", "2", "≥3"]
SAMPLE_TARGET = 4000
LEARNED = ("lambda_sym", "cmm_fa")


def default_paths(model: str) -> dict[str, Path]:
    return {lvl: C.vocab_path(lvl, model) for lvl in ("lambda", "cmm")}


def cache_path(corpus: Corpus, model: str, paths: dict[str, Path]) -> Path:
    sha = "".join(C._sha(paths[lvl])[:8] for lvl in ("lambda", "cmm"))
    return corpus.root / "cache" / f"functions_{model}_{sha}.npz"


def row_key(pkg: str, unit: str, fid) -> str:
    return f"{pkg}/{unit}/{fid}"


def key_hash(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)


def build(corpus: Corpus, model: str, cfg: VocabConfig,
          paths: dict[str, Path] | None = None) -> dict:
    """Encode every selected unit; keep the 256 learned dimensions and labels."""
    paths = paths or default_paths(model)
    vl, vc = paths["lambda"], paths["cmm"]
    w = Weights.load()
    X, keys, pkgs, rec, alloc, eff, arity, nodes = [], [], [], [], [], [], [], []
    tally: Counter = Counter()
    units = 0
    for pkg in corpus.packages():
        for lf in corpus.unit_files("lambda", pkg):
            lam = json.loads(lf.read_text())
            cmm = json.loads(lf.with_name(lf.name[: -len(".lambda.json")]
                                          + ".cmm.json").read_text())
            res = embed_units([(lam, cmm)], vl, vc, cfg, w)
            units += 1
            names = res["metadata"]["count_features"]["lambda"]
            ci = {n: i for i, n in enumerate(names)}
            lrec = {r["fid"]: r for r in lam["functions"]}
            cfun = {f["name"]: f for f in cmm["functions"]}
            for row in res["units"][0]["functions"]:
                tally[row["category"]] += 1
                if not row["aligned"]:
                    continue
                if row["lambda_kind"] == "module_init":
                    tally["excluded_module_init"] += 1
                    continue
                v = np.concatenate([l2(np.asarray(row[b])) for b in LEARNED])
                X.append(v)
                keys.append(row_key(pkg, lam["unit"], row["lambda_fid"]))
                pkgs.append(pkg)
                cl = row["counts_lambda"]
                rec.append(cl[ci["CALL_SELF"]] > 0)
                ops = {n["op"] for n in owned_nodes(lrec[row["lambda_fid"]])}
                cops = {i["op"] for b in cfun[row["cmm_name"]]["blocks"] for i in b["instrs"]}
                alloc.append(bool(ops & ALLOC_OPS or cops & CMM_ALLOC_OPS))
                eff.append(bool(ops & EFFECT_OPS))
                a = [cl[ci[f"ARITY_{k}"]] for k in ("1", "2", "3", "4P")]
                arity.append(-1 if max(a) == 0 else min(int(np.argmax(a)), 2))
                nodes.append(row["node_counts"][0])
    X = np.asarray(X)
    dims = res["metadata"]["dims"]
    assert X.shape[1] == dims["lambda_sym"] + dims["cmm_fa"] == 256, X.shape
    return {"X": X, "keys": np.asarray(keys), "package": np.asarray(pkgs),
            "recursive": np.asarray(rec), "allocating": np.asarray(alloc),
            "effects": np.asarray(eff), "arity": np.asarray(arity),
            "lambda_nodes": np.asarray(nodes),
            "meta": json.dumps({"model": model, "units": units, "rows": dict(sorted(tally.items())),
                                "vocab_sha256": {lvl: C._sha(paths[lvl])
                                                 for lvl in ("lambda", "cmm")},
                                "config_sha256": cfg.config_sha256,
                                "blocks": list(LEARNED), "dims": X.shape[1]})}


def load_or_build(corpus: Corpus, model: str, cfg: VocabConfig,
                  paths: dict[str, Path] | None = None) -> dict:
    paths = paths or default_paths(model)
    path = cache_path(corpus, model, paths)
    if path.exists():
        z = np.load(path, allow_pickle=False)
        return {k: z[k] for k in z.files} | {"meta": str(z["meta"])}
    d = build(corpus, model, cfg, paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **d)
    return d


def sample_mask(keys: np.ndarray, target: int = SAMPLE_TARGET) -> tuple[np.ndarray, int]:
    m = max(1, math.ceil(len(keys) / target))
    return np.asarray([key_hash(k) % m == 0 for k in keys]), m


def _distinctness(Xs: np.ndarray, mask: np.ndarray) -> float:
    V = Xs / np.maximum(np.linalg.norm(Xs, axis=1, keepdims=True), 1e-12)
    D = 1.0 - V @ V.T
    n = len(V)
    overall = (D.sum() - np.trace(D)) / (n * (n - 1))
    k = int(mask.sum())
    if k < 2:
        return float("nan")
    sub = D[np.ix_(mask, mask)]
    return float((sub.sum() - np.trace(sub)) / (k * (k - 1)) / overall)


def draw(d: dict, out_dir: Path = C.OUT_DIR) -> Path:
    plt = C.setup()
    meta = json.loads(d["meta"])
    X = d["X"]
    assert X.shape[1] == 256, "only the learned blocks may be projected (§8.6)"
    P, ratio = C.pca2(X)
    mask, m = sample_mask(d["keys"])
    Ps, Xs = P[mask], X[mask]
    fig, axes = plt.subplots(2, 3, figsize=(15, 9.6))
    axes = axes.ravel()

    def binary(ax, name, lab, rare=False):
        y = lab[mask]
        ax.scatter(Ps[~y, 0], Ps[~y, 1], s=3, color=C.CONTEXT, linewidths=0,
                   label=f"no (n = {int((~y).sum())}, sample)")
        if rare:
            # too rare for the hash sample: every positive in the corpus, same PCA
            allpos = np.flatnonzero(lab)
            dist = _distinctness(np.vstack([Xs, X[allpos]]),
                                 np.r_[np.zeros(len(Xs), bool), np.ones(len(allpos), bool)])
            ax.scatter(P[allpos, 0], P[allpos, 1], s=22, color=C.SERIES[0], linewidths=0,
                       label=f"yes: all {len(allpos)} in the corpus, not sampled "
                             f"(d = {dist:.2f})")
            ax.set_title(name, fontsize=9)
            return [name + " (all corpus positives)", len(allpos), int(len(y)), dist]
        dist = _distinctness(Xs, y)
        ax.scatter(Ps[y, 0], Ps[y, 1], s=5, color=C.SERIES[0], linewidths=0,
                   label=f"yes (n = {int(y.sum())}, d = {dist:.2f})")
        ax.set_title(name, fontsize=9)
        return [name, int(y.sum()), int(len(y)), dist]

    rows = [binary(axes[0], "recursive (CALL_SELF > 0)", d["recursive"]),
            binary(axes[1], "allocating (Pmakeblock / Pmakearray / Calloc)", d["allocating"]),
            binary(axes[3], "uses effects (Pperform / Presume / Prunstack / Preperform)",
                   d["effects"], rare=True)]
    ar = d["arity"][mask]
    ax = axes[2]
    if (ar < 0).any():
        ax.scatter(Ps[ar < 0, 0], Ps[ar < 0, 1], s=3, color=C.CONTEXT, linewidths=0,
                   label=f"no signature (n = {int((ar < 0).sum())})")
    for k, name in enumerate(ARITY):
        sel = ar == k
        dist = _distinctness(Xs, sel)
        ax.scatter(Ps[sel, 0], Ps[sel, 1], s=4, color=C.SERIES[k], linewidths=0,
                   label=f"arity {name} (n = {int(sel.sum())}, d = {dist:.2f})")
        rows.append([f"arity {name}", int(sel.sum()), int(len(ar)), dist])
    ax.set_title("arity (Lambda signature block)", fontsize=9)
    pk = d["package"][mask]
    top = [p for p, _ in sorted(Counter(pk.tolist()).items(), key=lambda t: (-t[1], t[0]))[:3]]
    ax = axes[4]
    other = ~np.isin(pk, top)
    ax.scatter(Ps[other, 0], Ps[other, 1], s=3, color=C.CONTEXT, linewidths=0,
               label=f"other packages (n = {int(other.sum())})")
    for k, p in enumerate(top):
        sel = pk == p
        dist = _distinctness(Xs, sel)
        ax.scatter(Ps[sel, 0], Ps[sel, 1], s=4, color=C.SERIES[k], linewidths=0,
                   label=f"{p} (n = {int(sel.sum())}, d = {dist:.2f})")
        rows.append([f"package {p}", int(sel.sum()), int(len(pk)), dist])
    ax.set_title("package, 3 largest in the sample (style/domain: treat sceptically)", fontsize=9)
    for ax in axes[:5]:
        ax.set_xlabel("PC1")
        ax.set_ylabel("PC2")
        ax.legend(loc="upper left", fontsize=6.5, markerscale=2.5)
    axes[5].axis("off")
    counts = meta["rows"]
    axes[5].text(0, 1, "\n".join([
        "What is plotted",
        f"  L2(lambda_sym) ⊕ L2(cmm_fa): the {X.shape[1]} learned dimensions only.",
        "  The 182 count and node features are left out: they hold CALL_SELF,",
        "  ALLOC and the arity signature, so they would separate these labels",
        "  by construction and prove nothing.",
        "",
        f"  rows: {len(X):,} aligned functions from {meta['units']:,} units",
        f"  (module_init rows excluded: {counts.get('excluded_module_init', 0)}; unaligned "
        f"rows not used: {sum(v for k, v in counts.items() if k not in ('aligned', 'excluded_module_init')):,})",
        f"  PCA fitted on all {len(X):,} rows; plotted: {int(mask.sum()):,} "
        f"(sha256(key) mod {m} = 0)",
        "",
        "Caveats",
        "  allocating / effects: those opcodes' seed vectors are summed into",
        "  the learned blocks, so partial visibility is expected by construction.",
        "  recursion and arity are not entities in the learned vocabulary.",
        "  effects: too rare for the sample, so all corpus positives are drawn.",
        "  d = distinctness of the group in full 256-D over the plotted sample",
        "  (< 1: tighter than an average pair). No claim is read off the 2-D",
        "  positions; the linear probe (probe.png) gives the decodability numbers.",
    ]), fontsize=7.5, va="top", family="DejaVu Sans", color=C.INK)
    fig.suptitle(f"Functions — PCA of the learned blocks, {meta['model']} "
                 f"(PC1 {ratio[0]:.1%}, PC2 {ratio[1]:.1%} of variance)", fontsize=10)
    sha = meta["vocab_sha256"]
    fig.text(0.01, 0.005, f"{meta['model']} · α = 0.75 · lambda {sha['lambda'][:12]} · "
             f"cmm {sha['cmm'][:12]} · config {meta['config_sha256'][:12]}\n"
             f"{counts.get('excluded_module_init', 0):,} module_init rows excluded: top-level "
             "initialisation code, one per unit, not a function anyone wrote "
             "(Pgetglobal_self + Lsequence + Psetfield = 52% of its Lambda nodes: stores into "
             "the module block); it would pull the PCA toward a structure that says nothing "
             "about functions",
             fontsize=6, color=C.INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    base = out_dir / f"functions_{meta['model']}"
    C.save(fig, base)
    idx = np.flatnonzero(mask)
    C.write_tsv(base.with_suffix(".tsv"),
                ["key", "package", "recursive", "allocating", "effects", "arity", "pc1", "pc2"],
                [[d["keys"][i], d["package"][i], int(d["recursive"][i]),
                  int(d["allocating"][i]), int(d["effects"][i]),
                  "" if d["arity"][i] < 0 else ARITY[d["arity"][i]],
                  float(P[i, 0]), float(P[i, 1])] for i in idx],
                [f"learned blocks only: {', '.join(meta['blocks'])} ({X.shape[1]}-D)",
                 f"PCA on {len(X)} rows, explained PC1 {ratio[0]:.6f} PC2 {ratio[1]:.6f}",
                 f"sample: sha256(key)[:12] mod {m} == 0 -> {int(mask.sum())} rows",
                 f"module_init rows excluded ({counts.get('excluded_module_init', 0)}): "
                 "top-level initialisation code, not functions",
                 "group distinctness (256-D, sample): " + "; ".join(
                     f"{r[0]} n={r[1]} d={r[3]:.4f}" for r in rows),
                 "row accounting: " + json.dumps(counts)])
    return base
