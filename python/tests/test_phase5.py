"""Phase 5 acceptance: encoders on the extracted fixtures (tests/golden)."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from ir2vec import config as cfgmod, inventory
from ir2vec.encode import cmm_enc, engine, lambda_enc
from ir2vec.encode.cells import encode_cells, unknown_total
from ir2vec.encode.vocab import ImpossibleEntity, Vocabulary, Weights

GOLDEN = inventory.REPO / "tests" / "golden"
VOCAB = inventory.REPO / "vocab"
FIXTURES = ["align", "closures", "counter", "effects", "evenodd", "exn", "fact", "pq"]
MODELS = ["complex", "transe"]


@pytest.fixture(scope="module")
def cfg():
    return cfgmod.VocabConfig.load()


def unit(name, level):
    return json.loads((GOLDEN / f"{name}.{level}.json").read_text())


def vocab(level, model, cfg):
    return Vocabulary.load(VOCAB / f"{level}.{model}.json", cfg)


def by_key(fvs, key):
    (fv,) = [f for f in fvs if key(f)]
    return fv


W = Weights.load()


def test_weights_are_the_spec_defaults():
    assert (W.Wo, W.Wt, W.Wa, W.Wc) == (1.0, 0.5, 0.2, 0.2)


# ------------------------------------------------------------------ pq.ml ---

@pytest.mark.parametrize("model", MODELS)
def test_pq_lambda_sym_differs_only_by_the_let_node(model, cfg):
    """p = (x+y)*(x-y); q = let a = x+y in (a-y)*a. Under lambda_sym every
    operand is VAR_INT either way, so q - p is exactly q's Llet node (schema
    §1.8 sums every node; D5.6)."""
    v, u = vocab("lambda", model, cfg), unit("pq", "lambda")
    fvs = lambda_enc.lambda_sym(u, v, W)
    p = by_key(fvs, lambda f: f.name == "p").vector
    q = by_key(fvs, lambda f: f.name == "q").vector
    qrec = next(f for f in u["functions"] if f["name"] == "q")
    let = next(n for n in qrec["nodes"] if n["op"] == "Llet")
    let_vec = W.Wo * v("Llet") + W.Wt * v(let["type"]) + W.Wa * v(let["positions"][0]["kind"])
    assert np.allclose(q - p, let_vec, atol=1e-12)


@pytest.mark.parametrize("model", MODELS)
def test_pq_distinct_under_flow_aware(model, cfg):
    vl, vc = vocab("lambda", model, cfg), vocab("cmm", model, cfg)
    lu, cu = unit("pq", "lambda"), unit("pq", "cmm")
    sym = lambda_enc.lambda_sym(lu, vl, W)
    fa = lambda_enc.lambda_fa(lu, vl, W)
    get = lambda fvs, n: by_key(fvs, lambda f: f.name == n).vector  # noqa: E731
    # beyond the Llet node: FA makes q's uses of `a` carry Paddint's vector
    assert not np.allclose(get(fa, "q") - get(fa, "p"), get(sym, "q") - get(sym, "p"))
    cfa = cmm_enc.cmm_fa(cu, vc, W)
    cget = lambda fvs, n: by_key(fvs, lambda f: f.name.split(".")[-1].startswith(n + "_")).vector  # noqa: E731
    assert np.linalg.norm(cget(cfa, "q") - cget(cfa, "p")) > 1e-6


# ------------------------------------------------------------ counter.ml ---

@pytest.mark.parametrize("model", MODELS)
def test_counter_loop_is_a_cyclic_scc_solved_exactly(model, cfg):
    v, u = vocab("cmm", model, cfg), unit("counter", "cmm")
    f = next(f for f in u["functions"] if "count" in f["name"])
    system, _ = cmm_enc._system(f, v, W, flow=True, count_synthetic=False)
    X, stats = engine.solve(system, W.Wa)
    assert stats.cyclic_sccs >= 1 and not stats.retries
    assert engine.residual(system, X) < 1e-9


# ------------------------------------------------------------ evenodd.ml ---

@pytest.mark.parametrize("model", MODELS)
def test_evenodd_pass2_terminates_and_is_finite(model, cfg):
    fvs = cmm_enc.cmm_fa(unit("evenodd", "cmm"), vocab("cmm", model, cfg), W)
    for fv in fvs:
        assert np.isfinite(fv.vector).all()
    short = lambda f: f.name.split(".")[-1]  # noqa: E731
    even = by_key(fvs, lambda f: short(f).startswith("even_"))
    odd = by_key(fvs, lambda f: short(f).startswith("odd_"))
    assert any(".odd_" in c for c in even.direct_calls)
    assert any(".even_" in c for c in odd.direct_calls)
    assert np.allclose(even.vector, even.pass1 + W.Wc * sum(
        by_key(fvs, lambda f, c=c: f.name == c).pass1 for c in even.direct_calls))


# ------------------------------------------------------------ fa == sym ---

@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("fixture,name", [("fact", "fact"), ("pq", "p")])
def test_lambda_fa_equals_sym_without_definitions(model, fixture, name, cfg):
    v, u = vocab("lambda", model, cfg), unit(fixture, "lambda")
    rec = next(f for f in u["functions"] if f["name"] == name)
    assert not any(p.get("def") for n in rec["nodes"] for p in n["positions"])
    s = by_key(lambda_enc.lambda_sym(u, v, W), lambda f: f.name == name).vector
    a = by_key(lambda_enc.lambda_fa(u, v, W), lambda f: f.name == name).vector
    assert np.array_equal(s, a)


# ------------------------------------------------- fixtures, determinism ---

@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("fixture", FIXTURES)
def test_fixtures_have_no_unknown_entities(model, fixture, cfg):
    res = encode_cells(unit(fixture, "lambda"), unit(fixture, "cmm"),
                       VOCAB / f"lambda.{model}.json", VOCAB / f"cmm.{model}.json", cfg)
    assert unknown_total(res) == 0, res["lookup"]
    assert set(res["cells"]) == {"lambda_sym", "lambda_fa", "cmm_sym", "cmm_fa"}


def test_two_runs_are_byte_identical(cfg):
    runs = [json.dumps(encode_cells(unit("counter", "lambda"), unit("counter", "cmm"),
                                    VOCAB / "lambda.complex.json", VOCAB / "cmm.complex.json",
                                    cfg), sort_keys=True) for _ in range(2)]
    assert runs[0] == runs[1]


# ----------------------------------------------------- lookup rules (D5.4) ---

def test_fallback_is_lookup_only_and_counted(cfg):
    v = vocab("cmm", "complex", cfg)
    assert "Cload_single" in v.fallback
    assert np.array_equal(v("Cload_single"), v("Cload_double"))
    assert v.fallbacks_used["Cload_single"] == 1 and not v.unknown


def test_impossible_entity_is_a_hard_error(cfg):
    with pytest.raises(ImpossibleEntity):
        vocab("cmm", "complex", cfg)("RETURN_ADDR")
    with pytest.raises(ImpossibleEntity):
        vocab("lambda", "complex", cfg)("Psetglobal")


def test_unknown_entity_is_counted_not_silent(cfg):
    v = vocab("cmm", "complex", cfg)
    assert not v("NOT_AN_ENTITY").any() and v.unknown["NOT_AN_ENTITY"] == 1


# ------------------------------------- synthetic COPY, liveness, engine ---

def _i(iid, op, dst=None, ops=(), ty=None, term=False, se=False, syn=False):
    d = {"id": iid, "op": op, "type": ty, "dst": dst,
         "operands": [{"kind": "VAR_INT", "var": o} if not o.startswith("CONST")
                      else {"kind": o} for o in ops],
         "side_effect": se, "terminator": term}
    if syn:
        d["synthetic"] = True
    return d


# if c then j = x + 1 else j = x + 2; return j  -- arms define j through synthetic COPYs
JOIN = {"name": "f", "params": [{"var": "x", "type": "INT"}, {"var": "c", "type": "INT"}],
        "mutable_vars": [], "join_vars": ["j"], "handler_params": [],
        "blocks": [
            {"id": 0, "instrs": [_i(0, "BR", ops=["c"], term=True)], "succ": [1, 2], "exn_succ": []},
            {"id": 1, "instrs": [_i(1, "Caddi", "t1", ["x", "CONST_INT"], "INT"),
                                 _i(2, "COPY", "j", ["t1"], "INT", syn=True),
                                 _i(3, "JUMP", term=True, syn=True)], "succ": [3], "exn_succ": []},
            {"id": 2, "instrs": [_i(4, "Caddi", "t2", ["x", "CONST_INT"], "INT"),
                                 _i(5, "COPY", "j", ["t2"], "INT", syn=True),
                                 _i(6, "JUMP", term=True, syn=True)], "succ": [3], "exn_succ": []},
            {"id": 3, "instrs": [_i(7, "Csubi", "dead", ["x", "x"], "INT"),
                                 _i(8, "RET", ops=["j"], term=True)], "succ": [], "exn_succ": []},
        ]}


def test_join_through_synthetic_copies_sums_the_arms(cfg):
    v = vocab("cmm", "complex", cfg)
    system, instrs = cmm_enc._system(JOIN, v, W, flow=True, count_synthetic=False)
    X, _ = engine.solve(system, W.Wa)
    x = {i["id"]: X[k] for k, i in enumerate(instrs)}
    assert np.allclose(x[2], x[1]) and np.allclose(x[5], x[4])      # COPY = its operand
    ret = W.Wo * v("RET") + W.Wa * (x[1] + x[4])                    # use at the join
    assert np.allclose(x[8], ret)


def test_liveness_counts_terminators_and_drops_dead_pure_code():
    live = cmm_enc.live_instructions(JOIN)
    assert {0, 3, 6, 8} <= live                                     # terminators
    assert {1, 2, 4, 5} <= live                                     # feed the returned j
    assert 7 not in live                                            # dead pure Csubi


def test_synthetic_copies_are_excluded_from_sums(cfg):
    v = vocab("cmm", "complex", cfg)
    (fv,) = cmm_enc.cmm_fa({"functions": [JOIN]}, v, W)
    assert fv.n_counted == 6            # 9 - dead Csubi - 2 synthetic COPYs
    (fv_all,) = cmm_enc.cmm_fa({"functions": [JOIN]}, v, W, count_synthetic=True)
    assert fv_all.n_counted == 8 and not np.allclose(fv.vector, fv_all.vector)


def test_tarjan_components_come_dependencies_first():
    deps = [[(1, 1, True)], [(2, 1, True)], [(1, 1, True)], [(0, 1, True)]]
    comps = engine.sccs(deps)
    assert comps == [[1, 2], [0], [3]]
