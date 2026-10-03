"""Phase 6 acceptance: `ir2vec embed` on new programs (needs the ir2vec switch)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ir2vec import cli, config as cfgmod, embed as em, inventory
from ir2vec.align import align

REPO = inventory.REPO
VL, VC = REPO / "vocab" / "lambda.complex.json", REPO / "vocab" / "cmm.complex.json"
GOLDEN = REPO / "tests" / "golden"
DIMS = {"lambda_sym": 128, "cmm_fa": 128, "counts_lambda": 95, "counts_cmm": 83,
        "node_counts": 4, "final": 438}


@pytest.fixture(scope="module")
def cfg():
    return cfgmod.VocabConfig.load()


def functions(res):
    return [f for u in res["units"] for f in u["functions"]]


def test_align_ml_all_aligned(cfg):
    res = em.embed(REPO / "tests" / "fixtures" / "align.ml", VL, VC, cfg)
    assert res["metadata"]["dims"] == DIMS
    fs = functions(res)
    assert len(fs) == 5 and all(f["aligned"] for f in fs)
    kinds = sorted(f["lambda_kind"] for f in fs)
    assert kinds == ["anonymous", "module_init", "named", "named", "named"]
    anon = next(f for f in fs if f["lambda_kind"] == "anonymous")
    assert anon["aligned_by"] == "location" and anon["cmm_name"].endswith(".fun_368")
    init = next(f for f in fs if f["lambda_kind"] == "module_init")
    assert init["cmm_name"] == "camlAlign.entry"
    assert em.unknown_total(res) == 0
    for f in fs:
        assert len(f["final"]) == 438 and len(f["counts_lambda"]) == 95
        assert len(f["counts_cmm"]) == 83 and len(f["node_counts"]) == 4
        assert np.isclose(np.linalg.norm(f["final"][:128]), 1.0)          # L2(lambda_sym)
        assert np.isclose(np.linalg.norm(f["final"][128:256]), 1.0)       # L2(cmm_fa)
    assert len(res["units"][0]["module"]["final"]) == 438


FRESH = """
type shape = Circle of float | Rect of float * float
type account = { owner : string; mutable balance : float }
exception Insufficient of float

let area = function Circle r -> 3.14159 *. r *. r | Rect (w, h) -> w *. h
let withdraw acct amt =
  if amt > acct.balance then raise (Insufficient (amt -. acct.balance));
  acct.balance <- acct.balance -. amt
let total shapes = Array.fold_left (fun s x -> s +. area x) 0. shapes
let histogram xs =
  let h = Array.make 10 0 in
  List.iter (fun x -> let i = min 9 (max 0 (int_of_float x)) in h.(i) <- h.(i) + 1) xs;
  h
let rec gcd a b = if b = 0 then a else gcd b (a mod b)
let safe f x = try Some (f x) with Insufficient _ | Division_by_zero -> None
let describe s = let b = Buffer.create 16 in
  String.iter (fun c -> Buffer.add_string b (if c = ' ' then "_" else String.make 1 c)) s;
  Buffer.contents b
