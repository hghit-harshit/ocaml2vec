"""§8.5 Analogy (offset-consistency) test against a random-pair null.

For a quadruple (a, b) vs (c, d) the statistic is cos(b - a, d - c): +1 if
the two relations are the same vector offset. A raw cosine means nothing on
its own, so every value is placed in a null distribution of NULL_DRAWS
cosines between the difference vectors of two random pairs of distinct
entities (4 distinct entities, like every tested quadruple), drawn with a
fixed seed from the same vocabulary.

Decision rule, fixed before looking (D8.5): one-sided; a quadruple "holds"
when its cosine exceeds the Bonferroni-corrected null percentile
100 * (1 - 0.05 / k), k = testable quadruples at that level; "above 95th
only" when it passes the uncorrected 95th percentile but not the corrected
one; otherwise "does not hold". A quadruple with an entity that has no own
vector (fallback-mapped, impossible) is reported as untestable, never scored
via the fallback target.

Secondary control (D8.5): the random-pair null cannot tell a genuine
relation offset from two pairs that merely link the same two clusters (if
a ~ c and b ~ d, then b - a ~ d - c for any members). The category-matched
null draws each of the four positions from the tested entity's own category
(4 distinct entities, MATCHED_DRAWS draws); a quadruple that is not above
it is explained by category membership alone. Reported beside the primary
verdict, which stays the one defined above.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import common as C

NULL_DRAWS = 10_000
MATCHED_DRAWS = 2_000
SEED = 8_005
ALPHA = 0.05

ANALOGIES = {
    "lambda": [
        (("Paddint", "Psubint"), ("Paddfloat", "Psubfloat")),
        (("Paddint", "Paddbint"), ("Psubint", "Psubbint")),
        (("Parrayrefu", "Parraysetu"), ("Parrayrefs", "Parraysets")),
        (("Pstringrefu", "Pbytesrefu"), ("Pstringlength", "Pbyteslength")),
        (("Lapply_a1", "Lapply_a2"), ("Lfunction_a1", "Lfunction_a2")),
    ],
    "cmm": [
        (("Caddi", "Csubi"), ("Caddf", "Csubf")),
        (("Cload_word_val", "Cstore_word_val"), ("Cload_double", "Cstore_double")),
        (("Cload_byte_u", "Cload_byte_s"), ("Cload_16u", "Cload_16s")),
    ],
}


def _cos(u: np.ndarray, v: np.ndarray) -> float:
    return float(u @ v / max(np.linalg.norm(u) * np.linalg.norm(v), 1e-12))


def null_distribution(vecs: np.ndarray, draws: int = NULL_DRAWS, seed: int = SEED) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.empty(draws)
    for t in range(draws):
        a, b, c, d = rng.choice(len(vecs), size=4, replace=False)
        out[t] = _cos(vecs[b] - vecs[a], vecs[d] - vecs[c])
    return out


def matched_null(lv, quad, draws: int = MATCHED_DRAWS, seed: int = SEED) -> np.ndarray:
    (a, b), (c, d) = quad
    pools = [[lv.idx(n) for n in lv.names if lv.category[n] == lv.category[e]]
             for e in (a, b, c, d)]
    rng = np.random.default_rng(seed)
    out = []
    while len(out) < draws:
        pick = [int(rng.choice(p)) for p in pools]
        if len(set(pick)) < 4:
            continue
        i, j, k, m = pick
        out.append(_cos(lv.vecs[j] - lv.vecs[i], lv.vecs[m] - lv.vecs[k]))
    return np.asarray(out)


def percentile(null: np.ndarray, x: float) -> float:
    """Percentage of null draws strictly below x (ties count half)."""
    return float(100.0 * (np.sum(null < x) + 0.5 * np.sum(null == x)) / len(null))


def evaluate(lv) -> dict:
    null = null_distribution(lv.vecs)
    status = dict(lv.excluded)
    quads = ANALOGIES[lv.level]
    testable = [q for q in quads if all(e in lv.names for p in q for e in p)]
    k = max(len(testable), 1)
    p95 = float(np.percentile(null, 95))
    corrected_pct = 100 * (1 - ALPHA / k)
    pbon = float(np.percentile(null, corrected_pct))
    rows = []
    for (a, b), (c, d) in quads:
        missing = [e for e in (a, b, c, d) if e not in lv.names]
        r = {"pair1": f"({a}, {b})", "pair2": f"({c}, {d})"}
        if missing:
            r.update(cosine=None, percentile=None, z=None, matched_percentile=None,
                     cos_ac=None, cos_bd=None,
                     verdict="untestable: " + "; ".join(f"{e} {status.get(e, 'no vector')}"
                                                         for e in missing))
        else:
            I = lv.idx
            x = _cos(lv.vecs[I(b)] - lv.vecs[I(a)], lv.vecs[I(d)] - lv.vecs[I(c)])
            pct = percentile(null, x)
            verdict = ("holds" if x > pbon else
                       "above 95th only (not significant after correction)" if x > p95 else
                       "does not hold")
            mpct = percentile(matched_null(lv, ((a, b), (c, d))), x)
            S = lambda u, v: _cos(lv.vecs[I(u)], lv.vecs[I(v)])  # noqa: E731
            r.update(cosine=x, percentile=pct, z=(x - null.mean()) / null.std(), verdict=verdict,
                     matched_percentile=mpct, cos_ac=S(a, c), cos_bd=S(b, d))
        rows.append(r)
    held = sum(r["verdict"] == "holds" for r in rows)
    return {"null": null, "mean": float(null.mean()), "std": float(null.std()),
            "p95": p95, "p_corrected": pbon, "corrected_percentile": corrected_pct,
            "k": len(testable), "rows": rows, "held": held}


def draw(lvs: list, out_dir: Path = C.OUT_DIR) -> tuple[Path, dict]:
    """One panel per (model, level) vocabulary in `lvs`."""
    plt = C.setup()
    models = sorted({lv.model for lv in lvs}, key=["complex", "transe"].index)
    levels = ["lambda", "cmm"]
    fig, axes = plt.subplots(len(models), 2, figsize=(13, 4.3 * len(models)), squeeze=False)
    results, tsv, caps = {}, [], []
    for lv in lvs:
        ev = evaluate(lv)
        results[(lv.level, lv.model)] = ev
        ax = axes[models.index(lv.model), levels.index(lv.level)]
        ax.hist(ev["null"], bins=80, color=C.CONTEXT, edgecolor=C.SURFACE, linewidth=0.3)
        ymax = ax.get_ylim()[1]
        ax.axvline(ev["p95"], color=C.INK2, linestyle=":", linewidth=1)
        ax.axvline(ev["p_corrected"], color=C.INK2, linestyle="--", linewidth=1)
        ax.annotate("95th", (ev["p95"], ymax * 0.97), fontsize=6, color=C.INK2, ha="right",
                    xytext=(-2, 0), textcoords="offset points")
        ax.annotate(f"{ev['corrected_percentile']:.2f}th\n(Bonferroni, k={ev['k']})",
                    (ev["p_corrected"], ymax * 0.97), fontsize=6, color=C.INK2, ha="left",
                    va="top", xytext=(2, 0), textcoords="offset points")
        lines = []
        for i, r in enumerate(ev["rows"], 1):
            if r["cosine"] is None:
                lines.append(f"{i}. {r['pair1']} vs {r['pair2']}: "
                             + r["verdict"].replace(": ", ":\n      ").replace("; ", ";\n      "))
                continue
            ax.axvline(r["cosine"], color=C.SERIES[0], linewidth=1.6)
            ax.annotate(str(i), (r["cosine"], ymax * (0.55 + 0.08 * (i % 4))), fontsize=8,
                        weight="bold", color=C.INK, ha="center",
                        bbox=dict(boxstyle="circle,pad=0.15", fc=C.SURFACE, ec=C.SERIES[0]))
            lines.append(f"{i}. {r['pair1']} vs {r['pair2']}: cos {r['cosine']:+.3f}, "
                         f"{r['percentile']:.1f}th pct → {r['verdict']}; "
                         f"category-matched null {r['matched_percentile']:.1f}th")
        ax.set_xlim(-1, 1)
        ax.set_xlabel("cos(b − a, d − c)")
        ax.set_ylabel(f"null count (of {NULL_DRAWS:,})")
        ax.set_title(f"{lv.level.capitalize()} · {lv.model} (α = {lv.alpha}): "
                     f"{ev['held']}/{ev['k']} testable analogies hold\n"
                     f"null mean {ev['mean']:+.3f}, std {ev['std']:.3f}", fontsize=9)
        ax.text(0.0, -0.3, "\n".join(lines), transform=ax.transAxes, fontsize=6.3, va="top",
                color=C.INK)
        caps.append(f"{lv.level}.{lv.model} {lv.sha[:12]}")
        for r in ev["rows"]:
            tsv.append([lv.level, lv.model, r["pair1"], r["pair2"],
                        "" if r["cosine"] is None else r["cosine"],
                        "" if r["percentile"] is None else r["percentile"],
                        "" if r["z"] is None else r["z"], r["verdict"],
                        "" if r["matched_percentile"] is None else r["matched_percentile"],
                        "" if r["cos_ac"] is None else r["cos_ac"],
                        "" if r["cos_bd"] is None else r["cos_bd"],
                        ev["mean"], ev["std"], ev["p95"], ev["p_corrected"]])
    fig.suptitle("Analogy test: offset consistency against a random-pair null "
                 f"({NULL_DRAWS:,} draws of 4 distinct entities, seed {SEED}); "
                 "a raw cosine is meaningless without the null", fontsize=10)
    fig.text(0.01, 0.005, "vocabularies: " + " · ".join(caps), fontsize=6, color=C.INK2)
    fig.tight_layout(rect=(0, 0.02, 1, 0.96), h_pad=7)
    base = out_dir / "analogy"
    C.save(fig, base)
    C.write_tsv(base.with_suffix(".tsv"),
                ["level", "model", "pair1", "pair2", "cosine", "percentile", "z", "verdict",
                 "matched_null_percentile", "cos_a_c", "cos_b_d",
                 "null_mean", "null_std", "null_p95", "null_p_bonferroni"], tsv,
                [f"null: {NULL_DRAWS} random quadruples of distinct entities, "
                 f"numpy default_rng({SEED}); percentile = % of null strictly below (ties half)",
                 "decision: holds if cosine > Bonferroni percentile 100(1 - 0.05/k); "
                 "k = testable quadruples per level",
                 f"matched null: {MATCHED_DRAWS} draws, each position from the tested entity's "
                 "category (secondary control, not the decision rule)"])
    return base, results
