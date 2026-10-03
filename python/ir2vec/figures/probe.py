"""§8.7 Linear probe on the 256 learned dimensions.

L2-regularised logistic regression (numpy Newton/IRLS, lambda = RIDGE on the
weights, not the bias), features standardised on each training fold, 5-fold
stratified CV with folds assigned by the row-key hash. Reported: ROC AUC
mean ± std over folds, accuracy against the majority-class baseline, and a
shuffled-label control (labels permuted with a fixed seed, same folds).

Two controls beside the shuffled labels (D8.7):
  size only   - the same probe on log1p(Lambda node count) alone: how much of
                a property is just function size;
  by package  - folds grouped by package (no package in both train and test),
                so near-duplicate code in one package cannot leak across folds.

What this measures: whether a property is *linearly decodable* from the
learned blocks, not whether the embedding is useful for any task.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import common as C
from .functions import key_hash

FOLDS = 5
RIDGE = 1.0
SEED = 8_007
MIN_CLASS = 10
TASKS = [("recursive", "recursive"), ("allocating", "allocating"),
         ("uses effects", "effects"), ("arity ≥ 2", "arity")]


def fit_logistic(X: np.ndarray, y: np.ndarray, ridge: float = RIDGE,
                 iters: int = 100, tol: float = 1e-10) -> np.ndarray:
    """Newton's method; returns [bias, w...]."""
    A = np.hstack([np.ones((len(X), 1)), X])
    beta = np.zeros(A.shape[1])
    R = ridge * np.eye(A.shape[1])
    R[0, 0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(A @ beta, -35, 35)))
        g = A.T @ (p - y) + R @ beta
        H = (A * (p * (1 - p))[:, None]).T @ A + R
        step = np.linalg.solve(H, g)
        beta -= step
        if np.max(np.abs(step)) < tol:
            break
    return beta


def predict(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(beta[0] + X @ beta[1:], -35, 35)))


