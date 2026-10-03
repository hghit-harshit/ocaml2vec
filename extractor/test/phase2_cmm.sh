#!/usr/bin/env bash
# Phase 2 acceptance (golden snapshot: tests/golden/dune):
#  - lowering invariants on every fixture:
#      each Cop becomes exactly one instruction (cross-checked against the
#      independent per-constructor counter dump_counts), each block ends in
#      exactly one terminator, every variable use is a parameter, a handler
#      parameter, or has a definition in the function; every variable with
#      more than one definition is a mutable, join or handler variable (D2.3)
#  - fact.ml lowers to the TAC of schema §2.9 modulo temp names
#  - align.ml: fact's self-call has operand 0 = SYM_FUNC; use contains two
#    indirect Capply whose callee is a variable defined by a Cload
#  - extraction is byte-deterministic
set -euo pipefail
EXTRACT=$(realpath "$1"); COUNTS=$(realpath "$2"); FIXTURES=$(realpath "$3")
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
cp "$FIXTURES"/*.ml "$WORK"/; cd "$WORK"
for ml in *.ml; do
  u=${ml%.ml}
  IR2VEC_DUMP_DIR="$WORK/dump" ocamlfind ocamlopt -c "$ml"
  d=(dump/*."$(md5sum "$ml" | cut -d' ' -f1)".cmm.bin)
  "$EXTRACT" cmm "${d[0]}" > "$u.cmm.json"
  "$EXTRACT" cmm "${d[0]}" > "$u.again.json"
  cmp -s "$u.cmm.json" "$u.again.json" || { echo "FAIL: $u not deterministic"; exit 1; }
  "$COUNTS" "${d[0]}" | awk '/^cmm Cop:/ {n += $3} END {print n + 0}' > "$u.ncops"
done
python3 - "$WORK" <<'PY'
import json, sys, pathlib
w = pathlib.Path(sys.argv[1])
STRUCTURAL = {"COPY", "ASSIGN", "BR", "SWITCH", "JUMP", "RET", "TUPLE", "RETURN_ADDR"}
TERMINATORS = {"BR", "SWITCH", "JUMP", "RET", "Craise"}
fail = []
units = {p.name[:-len(".cmm.json")]: json.loads(p.read_text()) for p in w.glob("*.cmm.json")}

for u, d in sorted(units.items()):
    n_cops = int((w / f"{u}.ncops").read_text())
    lowered = sum(1 for f in d["functions"] for b in f["blocks"] for i in b["instrs"]
                  if i["op"] not in STRUCTURAL)
    dead = sum(f["dead_cops"] for f in d["functions"])
    if n_cops != lowered + dead or n_cops != sum(f["n_cops"] for f in d["functions"]):
        fail.append(f"{u}: {n_cops} Cops in dump, {lowered} instructions + {dead} dead")
    for f in d["functions"]:
        ids = {b["id"] for b in f["blocks"]}
        defined = {i["dst"] for b in f["blocks"] for i in b["instrs"] if i["dst"]}
        known = defined | {p["var"] for p in f["params"]} | set(f["handler_params"])
        ndefs = {}
        for b in f["blocks"]:
            for i in b["instrs"]:
                if i["dst"]: ndefs[i["dst"]] = ndefs.get(i["dst"], 0) + 1
        multi = set(f["mutable_vars"]) | set(f["join_vars"]) | set(f["handler_params"])
        for v, n in ndefs.items():
            if n > 1 and v not in multi:
                fail.append(f"{u}/{f['name']}: {v} has {n} definitions but is not multi-def")
        for b in f["blocks"]:
            ins = b["instrs"]
            if not ins or ins[-1]["op"] not in TERMINATORS or not ins[-1]["terminator"]:
                fail.append(f"{u}/{f['name']} B{b['id']}: does not end in a terminator")
            if any(i["terminator"] or i["op"] in TERMINATORS for i in ins[:-1]):
                fail.append(f"{u}/{f['name']} B{b['id']}: terminator before the end")
            if not set(b["succ"]) | set(b["exn_succ"]) <= ids:
                fail.append(f"{u}/{f['name']} B{b['id']}: dangling successor")
            for i in ins:
                for o in i["operands"]:
                    if "var" in o and o["var"] not in known:
                        fail.append(f"{u}/{f['name']}: use of undefined {o['var']}")

# schema §2.9, modulo temp names (5.5.1: n has machtype int, see DECISIONS D2.4)
def canon(f):
    names, out = {}, []
    def nm(v):
        if v.startswith("t") and v[1:].isdigit():
            names.setdefault(v, f"T{len(names) + 1}")
            return names[v]
        return v.split("/")[0]
    for b in f["blocks"]:
        rows = []
        for i in b["instrs"]:
            ops = [nm(o["var"]) if "var" in o else o["kind"] for o in i["operands"]]
            lhs = nm(i["dst"]) + " = " if i["dst"] else ""
            rows.append(f"{lhs}{i['op']} {', '.join(ops)}".strip())
        out.append((b["id"], rows, b["succ"]))
    return out
fact = next(f for f in units["fact"]["functions"] if f["name"].endswith("fact_274"))
want = [(0, ["T1 = Ccmpi n, CONST_INT", "BR T1"], [1, 2]),
        (1, ["RET CONST_INT"], []),
        (2, ["T2 = Caddi n, CONST_INT", "T3 = Capply SYM_FUNC, T2", "T4 = Casr T3, CONST_INT",
             "T5 = Caddi n, CONST_INT", "T6 = Cmuli T5, T4", "T7 = Caddi T6, CONST_INT",
             "RET T7"], [])]
if canon(fact) != want:
    fail.append(f"fact.ml TAC differs from schema §2.9: {canon(fact)}")

align = {f["name"].split(".")[-1]: f for f in units["align"]["functions"]}
calls = [i for b in align["fact_274"]["blocks"] for i in b["instrs"] if i["op"] == "Capply"]
if len(calls) != 1 or calls[0]["operands"][0]["kind"] != "SYM_FUNC":
    fail.append(f"align.ml: fact self-call {calls}")
use = align["use_280"]
defs = {i["dst"]: i["op"] for b in use["blocks"] for i in b["instrs"] if i["dst"]}
ind = [i for b in use["blocks"] for i in b["instrs"] if i["op"] == "Capply"
       and "var" in i["operands"][0] and defs.get(i["operands"][0]["var"], "").startswith("Cload_")]
if len(ind) != 2:
    fail.append(f"align.ml: use has {len(ind)} indirect Capply through a loaded callee")

for f in fail: print("FAIL:", f)
sys.exit(1 if fail else 0)
PY
echo "PASS phase2_cmm"
