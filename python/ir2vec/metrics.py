"""Corpus-level checks. `plateau` (schema §4, BUILD_SPEC Phase 3.5): the
cumulative number of distinct entities seen (pre-merge), per level, against
the number of packages. A curve that keeps rising means an abstraction rule
is leaking unbounded payloads into entity names."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .inventory import LEVELS, Inventory
from .triples import unit_triples


def plateau(corpus, inv: Inventory) -> list[dict]:
    seen = {lv: set() for lv in LEVELS}
    rows = []
    for k, pkg in enumerate(corpus.packages(), start=1):
        for level in LEVELS:
            for unit in corpus.units_of(level, pkg):
                for h, _r, t in unit_triples(level, unit, {}, count_synthetic=False):
                    seen[level].add(h)
                    seen[level].add(t)
        rows.append({"packages": k, "package": pkg,
                     "lambda_entities": len(seen["lambda"]),
                     "cmm_entities": len(seen["cmm"]),
                     "lambda_inventory": len(inv.lambda_.entities),
                     "cmm_inventory": len(inv.cmm.entities)})
    return rows


def write_plateau(rows: list[dict], out_dir: Path) -> tuple[Path, Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path, png_path = out_dir / "plateau.csv", out_dir / "plateau.png"
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["packages"])
        w.writeheader()
        w.writerows(rows)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    xs = [r["packages"] for r in rows]
    for ax, level in zip(axes, LEVELS):
        ys = [r[f"{level}_entities"] for r in rows]
        inv_total = rows[0][f"{level}_inventory"] if rows else 0
        ax.plot(xs, ys, marker="o", markersize=3, label="seen in corpus")
        ax.axhline(inv_total, linestyle="--", color="gray", label=f"inventory ({inv_total})")
        ax.set_title(f"{level.capitalize()} entities")
        ax.set_xlabel("packages")
        ax.set_ylabel("distinct entities")
        ax.set_ylim(0, inv_total * 1.1 if inv_total else None)
        ax.legend(loc="lower right")
    fig.savefig(png_path, dpi=120)
    plt.close(fig)
    return csv_path, png_path


def entity_report(inv: Inventory, cfg, stats: dict) -> list[dict]:
    """One row per inventory entity: pre-merge triples and its status under the
    frozen config (trained / low-confidence / merged / fallback / impossible)."""
    rows = []
    for level in LEVELS:
        merge = cfg.merge_map(level)
        post: dict[str, int] = {}
        for e, n in stats[level]["entity_triples"].items():
            post[merge.get(e, e)] = post.get(merge.get(e, e), 0) + n
        for e in inv.level(level).entities:
            n = stats[level]["entity_triples"].get(e, 0)
            m = merge.get(e, e)
            if e in cfg.impossible[level]:
                status = "impossible"
            elif e in cfg.fallback_map[level]:
                status = f"fallback->{cfg.fallback_map[level][e]}"
            elif m in cfg.low_confidence[level]:
                status = "low-confidence" + (f" (merged into {m})" if m != e else "")
            else:
                status = "trained" + (f" (merged into {m})" if m != e else "")
            rows.append({"level": level, "entity": e, "triples": n,
                         "vector": m if status.startswith(("trained", "low")) else "",
                         "vector_triples": post.get(m, 0) if status.startswith(("trained", "low")) else 0,
                         "status": status})
    return rows


def distinct_triples(tsv: Path) -> tuple[int, int]:
    seen, n = set(), 0
    with tsv.open() as fh:
        for line in fh:
            n += 1
            seen.add(line)
    return n, len(seen)


# ------------------------------------------------ embedding geometry ---

# Sibling groups of schema §4, per level: explicit inventory lists or name prefixes.
DISTINCTNESS_GROUPS = {
    "lambda": [("types", "types"), ("operand_kinds", "operand_kinds"),
               ("Lapply_a*", "Lapply_a"), ("Lfunction_a*", "Lfunction_a"),
               ("Pgetglobal_*", "Pgetglobal_")],
    "cmm": [("types", "types"), ("operand_kinds", "operand_kinds"),
            ("Cload_*", "Cload_"), ("Cstore_*", "Cstore_")],
}
DISTINCTNESS_FLAG = 0.1
RARE_FAMILIES = {
    "lambda": ["Pperform", "Presume", "Prunstack", "Preperform", "Patomic_load", "Pdls_get"],
    "cmm": ["C_RUNTIME", "Cstore_byte_s"],
}


def load_vocab(path: Path) -> tuple[dict, list[str], np.ndarray]:
    d = json.loads(Path(path).read_text())
    names = list(d["entities"])
    return d["metadata"], names, np.asarray([d["entities"][n] for n in names], dtype=np.float64)


def _cos_dist(vecs):
    v = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)
    return 1.0 - v @ v.T


def _mean_pairs(dist, idx) -> float:
    idx = list(idx)
    if len(idx) < 2:
        return float("nan")
    sub = dist[np.ix_(idx, idx)]
    iu = np.triu_indices(len(idx), k=1)
    return float(sub[iu].mean())


def distinctness(level: str, inv: Inventory, names: list[str], vecs) -> dict:
    """score = mean within-group cosine distance / mean over all entity pairs."""
    dist = _cos_dist(vecs)
    overall = _mean_pairs(dist, range(len(names)))
    lv = inv.level(level)
    out = {"_all_pairs": overall}
    for group, spec in DISTINCTNESS_GROUPS[level]:
        if spec in ("types", "operand_kinds"):
            members = [n for n in getattr(lv, spec) if n in names]
        else:
            members = [n for n in names if n.startswith(spec)]
        within = _mean_pairs(dist, [names.index(m) for m in members])
        score = within / overall if overall else float("nan")
        out[group] = {"members": members, "within": within, "score": score,
                      "flag": bool(score < DISTINCTNESS_FLAG)}
    return out


def rare_report(level: str, meta: dict, names: list[str], vecs, k: int = 5) -> dict:
    """Neighbours and movement of the rare families; cohesion of low-confidence entities."""
    dist = _cos_dist(vecs)
    idx = {n: i for i, n in enumerate(names)}
    movement = meta.get("movement", {})
    low = [n for n in meta.get("low_confidence", {}) if n in idx]
    rest = [n for n in names if n not in low]
    fam = {}
    for e in RARE_FAMILIES[level]:
        if e not in idx:
            continue
        order = [j for j in np.argsort(dist[idx[e]], kind="stable") if j != idx[e]][:k]
        fam[e] = {"movement": movement.get(e),
                  "neighbours": [(names[j], round(1 - float(dist[idx[e], j]), 3)) for j in order],
                  "low_confidence_neighbours": sum(names[j] in low for j in order)}
    mean_move = lambda ns: float(np.mean([movement[n] for n in ns])) if ns and movement else None  # noqa: E731
    return {
        "families": fam,
        "low_confidence": len(low),
        "movement_low": mean_move(low), "movement_rest": mean_move(rest),
        # < 1: low-confidence entities sit closer to each other than an average pair
        "low_cohesion_ratio": (_mean_pairs(dist, [idx[n] for n in low])
                               / _mean_pairs(dist, range(len(names)))) if len(low) > 1 else None,
    }


def cmm_only_kind(name: str) -> str:
    """Why a Cmm function may have no Lambda counterpart."""
    from .align import cmm_local
    local = cmm_local(name)
    base = local.rsplit("_", 1)[0] if local.rsplit("_", 1)[-1].isdigit() else local
    if base == "fun":
        return "synthesised_closure"      # closure conversion (eta-expansions, wrappers)
    if base.endswith("_inner"):
        return "optional_arg_inner"       # inner half of a function with optional args
    return "other"


def alignment_report(corpus) -> tuple[dict, list[dict]]:
    """Corpus-wide Lambda<->Cmm match rate and every unmatched function."""
    from .align import align, cmm_parents
    totals = {"units": 0, "lambda_functions": 0, "matched": 0, "cmm_functions": 0,
              "by": {"entry": 0, "stamp": 0, "location": 0, "params": 0},
              "unmatched": {"named": 0, "anonymous": 0, "module_init": 0},
              "cmm_only": {"synthesised_closure": 0, "optional_arg_inner": 0, "other": 0},
              "cmm_only_parent": {"lambda_fid": 0, "cmm_only_parent": 0, "none": 0}}
    rows = []
    for pkg in corpus.packages():
        for lf in corpus.unit_files("lambda", pkg):
            lam = json.loads(lf.read_text())
            cmm = json.loads(lf.with_name(lf.name[: -len(".lambda.json")] + ".cmm.json").read_text())
            a = align(lam, cmm)
            recs = {r["fid"]: r for r in lam["functions"]}
            totals["units"] += 1
            totals["lambda_functions"] += a.n_lambda
            totals["matched"] += len(a.matches)
            totals["cmm_functions"] += len(cmm["functions"])
            for m in a.matches:
                totals["by"][m.by] += 1
            for cat, fids in a.unmatched_lambda.items():
                totals["unmatched"][cat] += len(fids)
                for fid in fids:
                    loc = recs[fid]["loc"]
                    rows.append({"package": pkg, "unit": a.unit, "side": "lambda_only",
                                 "category": cat, "function": fid,
                                 "loc": f"{loc['file']}:{loc['l1']}:{loc['c1']}" if loc else ""})
            fns = {f["name"]: f for f in cmm["functions"]}
            parents = cmm_parents(cmm)
            fid_of = {m.cmm: m.fid for m in a.matches}
            for name in a.cmm_only:
                par = parents.get(name)
                totals["cmm_only_parent"]["lambda_fid" if par in fid_of else
                                          "cmm_only_parent" if par else "none"] += 1
                kind = cmm_only_kind(name)
                totals["cmm_only"][kind] += 1
                loc = fns[name]["loc"]
                rows.append({"package": pkg, "unit": a.unit, "side": "cmm_only", "category": kind,
                             "function": name,
                             "loc": f"{loc['file']}:{loc['l1']}:{loc['c1']}" if loc else ""})
    totals["match_rate"] = totals["matched"] / totals["lambda_functions"] if totals["lambda_functions"] else None
    return totals, rows


def encode_check(corpus, vocab_lambda: Path, vocab_cmm: Path, cfg) -> dict:
    """Run all four cells over every selected unit: inference-time unknown /
    fallback / impossible lookups and solver statistics at corpus scale."""
    from .encode import cmm_enc, lambda_enc
    from .encode.vocab import ImpossibleEntity, Vocabulary, Weights
    w = Weights.load()
    vl, vc = Vocabulary.load(vocab_lambda, cfg), Vocabulary.load(vocab_cmm, cfg)
    st = {"units": 0, "lambda_functions": 0, "cmm_functions": 0, "impossible": 0,
          "cyclic_sccs": 0, "largest_scc": 0, "max_residual": 0.0, "retries": 0,
          "non_finite": 0, "dead_cops": 0, "n_cops": 0}
    for pkg in corpus.packages():
        for lf in corpus.unit_files("lambda", pkg):
            lam = json.loads(lf.read_text())
            cmm = json.loads(lf.with_name(lf.name[: -len(".lambda.json")] + ".cmm.json").read_text())
            st["units"] += 1
            try:
                fvs = (lambda_enc.lambda_sym(lam, vl, w) + lambda_enc.lambda_fa(lam, vl, w))
                cvs = (cmm_enc.cmm_sym(cmm, vc, w, cfg.count_synthetic)
                       + cmm_enc.cmm_fa(cmm, vc, w, cfg.count_synthetic))
            except ImpossibleEntity:
                st["impossible"] += 1
                continue
            st["lambda_functions"] += len(fvs) // 2
            st["cmm_functions"] += len(cvs) // 2
            for fv in fvs + cvs:
                s = fv.stats
                st["cyclic_sccs"] += s.cyclic_sccs
                st["largest_scc"] = max([st["largest_scc"], *s.cyclic_sizes])
                st["max_residual"] = max(st["max_residual"], s.max_residual)
                st["retries"] += len(s.retries)
                st["non_finite"] += int(not np.isfinite(fv.vector).all())
            for f in cmm["functions"]:
                st["dead_cops"] += f["dead_cops"]
                st["n_cops"] += f["n_cops"]
    st["lookup"] = {"lambda": vl.report(), "cmm": vc.report()}
    return st