def auc(y: np.ndarray, s: np.ndarray) -> float:
    """Mann-Whitney AUC with average ranks for ties."""
    order = np.argsort(s, kind="stable")
    ranks = np.empty(len(s))
    ss = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and ss[j + 1] == ss[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    npos, nneg = int(y.sum()), int((~y.astype(bool)).sum())
    return float((ranks[y.astype(bool)].sum() - npos * (npos + 1) / 2) / (npos * nneg))


def folds(keys: np.ndarray, y: np.ndarray, k: int = FOLDS) -> np.ndarray:
    f = np.empty(len(y), dtype=int)
    for cls in (False, True):
        idx = np.flatnonzero(y == cls)
        idx = idx[np.argsort([key_hash(keys[i]) for i in idx], kind="stable")]
        f[idx] = np.arange(len(idx)) % k
    return f


def package_folds(packages: np.ndarray, k: int = FOLDS) -> np.ndarray:
    """Whole packages to folds: largest first (ties by name), each to the
    currently smallest fold."""
    sizes = {}
    for p in packages.tolist():
        sizes[p] = sizes.get(p, 0) + 1
    load, of = [0] * k, {}
    for p in sorted(sizes, key=lambda q: (-sizes[q], q)):
        j = min(range(k), key=lambda i: (load[i], i))
        of[p] = j
        load[j] += sizes[p]
    return np.asarray([of[p] for p in packages.tolist()])


def cross_validate(X: np.ndarray, y: np.ndarray, keys: np.ndarray,
                   fo: np.ndarray | None = None) -> dict:
    fo = folds(keys, y) if fo is None else fo
    aucs, accs = [], []
    for k in range(FOLDS):
        tr, te = fo != k, fo == k
        if y[te].all() or not y[te].any() or y[tr].all() or not y[tr].any():
            continue                     # a fold without both classes has no AUC
        mu, sd = X[tr].mean(axis=0), X[tr].std(axis=0)
        sd[sd == 0] = 1.0
        beta = fit_logistic((X[tr] - mu) / sd, y[tr].astype(float))
        s = predict(beta, (X[te] - mu) / sd)
        aucs.append(auc(y[te], s))
        accs.append(float(np.mean((s > 0.5) == y[te])))
    return {"auc_mean": float(np.mean(aucs)), "auc_std": float(np.std(aucs)),
            "acc_mean": float(np.mean(accs)), "aucs": aucs, "folds_used": len(aucs)}


def run(d: dict) -> list[dict]:
    X = d["X"]
    assert X.shape[1] == 256, "the probe reads the learned blocks only (§8.7)"
    out = []
    for label, field in TASKS:
        if field == "arity":
            keep = d["arity"] >= 0
            y = d["arity"][keep] >= 1
        else:
            keep = np.ones(len(X), dtype=bool)
            y = d[field].astype(bool)
        Xk, kk, pk = X[keep], d["keys"][keep], d["package"][keep]
        size = np.log1p(d["lambda_nodes"][keep].astype(float))[:, None]
        pos, neg = int(y.sum()), int((~y).sum())
        r = {"property": label, "n": int(len(y)), "positives": pos,
             "majority_acc": max(pos, neg) / len(y)}
        if min(pos, neg) < MIN_CLASS:
            r["status"] = f"too few in the minority class ({min(pos, neg)} < {MIN_CLASS})"
            out.append(r)
            continue
        r |= cross_validate(Xk, y, kk)
        ys = np.random.default_rng(SEED).permutation(y)
        sh = cross_validate(Xk, ys, kk)
        sz = cross_validate(size, y, kk)
        gp = cross_validate(Xk, y, kk, package_folds(pk))
        r |= {"shuffled_auc_mean": sh["auc_mean"], "shuffled_auc_std": sh["auc_std"],
              "size_auc_mean": sz["auc_mean"], "size_auc_std": sz["auc_std"],
              "package_auc_mean": gp["auc_mean"], "package_auc_std": gp["auc_std"],
              "package_folds_used": gp["folds_used"], "status": "ok"}
        out.append(r)
    return out


def draw(results: dict[str, tuple[dict, list[dict]]], out_dir: Path = C.OUT_DIR) -> Path:
    """results: model -> (function data meta, probe rows)."""
    plt = C.setup()
    models = [m for m in ("complex", "transe") if m in results]
    props = [t[0] for t in TASKS]
    fig, ax = plt.subplots(figsize=(11, 5.6))
    tsv, caps = [], []
    kinds = [("auc", "o", True, "probe, key-hash folds"),
             ("package_auc", "D", True, "probe, package-grouped folds"),
             ("size_auc", "X", True, "size only (log node count)"),
             ("shuffled_auc", "o", False, "shuffled labels")]
    for k, m in enumerate(models):
        meta, rows = results[m]
        caps.append(f"{m}: lambda {meta['vocab_sha256']['lambda'][:12]} "
                    f"cmm {meta['vocab_sha256']['cmm'][:12]}")
        for i, r in enumerate(rows):
            y = i + (k - 0.5) * 0.36
            tsv.append([m, r["property"], r["n"], r["positives"], r["majority_acc"],
                        *[r.get(f"{a}_{b}", "") for a, *_ in kinds for b in ("mean", "std")],
                        r.get("acc_mean", ""), r.get("package_folds_used", ""), r["status"]])
            if r["status"] != "ok":
                ax.annotate(f"{m}: {r['status']}", (0.51, y), fontsize=6.5, va="center",
                            color=C.INK2)
                continue
            for j, (a, mk, filled, lab) in enumerate(kinds):
                ax.errorbar(r[f"{a}_mean"], y + (j - 1.5) * 0.05, xerr=r[f"{a}_std"], fmt=mk,
                            ms=6, capsize=2, color=C.SERIES[k], mec=C.SERIES[k],
                            mfc=C.SERIES[k] if filled else "none", elinewidth=1,
                            label=f"{m}: {lab}" if i == 0 else None)
            ax.annotate(f"{m}: {r['auc_mean']:.3f} ± {r['auc_std']:.3f} · by package "
                        f"{r['package_auc_mean']:.3f}"
                        + (f" ({r['package_folds_used']}/{FOLDS} folds have both classes)"
                           if r["package_folds_used"] < FOLDS else "")
                        + f" · size only {r['size_auc_mean']:.3f} · "
                        f"acc {r['acc_mean']:.3f} vs majority {r['majority_acc']:.3f} · "
                        f"pos {r['positives']:,}/{r['n']:,}",
                        (1.02, y), fontsize=6.2, va="center", color=C.INK)
    ax.axvline(0.5, color=C.INK2, linestyle="--", linewidth=1)
    ax.set_yticks(range(len(props)), props)
    ax.invert_yaxis()
    ax.set_xlim(0.35, 1.62)
    ax.set_xticks(np.arange(0.4, 1.01, 0.1))
    ax.set_xlabel(f"ROC AUC, {FOLDS}-fold CV (mean ± std over folds); 0.5 = chance")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4, fontsize=6.5)
    ax.set_title("Linear probe on the 256 learned dimensions (L2(lambda_sym) ⊕ L2(cmm_fa)): "
                 "linear decodability, not usefulness", fontsize=9)
    fig.text(0.01, 0.005, f"logistic regression, ridge {RIDGE}, fold-wise standardisation · "
             + " · ".join(caps), fontsize=6, color=C.INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    base = out_dir / "probe"
    C.save(fig, base)
    C.write_tsv(base.with_suffix(".tsv"),
                ["model", "property", "n", "positives", "majority_acc",
                 *[f"{a}_{b}" for a, *_ in kinds for b in ("mean", "std")],
                 "acc_mean", "package_folds_used", "status"], tsv,
                ["features: the 256 learned dimensions only; labels from the IR (functions.py)",
                 f"folds: stratified by sha256(key), or whole packages (package_*); ridge {RIDGE}; "
                 f"shuffle seed {SEED}; size_* = the same probe on log1p(Lambda node count) alone"])
    (out_dir / "probe.json").write_text(json.dumps(
        {m: rows for m, (_meta, rows) in results.items()}, indent=1) + "\n")
    return base
