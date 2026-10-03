#!/usr/bin/env bash
# Manual stress test (not part of `dune test`; takes a few minutes): compile
# the standalone programs of the pinned compiler's testsuite with the hooks,
# extract both levels, and check the Phase 2 invariants plus a Lambda
# node-count cross-check against dump_counts.
# Usage: opam exec --switch=ir2vec -- bash extractor/test/stress_testsuite.sh
set -u
SRC=${IR2VEC_OCAML_SRC:-$HOME/ir2vec-build/ocaml-5.5.1}/testsuite/tests
EX=/mnt/d/ocaml2vec/_build/default/extractor/bin/ir2vec_extract.exe
W=$(mktemp -d); cd "$W"; mkdir -p src dump out
n=0; ok=0
for f in $(ls $SRC/basic/*.ml $SRC/basic-more/*.ml $SRC/lib-*/*.ml 2>/dev/null); do
  b=$(basename "$f"); cp "$f" "src/$n-$b" 2>/dev/null || continue
  ( cd src && IR2VEC_DUMP_DIR="$W/dump" timeout 60 ocamlfind ocamlopt -package unix,str,threads.posix -c "$n-$b" >/dev/null 2>&1 ) && ok=$((ok+1))
  n=$((n+1))
done
echo "compiled $ok / $n testsuite files"
fails=0
for d in dump/*.bin; do
  lvl=$(echo "$d" | sed 's/.*\.\([a-z]*\)\.bin/\1/')
  if ! "$EX" "$lvl" "$d" -o "out/$(basename "$d" .bin).json" 2> err.txt; then
    fails=$((fails+1)); echo "EXTRACT FAIL $d: $(head -c 300 err.txt)"
  fi
done
echo "dumps: $(ls dump | wc -l), extraction failures: $fails"
DC=/mnt/d/ocaml2vec/_build/default/extractor/test/dump_counts.exe
mism=0
for d in dump/*.lambda.bin; do
  want=$("$DC" "$d" | awk '$1=="lambda" && $2!~/^(Lvar|Lmutvar|Lconst|Levent|Lifused)$/ {n+=$3} END {print n+0}')
  got=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(sum(1 for f in d['functions'] for n in f['nodes'] if n.get('owner') in (None, f['fid'])))" "out/$(basename "$d" .bin).json")
  [[ "$want" == "$got" ]] || { mism=$((mism+1)); echo "LAMBDA NODE COUNT $d: counter $want, extracted $got"; }
done
echo "lambda node-count mismatches: $mism"
python3 - "$W/out" <<'PY'
import json, sys, pathlib
STRUCT = {"COPY","ASSIGN","BR","SWITCH","JUMP","RET","TUPLE","RETURN_ADDR"}
TERM = {"BR","SWITCH","JUMP","RET","Craise"}
bad, nf, ni, ops, dead = [], 0, 0, {}, 0
for p in pathlib.Path(sys.argv[1]).glob("*.cmm.json"):
    d = json.loads(p.read_text())
    for f in d["functions"]:
        nf += 1; dead += f["dead_cops"]
        defined = {i["dst"] for b in f["blocks"] for i in b["instrs"] if i["dst"]}
        known = defined | {x["var"] for x in f["params"]} | set(f["handler_params"])
        nd = {}
        for b in f["blocks"]:
            for i in b["instrs"]:
                if i["dst"]: nd[i["dst"]] = nd.get(i["dst"], 0) + 1
        multi = set(f["mutable_vars"]) | set(f["join_vars"]) | set(f["handler_params"])
        bad += [f"{p.name}/{f['name']} multi-def {v}" for v, n in nd.items() if n > 1 and v not in multi]
        low = 0
        for b in f["blocks"]:
            ins = b["instrs"]; ni += len(ins)
            if not ins or ins[-1]["op"] not in TERM: bad.append(f"{p.name}/{f['name']} B{b['id']} no terminator")
            if any(i["op"] in TERM for i in ins[:-1]): bad.append(f"{p.name}/{f['name']} B{b['id']} early terminator")
            for i in ins:
                ops[i["op"]] = ops.get(i["op"], 0) + 1
                if i["op"] not in STRUCT: low += 1
                for o in i["operands"]:
                    if "var" in o and o["var"] not in known: bad.append(f"{p.name}/{f['name']} undefined {o['var']}")
        if low + f["dead_cops"] != f["n_cops"]: bad.append(f"{p.name}/{f['name']} cop count")
lam = 0
for p in pathlib.Path(sys.argv[1]).glob("*.lambda.json"):
    lam += sum(len(f["nodes"]) for f in json.loads(p.read_text())["functions"])
print(f"cmm functions {nf}, instructions {ni}, dead cops {dead}; lambda nodes {lam}")
print(f"distinct cmm opcodes seen: {len(ops)}")
print("invariant violations:", len(bad)); [print("  ", b) for b in bad[:15]]
PY
rm -rf "$W"