"""


def test_fresh_file_outside_the_corpus(tmp_path: Path, cfg):
    src = tmp_path / "fresh_program.ml"
    src.write_text(FRESH)
    res = em.embed(src, VL, VC, cfg)
    assert em.unknown_total(res) == 0
    a = res["alignment"]
    assert a["lambda_functions"] >= 9 and a["matched"] == a["lambda_functions"]
    assert all(np.isfinite(f["final"]).all() for f in functions(res))


def test_single_file_with_ocamlfind_package(tmp_path: Path, cfg):
    src = tmp_path / "uses_str.ml"
    src.write_text('let words s = Str.split (Str.regexp " +") s\nlet n s = List.length (words s)\n')
    res = em.embed(src, VL, VC, cfg, em.EmbedOptions(packages=["str"]))
    assert em.unknown_total(res) == 0 and res["alignment"]["matched"] >= 3


def test_dune_project_with_opam_dependency(cfg):
    res = em.embed(REPO / "tests" / "embed_project", VL, VC, cfg,
                   em.EmbedOptions(install_deps=True))
    units = {u["unit"] for u in res["units"]}
    assert "Wordcount" in units and any(u.endswith("Main") for u in units)
    a = res["alignment"]
    assert a["matched"] == a["lambda_functions"] and em.unknown_total(res) == 0
    # the library's calls into Re are visible as cross-module calls
    wc = next(u for u in res["units"] if u["unit"] == "Wordcount")
    words = next(f for f in wc["functions"] if f["lambda_name"] == "words")
    names = res["metadata"]["count_features"]["lambda"]
    assert words["counts_lambda"][names.index("CALL_MODULE")] + \
        words["counts_lambda"][names.index("CALL_STDLIB")] > 0


def test_npy_output(tmp_path: Path, cfg):
    res = em.embed(REPO / "tests" / "fixtures" / "align.ml", VL, VC, cfg)
    em.write_npy(res, tmp_path / "out")
    f = np.load(tmp_path / "out" / "functions.npy")
    m = np.load(tmp_path / "out" / "modules.npy")
    idx = json.loads((tmp_path / "out" / "index.json").read_text())
    assert f.shape == (5, 438) and m.shape == (1, 438) and len(idx["functions"]) == 5


def test_unknown_entity_exits_nonzero(tmp_path: Path):
    vocab = json.loads(VL.read_text())
    del vocab["entities"]["Pmulint"]
    bad = tmp_path / "lambda.missing.json"
    bad.write_text(json.dumps(vocab))
    src = str(REPO / "tests" / "fixtures" / "align.ml")
    args = ["embed", src, "--vocab-lambda", str(bad), "-o", str(tmp_path / "o.json")]
    assert cli.main(args) == 1
    assert cli.main(args + ["--allow-unknown"]) == 0
    out = json.loads((tmp_path / "o.json").read_text())
    # one lookup per Lambda cell (lambda_sym, lambda_fa)
    assert out["lookup"]["lambda"]["unknown"] == {"Pmulint": 2}


def test_count_vector_buckets_unlisted_externs():
    names = ["MUT", "EXT:caml_modify", "EXT_OTHER"]
    v = em.count_vector({"MUT": 2, "EXT:caml_modify": 1, "EXT:my_stub": 3}, names)
    assert list(v) == [2, 1, 3]
    with pytest.raises(em.EmbedError):
        em.count_vector({"NOT_A_FEATURE": 1}, names)


def test_embed_units_is_deterministic(cfg):
    units = [(json.loads((GOLDEN / f"{n}.lambda.json").read_text()),
              json.loads((GOLDEN / f"{n}.cmm.json").read_text())) for n in ("closures", "exn")]
    a = json.dumps(em.embed_units(units, VL, VC, cfg))
    b = json.dumps(em.embed_units(units, VL, VC, cfg))
    assert a == b


# --------------------------------------------------------------- alignment ---

def _lam(recs):
    return {"unit": "U", "functions": recs}


def _rec(fid, kind, stamp=None, loc=None, params=()):
    return {"fid": fid, "name": fid.split("/")[0], "kind": kind, "stamp": stamp, "loc": loc,
            "params": [{"name": "p", "stamp": s, "type": "GEN"} for s in params]}


def _fn(name, loc=None, params=()):
    return {"name": name, "loc": loc, "params": [{"var": f"p/{s}", "type": "VAL"} for s in params]}


def test_alignment_fallbacks_and_ambiguity():
    L1 = {"file": "a.ml", "l1": 1, "c1": 0, "l2": 1, "c2": 9}
    L2 = {"file": "a.ml", "l1": 2, "c1": 0, "l2": 2, "c2": 9}
    lam = _lam([_rec("module_init", "module_init"),
                _rec("f/10", "named", 10),
                _rec("anon/0", "anonymous", loc=L1, params=[20]),
                _rec("anon/1", "anonymous", loc=None, params=[30]),     # params fallback
                _rec("anon/2", "anonymous", loc=L2, params=[40]),     # ambiguous location
                _rec("g/50", "named", 50)])                            # inlined away
    cmm = {"functions": [_fn("camlU.entry"), _fn("camlU.f_10"),
                         _fn("camlU.fun_91", L1, [20]), _fn("camlU.fun_92", None, [30, 99]),
                         _fn("camlU.fun_93", L2, [41]), _fn("camlU.fun_94", L2, [42]),
                         _fn("camlU.f_inner_95")]}
    a = align(lam, cmm)
    by = {m.fid: (m.cmm, m.by) for m in a.matches}
    assert by["module_init"] == ("camlU.entry", "entry")
    assert by["f/10"] == ("camlU.f_10", "stamp")
    assert by["anon/0"] == ("camlU.fun_91", "location")
    assert by["anon/1"] == ("camlU.fun_92", "params")
    assert a.unmatched_lambda == {"named": ["g/50"], "anonymous": ["anon/2"], "module_init": []}
    assert a.cmm_only == ["camlU.f_inner_95", "camlU.fun_93", "camlU.fun_94"]


def test_packed_units_align_entry():
    lam = _lam([_rec("module_init", "module_init"), _rec("eval/281", "named", 281)])
    cmm = {"functions": [_fn("camlOcamlbuild_pack.Bool.entry"),
                         _fn("camlOcamlbuild_pack.Bool.eval_281")]}
    a = align(lam, cmm)
    assert len(a.matches) == 2 and not a.cmm_only


def test_cmm_parents_unique_referrer_or_none():
    from ir2vec.align import cmm_parents

    def fn(name, syms=()):
        return {"name": name, "blocks": [{"id": 0, "instrs": [
            {"operands": [{"kind": "SYM_FUNC", "sym": s} for s in syms]}]}]}
    cmm = {"functions": [fn("camlU.f_1", ["camlU.fun_9", "camlU.f_inner_8"]),
                         fn("camlU.f_inner_8"), fn("camlU.fun_9", ["camlU.fun_9"]),
                         fn("camlU.g_2", ["camlU.fun_7"]), fn("camlU.h_3", ["camlU.fun_7"]),
                         fn("camlU.fun_7"), fn("camlU.fun_6")]}
    p = cmm_parents(cmm)
    assert p["camlU.fun_9"] == "camlU.f_1"          # self-reference ignored
    assert p["camlU.f_inner_8"] == "camlU.f_1"      # wrapper -> inner
    assert p["camlU.fun_7"] is None                 # two referrers: not guessed
    assert p["camlU.fun_6"] is None                 # no referrer (e.g. static closure)
