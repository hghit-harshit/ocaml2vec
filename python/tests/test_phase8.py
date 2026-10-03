"""Phase 8: visualisation and geometry evidence."""

from __future__ import annotations

import numpy as np
import pytest

from ir2vec import categories, config as cfgmod, inventory

pytest.importorskip("matplotlib")

from ir2vec.figures import analogy, bars, common as C, functions, heatmap, neighbours, probe  # noqa: E402


def test_category_map_covers_every_entity_exactly_once():
    cats = categories.load()                     # raises on a duplicate
    cfg = cfgmod.VocabConfig.load()
    inv = inventory.load()
    assert categories.problems(cats, inv, cfg.trained) == []
    for level in ("lambda", "cmm"):
        assert set(cfg.trained[level]) <= set(cats.of[level])
    assert len(cats.order["lambda"]) == 15 and len(cats.order["cmm"]) == 12


def test_unused_status_matches_the_frozen_merges():
    cats, cfg, inv = categories.load(), cfgmod.VocabConfig.load(), inventory.load()
    for level in ("lambda", "cmm"):
        marked = {e for e, s in cats.status[level].items() if s.startswith("unused")}
        assert marked == categories.unused_families(inv, level, cfg.merges[level])
    assert categories.unused_families(inv, "cmm", cfg.merges["cmm"]) == {"Cload_narrow"}


@pytest.fixture(scope="module")
def lvs():
    cfg = cfgmod.VocabConfig.load()
    return {(lvl, m): C.load_level(lvl, C.vocab_path(lvl, m), cfg)
            for lvl in ("lambda", "cmm") for m in ("complex", "transe")}


# ------------------------------------------------------------ honesty rules ---

def test_fallback_and_impossible_entities_are_never_plotted_but_listed(lvs):
    cfg = cfgmod.VocabConfig.load()
    for (lvl, _m), lv in lvs.items():
        status = dict(lv.excluded)
        for e, target in cfg.fallback_map[lvl].items():
            assert e not in lv.names and status[e] == f"fallback -> {target}"
        for e in cfg.impossible[lvl]:
            assert e not in lv.names and status[e] == "impossible"
    assert "4 fallback-mapped, 1 impossible" in lvs["lambda", "complex"].caption()
    assert "5 fallback-mapped, 1 impossible" in lvs["cmm", "complex"].caption()


def test_pca_sign_convention_is_fixed():
    X = np.random.default_rng(0).normal(size=(40, 12))
    Y1, r1 = C.pca2(X)
    Y2, r2 = C.pca2(-X)          # same subspace, opposite raw SVD signs
    assert np.allclose(Y1, -Y2) and np.allclose(r1, r2)
    Y3, _ = C.pca2(X.copy())
    assert np.array_equal(Y1, Y3)


def test_figures_are_byte_identical_on_regeneration(lvs, tmp_path):
    lv = lvs["cmm", "complex"]
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
        heatmap.draw(lv, d)
        t, g, ctx = __import__("ir2vec.figures.seeds", fromlist=["panels"]).panels(lv)[3]
        __import__("ir2vec.figures.seeds", fromlist=["draw_panel"]).draw_panel(lv, t, g, ctx, d)
    files = sorted(a.glob("*.svg")) + sorted(a.glob("*.png"))
    assert len(files) == 4
    for f in files:
        assert f.read_bytes() == (b / f.name).read_bytes(), f.name
    # no timestamp and no version string (explicit metadata, D8.3)
    png = next(a.glob("*.png")).read_bytes()
    assert b"Software" not in png and b"Creation" not in png
    svg = next(a.glob("*.svg")).read_text()
    assert "<dc:date>" not in svg and "matplotlib.org" not in svg


def test_heatmap_tsv_is_symmetric_with_unit_diagonal_and_order(lvs, tmp_path):
    lv = lvs["lambda", "complex"]
    base = heatmap.draw(lv, tmp_path)
    lines = [ln for ln in base.with_suffix(".tsv").read_text().splitlines()
             if not ln.startswith("#")]
    header = lines[0].split("\t")
    names = [ln.split("\t")[0] for ln in lines[1:]]
    assert header[2:] == names == heatmap.ordered(lv)
    S = np.array([[float(x) for x in ln.split("\t")[2:]] for ln in lines[1:]])
    assert np.allclose(S, S.T, atol=1e-6) and np.allclose(np.diag(S), 1.0)
    order = categories.load().order["lambda"]
    ranks = [order.index(lv.category[n]) for n in names]
    assert ranks == sorted(ranks)


