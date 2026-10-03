"""Phase 3 acceptance: golden triples, entity counts, config, plateau."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from ir2vec import config as cfgmod
from ir2vec import inventory, metrics, stats, triples
from ir2vec import select as selmod
from ir2vec.corpus import Corpus, FileCorpus

GOLDEN = inventory.REPO / "tests" / "golden"


def load(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text())


def tsv(ts) -> str:
    return "".join(f"{h}\t{r}\t{t}\n" for h, r, t in ts)


# ------------------------------------------------------------ inventory ---

def test_entity_counts_match_decisions():
    inv = inventory.load()
    assert len(inv.lambda_.entities) == 148      # schema 151 before D0.15
    assert len(inv.cmm.entities) == 77           # schema 78 before D0.15
    assert inv.lambda_.n_count_features == 95    # 87 + signature block (D1.12)
    assert inv.cmm.n_count_features == 83        # 81 + LOAD_ATOMIC/NONATOMIC (D0.16)
    assert len(inv.lambda_.relations) == 12 and len(inv.cmm.relations) == 8


# --------------------------------------------------------- golden fact ---

# Schema §1.9: the triples of `fact` (its Lfunction node is owned by
# module_init's stub, D1.3).
SCHEMA_1_9 = Counter([
    ("Lfunction_a1", "Type", "INT"), ("Lfunction_a1", "Child0", "Lifthenelse"),
    ("Lifthenelse", "Child0", "Pintcomp"), ("Lifthenelse", "Arg1", "CONST_INT"),
    ("Lifthenelse", "Child2", "Pmulint"), ("Pintcomp", "Type", "INT"),
    ("Pintcomp", "Arg0", "VAR_INT"), ("Pintcomp", "Arg1", "CONST_INT"),
    ("Pmulint", "Type", "INT"), ("Pmulint", "Arg0", "VAR_INT"),
    ("Pmulint", "Child1", "Lapply_a1"), ("Lapply_a1", "Child0", "Psubint"),
    ("Psubint", "Type", "INT"), ("Psubint", "Arg0", "VAR_INT"),
    ("Psubint", "Arg1", "CONST_INT"),
])

# Schema §2.9, complete, for OCaml 5.5.1: `n` has machtype int (D2.4), so its
# uses are VAR_INT; right-to-left lowering order (D2.2).
SCHEMA_2_9 = Counter([
    ("Ccmpi", "Type", "INT"), ("Ccmpi", "Arg0", "VAR_INT"), ("Ccmpi", "Arg1", "CONST_INT"),
    ("Ccmpi", "Next", "BR"),
    ("BR", "Arg0", "VAR_INT"), ("BR", "Succ", "RET"), ("BR", "Succ", "Caddi"),
    ("RET", "Arg0", "CONST_INT"),
    ("Caddi", "Type", "INT"), ("Caddi", "Arg0", "VAR_INT"), ("Caddi", "Arg1", "CONST_INT"),
    ("Caddi", "Next", "Capply"),
    ("Capply", "Type", "VAL"), ("Capply", "Arg0", "SYM_FUNC"), ("Capply", "Arg1", "VAR_INT"),
    ("Capply", "Next", "Casr"),
    ("Casr", "Type", "INT"), ("Casr", "Arg0", "VAR_VAL"), ("Casr", "Arg1", "CONST_INT"),
    ("Casr", "Next", "Caddi"),
    ("Caddi", "Type", "INT"), ("Caddi", "Arg0", "VAR_INT"), ("Caddi", "Arg1", "CONST_INT"),
    ("Caddi", "Next", "Cmuli"),
    ("Cmuli", "Type", "INT"), ("Cmuli", "Arg0", "VAR_INT"), ("Cmuli", "Arg1", "VAR_INT"),
    ("Cmuli", "Next", "Caddi"),
    ("Caddi", "Type", "INT"), ("Caddi", "Arg0", "VAR_INT"), ("Caddi", "Arg1", "CONST_INT"),
    ("Caddi", "Next", "RET"),
    ("RET", "Arg0", "VAR_INT"),
])


def fact_lambda_triples() -> Counter:
    unit = load("fact.lambda.json")
    fact = next(f for f in unit["functions"] if f["name"] == "fact")
    init = next(f for f in unit["functions"] if f["kind"] == "module_init")
    stub = next(n for n in init["nodes"] if n.get("func") == fact["fid"])
    only = {"functions": [dict(init, nodes=[stub], cases={}), fact]}
    return Counter(triples.lambda_triples(only, {}))


def test_lambda_triples_match_schema_1_9():
    assert fact_lambda_triples() == SCHEMA_1_9


def test_cmm_triples_match_schema_2_9():
    unit = load("fact.cmm.json")
    fact = next(f for f in unit["functions"] if f["name"].endswith("fact_274"))
    got = Counter(triples.cmm_triples({"functions": [fact]}, {}, count_synthetic=False))
    assert got == SCHEMA_2_9


@pytest.mark.parametrize("level", ["lambda", "cmm"])
def test_golden_triples_snapshot(level):
    unit = load(f"fact.{level}.json")
    got = tsv(triples.unit_triples(level, unit, {}, count_synthetic=False))
    assert got == (GOLDEN / f"fact.{level}.triples.tsv").read_text()


def test_golden_units_have_no_unknown_entities():
    inv = inventory.load()
    for name in ("fact.lambda.json", "align.lambda.json", "fact.cmm.json"):
        level = name.split(".")[1]
        lv = inv.level(level)
        s = triples.TripleSummary(level)
        for t in triples.unit_triples(level, load(name), {}, False):
            s.add(t, set(lv.entities), set(lv.relations))
        assert not s.unknown, (name, s.unknown)


# ----------------------------------------------------- ownership / skips ---

def test_nested_function_node_counted_once():
    unit = load("align.lambda.json")
    n_funcs = sum(1 for f in unit["functions"] if f["kind"] != "module_init")
    ts = list(triples.lambda_triples(unit, {}))
    fn_types = [t for t in ts if t[0].startswith("Lfunction_") and t[1] == "Type"]
    fn_child0 = [t for t in ts if t[0].startswith("Lfunction_") and t[1] == "Child0"]
    assert len(fn_types) == n_funcs and len(fn_child0) == n_funcs


def _instr(op, synthetic=False, term=False, ty=None):
    return {"op": op, "type": ty, "dst": None, "operands": [{"kind": "CONST_INT"}],
            "side_effect": False, "terminator": term, **({"synthetic": True} if synthetic else {})}


SYNTH_UNIT = {"functions": [{"blocks": [
    {"id": 0, "instrs": [_instr("Caddi", ty="INT"), _instr("COPY", synthetic=True, ty="INT"),
                         _instr("JUMP", synthetic=True, term=True)], "succ": [1], "exn_succ": []},
    {"id": 1, "instrs": [_instr("COPY", synthetic=True), _instr("RET", term=True)],
     "succ": [], "exn_succ": []},
]}]}


def test_synthetic_copy_skipped_and_bridged():
    ts = list(triples.cmm_triples(SYNTH_UNIT, {}, count_synthetic=False))
    assert not any("COPY" in (h, t) for h, _r, t in ts)
    assert ("Caddi", "Next", "JUMP") in ts          # bridges over the COPY
    assert ("JUMP", "Succ", "RET") in ts            # synthetic JUMP is real
    ts_all = list(triples.cmm_triples(SYNTH_UNIT, {}, count_synthetic=True))
    assert ("Caddi", "Next", "COPY") in ts_all and ("JUMP", "Succ", "COPY") in ts_all


def test_merges_rename_heads_and_tails():
    unit = {"functions": [{"blocks": [{"id": 0, "instrs": [
        _instr("Cload_16u", ty="INT"), _instr("Cpoll"), _instr("RET", term=True)],
        "succ": [], "exn_succ": []}]}]}
    merge = {"Cload_16u": "Cload_narrow", "Cpoll": "C_RUNTIME"}
    ts = list(triples.cmm_triples(unit, merge, False))
    assert ("Cload_narrow", "Next", "C_RUNTIME") in ts
    assert not any(e in ("Cload_16u", "Cpoll") for t in ts for e in (t[0], t[2]))


# --------------------------------------------------------------- config ---

def test_whitelist_pins_then_package_frequency():
    pkgs = Counter({f"caml_f{i}": 3 + (i % 5) for i in range(100)})
    pkgs.update({"dune_private": 1, "caml_modify": 1})
    count = Counter({n: 1000 - i for i, n in enumerate(sorted(pkgs))})
    count["dune_private"] = 10**6                   # frequent but one package
    pins = cfgmod.resolve_pins(cfgmod.PINNED_EXTERNS,
                               set(pkgs) | {"caml_atomic_cas_field", "caml_atomic_exchange"})
    assert pins["caml_atomic_cas_field"].endswith("(D0.17)")
    wl = cfgmod.build_whitelist(list(pins), pkgs, count)
    assert len(wl) == 64 and wl[:len(pins)] == list(pins)
    assert "dune_private" not in wl                 # < 3 packages, not pinned
    rest = wl[len(pins):]
    assert [pkgs[n] for n in rest] == sorted((pkgs[n] for n in rest), reverse=True)
    with pytest.raises(ValueError):
        cfgmod.build_whitelist([f"p{i}" for i in range(65)], pkgs, count)


def test_resolve_vocabulary_impossible_fallback_low_confidence():
    inv = inventory.load()
    lv = inv.cmm
    part = Counter({e: 5000 for e in lv.entities})
    for e in ("Cload_single", "TUPLE", "RETURN_ADDR"):
        part[e] = 0
    part["Cload_byte_s"] = 7
    v = cfgmod.resolve_vocabulary(inv, "cmm", part, {}, threshold=1000)
    assert v["fallback_map"] == {"Cload_single": "Cload_double", "TUPLE": "COPY"}
    assert "RETURN_ADDR" in v["impossible"] and "RETURN_ADDR" not in v["trained"]
    assert v["low_confidence"] == {"Cload_byte_s": 7}
    cv = v["coverage"]
    assert (cv["inventory"], cv["fallback_mapped"], cv["impossible"]) == (77, 2, 1)
    part["RETURN_ADDR"] = 1                          # impossible yet present: a bug
    with pytest.raises(cfgmod.FreezeError):
        cfgmod.resolve_vocabulary(inv, "cmm", part, {}, threshold=1000)
    part["RETURN_ADDR"], part["Cload_double"] = 0, 0  # fallback target untrained
    with pytest.raises(cfgmod.FreezeError):
        cfgmod.resolve_vocabulary(inv, "cmm", part, {}, threshold=1000)


def test_effect_primitives_never_merged():
    inv = inventory.load()
    part = {"lambda": Counter(), "cmm": Counter()}
    merges, _ = cfgmod.decide_merges(inv, part, threshold=1000)
    merged = {m for ms in merges["lambda"].values() for m in ms}
    assert not merged & set(cfgmod.NEVER_MERGE)


def test_family_merges_only_if_all_members_rare():
    inv = inventory.load()
    part = {"lambda": Counter({m: 5 for m in inv.lambda_.merge_candidates["P_BSWAP"]}),
            "cmm": Counter({"Cload_16u": 5000})}
    merges, _ = cfgmod.decide_merges(inv, part, threshold=1000)
    assert "P_BSWAP" in merges["lambda"] and "P_RAW_LOAD" in merges["lambda"]
    assert "Cload_narrow" not in merges["cmm"] and "C_RUNTIME" in merges["cmm"]


def test_config_roundtrip_and_tamper_detection(tmp_path: Path):
    cfg = cfgmod.VocabConfig(ocaml="5.5.1", extern_whitelist=["caml_modify"],
                             merges={"lambda": {"P_BSWAP": ["Pbswap16", "Pbbswap"]}, "cmm": {}})
    p = tmp_path / "vocab_config.json"
    cfg.save(p)
    again = cfgmod.VocabConfig.load(p)
    assert again == cfg and again.merge_map("lambda") == {"Pbswap16": "P_BSWAP",
                                                          "Pbbswap": "P_BSWAP"}
    d = json.loads(p.read_text())
    d["threshold"] = 1
    p.write_text(json.dumps(d))
    with pytest.raises(ValueError):
        cfgmod.VocabConfig.load(p)


# --------------------------------------------------- stats and plateau ---

def _golden_corpus() -> FileCorpus:
    return FileCorpus({"fact": [GOLDEN / "fact.lambda.json", GOLDEN / "fact.cmm.json"],
                       "align": [GOLDEN / "align.lambda.json"]})


def test_stats_on_golden_corpus():
    inv, corpus = inventory.load(), _golden_corpus()
    s = stats.compute(corpus, inv)
    assert s["lambda"]["n_units"] == 2 and s["cmm"]["n_units"] == 1
    assert not s["lambda"]["unknown"] and not s["cmm"]["unknown"]
    assert s["externs"]["combined"]["caml_initialize"] >= 1
    assert s["externs"]["packages"]["caml_initialize"] == 1   # only fact has a cmm unit


# ------------------------------------------------------------- selection ---

def test_max_units_is_the_largest_feasible_cap():
    counts = [940, 233, 153, 72, 57, 50] + [10] * 40
    x = selmod.max_units(counts, 0.15)
    feasible = lambda y: y <= 0.15 * sum(min(n, y) for n in counts)  # noqa: E731
    assert feasible(x) and not feasible(x + 1)
    assert selmod.max_units([5, 5, 5, 5, 5, 5, 5], 0.15) == 5      # nothing binds


def _fake_corpus(root: Path) -> Corpus:
    (root / "json").mkdir(parents=True)
    fact_l, fact_c = (GOLDEN / "fact.lambda.json").read_text(), (GOLDEN / "fact.cmm.json").read_text()
    align = json.loads((GOLDEN / "align.lambda.json").read_text())
    rows = []
    for pkg, n in [("big", 30)] + [(f"small{k}", 3) for k in range(8)]:
        d = root / "json" / pkg
        d.mkdir()
        for i in range(n):
            (d / f"U{pkg}{i}.x.lambda.json").write_text(fact_l)
            (d / f"U{pkg}{i}.x.cmm.json").write_text(fact_c)
        rows.append([pkg, "1", "ok", str(2 * n), str(n), str(n), "0", ""])
    # one "big" unit alone carries align's entities (e.g. Lapply_a2, Pgetglobal_stdlib)
    (root / "json" / "big" / "Ubig7.x.lambda.json").write_text(json.dumps(align))
    header = ["package", "version", "status", "dumps", "lambda_json", "cmm_json",
              "extract_failures", "note"]
    (root / "manifest.tsv").write_text(
        "".join("\t".join(r) + "\n" for r in [header, *rows]))
    return Corpus(root, raw=True)


def test_selection_caps_deterministically_and_keeps_coverage(tmp_path: Path):
    corpus = _fake_corpus(tmp_path)
    sel = selmod.select(corpus, cap=0.15)
    again = selmod.select(corpus, cap=0.15)
    assert sel == again
    x = sel["max_units_per_package"]
    assert x == 4                                     # 4 <= 0.15 * (4 + 8 * 3) < 5
    big = sel["packages"]["big"]["selected"]
    by_hash = sorted(corpus.stems("big"), key=selmod.unit_hash)
    assert set(by_hash[:x]) <= set(big)
    extra = set(big) - set(by_hash[:x])
    if "Ubig7.x" not in by_hash[:x]:                  # capped out, but needed for coverage
        assert extra == {"Ubig7.x"} and sel["exemptions"][0]["unit"] == "Ubig7.x"
    selmod.write(sel, corpus.selection_path)
    capped = Corpus(tmp_path)
    assert len(capped.unit_files("lambda", "big")) == len(big)
    assert capped.sha256() != Corpus(tmp_path, raw=True).sha256()


def test_plateau_outputs(tmp_path: Path):
    inv = inventory.load()
    rows = metrics.plateau(_golden_corpus(), inv)
    assert [r["packages"] for r in rows] == [1, 2]
    assert rows[1]["lambda_entities"] >= rows[0]["lambda_entities"]
    csv_path, png_path = metrics.write_plateau(rows, tmp_path)
    assert csv_path.read_text().startswith("packages,package,")
    assert png_path.stat().st_size > 1000
