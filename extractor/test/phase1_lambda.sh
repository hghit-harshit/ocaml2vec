#!/usr/bin/env bash
# Phase 1 acceptance beyond the golden snapshots (tests/golden/dune):
#  - effects.ml has Pperform / Presume / Prunstack nodes
#  - align.ml's anonymous function is recorded as anonymous, with its location
#  - counter.ml: MUTVAR def refs = the Lmutlet and the Lassign; for index VAR_INT
#  - ownership (D1.3): every root is owned by a record holding its stub, and the
#    stub's body position points at the root's body
#  - callee nodes (D1.4): stdlib call in align.ml keeps Pfield + Pgetglobal_stdlib
#  - signature counts (D1.12) on every Lfunction record, none on module_init
#  - no computed operand is VAR_ADDR (D1.11)
#  - every fixture extracts, and extraction is byte-deterministic
set -euo pipefail
EXTRACT=$(realpath "$1"); FIXTURES=$(realpath "$2"); HERE=$(dirname "$(realpath "$0")")
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
for ml in "$FIXTURES"/*.ml; do
  u=$(basename "$ml" .ml)
  bash "$HERE/extract_fixture.sh" lambda "$EXTRACT" "$ml" > "$WORK/$u.json"
  bash "$HERE/extract_fixture.sh" lambda "$EXTRACT" "$ml" > "$WORK/$u.again.json"
  cmp -s "$WORK/$u.json" "$WORK/$u.again.json" || { echo "FAIL: $u not deterministic"; exit 1; }
done
python3 - "$WORK" <<'PY'
import json, sys, pathlib
w = pathlib.Path(sys.argv[1])
units = {p.stem: json.loads(p.read_text()) for p in w.glob("*.json") if ".again" not in p.name}
fail = []
def ops(d): return [n["op"] for f in d["functions"] for n in f["nodes"]]

eff = ops(units["effects"])
for op in ("Pperform", "Presume", "Prunstack"):
    if op not in eff: fail.append(f"effects.ml: no {op} node")

align = units["align"]
anon = [f for f in align["functions"] if f["kind"] == "anonymous"]
if len(anon) != 1: fail.append(f"align.ml: {len(anon)} anonymous functions, expected 1")
elif anon[0]["loc"] != {"file": "align.ml", "l1": 4, "c1": 21, "l2": 4, "c2": 37}:
    fail.append(f"align.ml: anonymous loc {anon[0]['loc']}")
named = sorted(f["name"] for f in align["functions"] if f["kind"] == "named")
if named != ["fact", "twice", "use"]: fail.append(f"align.ml: named {named}")

init = next(f for f in align["functions"] if f["kind"] == "module_init")
heads = [n for n in init["nodes"] if "callee_of" in n]
by_id = {n["id"]: n for n in init["nodes"]}
if [(h["op"], by_id[h["callee_of"]]["op"]) for h in heads] != [("Pfield", "Lapply_a2")]:
    fail.append(f"align.ml: callee heads {heads}")
elif by_id[heads[0]["positions"][0]["child"]]["op"] != "Pgetglobal_stdlib":
    fail.append("align.ml: stdlib callee lost its Pgetglobal_stdlib")

(count,) = [f for f in units["counter"]["functions"] if f["name"] == "count"]
cid = {n["id"]: n for n in count["nodes"]}
refs = {tuple(p["def"]) for n in count["nodes"] for p in n["positions"] if p.get("leaf") == "MUTVAR"}
if len(refs) != 1 or sorted(cid[i]["op"] for i in next(iter(refs))) != ["Lassign", "Lmutlet"]:
    fail.append(f"counter.ml: MUTVAR defs {refs}")
padd = next(n for n in count["nodes"] if n["op"] == "Paddint")
if [p.get("leaf") for p in padd["positions"]] != ["MUTVAR", "VAR_INT"]:
    fail.append(f"counter.ml: for index not VAR_INT: {padd['positions']}")

for u, d in units.items():
    recs = {f["fid"]: f for f in d["functions"]}
    for f in d["functions"]:
        sig = {k for k in f["counts"] if k.startswith(("ARITY_", "RET_"))}
        if f["kind"] == "module_init":
            if sig: fail.append(f"{u}: module_init has signature counts {sig}")
            continue
        if len(sig) != 2: fail.append(f"{u}/{f['fid']}: signature counts {sig}")
        root = f["nodes"][0]
        owner = recs.get(root.get("owner"))
        stubs = [n for n in (owner or {"nodes": []})["nodes"] if n.get("func") == f["fid"]]
        if len(stubs) != 1:
            fail.append(f"{u}/{f['fid']}: owner {root.get('owner')} has {len(stubs)} stubs")
        elif stubs[0]["op"] != root["op"] or stubs[0]["type"] != root["type"]:
            fail.append(f"{u}/{f['fid']}: stub/root mismatch")
        else:
            sp, rp = stubs[0]["positions"][0], root["positions"][0]
            if sp.get("child") != rp.get("child") or sp.get("leaf") != rp.get("leaf"):
                fail.append(f"{u}/{f['fid']}: stub body {sp} vs root body {rp}")
        for n in f["nodes"][1:]:
            if "owner" in n: fail.append(f"{u}/{f['fid']}: non-root node with owner")
    for f in d["functions"]:
        for n in f["nodes"]:
            for p in n["positions"]:
                if p.get("kind") == "VAR_ADDR": fail.append(f"{u}: VAR_ADDR operand")

for f in fail: print("FAIL:", f)
sys.exit(1 if fail else 0)
PY
echo "PASS phase1_lambda"