def test_distinctness_bars_reproduce_the_phase7_table():
    phase7 = {("lambda", "complex"): {"Lapply_a*": 0.516, "Lfunction_a*": 0.341,
                                      "Pgetglobal_*": 0.262, "operand_kinds": 0.633,
                                      "types": 0.645},
              ("cmm", "transe"): {"Cload_*": 0.913, "Cstore_*": 0.924,
                                  "operand_kinds": 0.830, "types": 0.896}}
    for (lvl, m), want in phase7.items():
        _meta, got = bars.scores(C.vocab_path(lvl, m))
        assert {g: round(v, 3) for g, v in got.items()} == want


# ------------------------------------------------------------------ §8.4/5 ---

def test_neighbours_come_only_from_plotted_entities(lvs):
    lv = lvs["cmm", "complex"]
    nn = neighbours.top_k(lv)
    assert set(nn) == set(lv.names)
    assert all(len(v) == neighbours.K and all(m in lv.names and m != q for m, _ in v)
               for q, v in nn.items())
    assert nn == neighbours.top_k(lv)


def test_analogy_null_is_seeded_and_centred(lvs):
    lv = lvs["lambda", "complex"]
    n1, n2 = analogy.null_distribution(lv.vecs), analogy.null_distribution(lv.vecs)
    assert len(n1) == analogy.NULL_DRAWS and np.array_equal(n1, n2)
    assert abs(n1.mean()) < 0.02
    assert analogy.percentile(np.array([0.0, 1.0, 2.0, 3.0]), 2.0) == 62.5


def test_matched_null_percentile_is_reported_for_every_testable_quadruple(lvs):
    # D8.5 ruling: a required diagnostic column, not part of the verdict
    for key in (("lambda", "complex"), ("cmm", "transe")):
        for r in analogy.evaluate(lvs[key])["rows"]:
            if r["cosine"] is not None:
                assert 0.0 <= r["matched_percentile"] <= 100.0
                assert r["verdict"] in ("holds", "does not hold") or r["verdict"].startswith("above 95th")


def test_analogy_with_a_fallback_entity_is_untestable(lvs):
    ev = analogy.evaluate(lvs["cmm", "complex"])
    row = next(r for r in ev["rows"] if "Cload_byte_s" in r["pair2"] or "Cload_byte_s" in r["pair1"])
    assert row["cosine"] is None and row["verdict"].startswith("untestable")
    assert ev["k"] == 2


# ------------------------------------------------------------------ §8.6/7 ---

def test_auc_matches_pair_counting():
    rng = np.random.default_rng(1)
    y = rng.random(60) < 0.4
    s = np.round(rng.random(60), 1)             # ties on purpose
    pos, neg = s[y], s[~y]
    brute = np.mean([(p > q) + 0.5 * (p == q) for p in pos for q in neg])
    assert probe.auc(y, s) == pytest.approx(brute)


def test_probe_decodes_a_linear_signal_and_not_shuffled_labels():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(3000, 256))
    y = X[:, 3] + 0.5 * rng.normal(size=3000) > 0
    keys = np.array([f"k{i}" for i in range(3000)])
    assert probe.cross_validate(X, y, keys)["auc_mean"] > 0.85
    ys = np.random.default_rng(3).permutation(y)
    assert abs(probe.cross_validate(X, ys, keys)["auc_mean"] - 0.5) < 0.1


def test_function_figures_refuse_anything_but_the_256_learned_dimensions():
    d = {"X": np.zeros((5, 438)), "keys": np.array(list("abcde")), "meta": "{}"}
    with pytest.raises(AssertionError, match="learned"):
        functions.draw(d)
    with pytest.raises(AssertionError, match="learned"):
        probe.run(d)


def test_function_sample_is_a_deterministic_hash_rule():
    keys = np.array([f"pkg/unit/f{i}" for i in range(10_000)])
    m1, k1 = functions.sample_mask(keys, 1000)
    m2, _ = functions.sample_mask(keys[::-1], 1000)
    assert k1 == 10 and np.array_equal(m1, m2[::-1]) and 700 < m1.sum() < 1300
