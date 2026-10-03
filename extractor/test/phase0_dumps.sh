#!/usr/bin/env bash
# Phase 0 acceptance (run by `dune test`):
#  1. IR2VEC_DUMP_DIR=<d> ocamlfind ocamlopt -c align.ml writes both dumps
#  2. dump_counts unmarshals both and prints per-constructor counts
#  3. with IR2VEC_DUMP_DIR unset (or empty) nothing is written
#  4. every fixture dumps and unmarshals cleanly
#  5. headers carry format 2, hooks 3 and this switch's build; a forged build
#     hash is rejected by the extractor (D5.13); a format-1 dump (the current
#     corpus) is read only with --legacy-format-1, identically
set -euo pipefail
COUNTS=$(realpath "$1")
FIXTURES=$(realpath "$2")
EXTRACT=$(realpath "$3")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

cp "$FIXTURES"/*.ml "$WORK"/
cd "$WORK"

# --- 1. both dumps written, header correct ---
IR2VEC_DUMP_DIR="$WORK/d" ocamlfind ocamlopt -c align.ml
shopt -s nullglob
lam=(d/Align.*.lambda.bin); cmm=(d/Align.*.cmm.bin)
(( ${#lam[@]} == 1 )) || fail "expected one Align lambda dump, got ${#lam[@]}"
(( ${#cmm[@]} == 1 )) || fail "expected one Align cmm dump, got ${#cmm[@]}"
digest=$(md5sum align.ml | cut -d' ' -f1)
[[ "${lam[0]}" == "d/Align.$digest.lambda.bin" ]] || fail "bad name ${lam[0]}"
[[ "${cmm[0]}" == "d/Align.$digest.cmm.bin" ]] || fail "bad name ${cmm[0]}"
ver=$(ocamlfind ocamlopt -version)
build=$(md5sum "$(command -v ocamlopt.opt)" | cut -d' ' -f1)
for f in "${lam[0]}" "${cmm[0]}"; do
  head -c 300 "$f" | grep -qx "IR2VEC-DUMP" || fail "$f: no magic"
  head -c 300 "$f" | grep -qx "ocaml=$ver" || fail "$f: no ocaml=$ver"
  head -c 300 "$f" | grep -qx "unit=Align" || fail "$f: no unit=Align"
  head -c 300 "$f" | grep -qx "format=2" || fail "$f: not format 2"
  head -c 300 "$f" | grep -qx "hooks=3" || fail "$f: not hooks revision 3"
  head -c 300 "$f" | grep -qx "build=$build" || fail "$f: build is not this switch's ocamlopt.opt"
  head -c 300 "$f" | grep -qx "source=align.ml" || fail "$f: no source"
done
# a dump claiming another compiler build is rejected (D5.13)
sed '0,/^build=/s/^build=.*/build=00000000000000000000000000000000/' "${cmm[0]}" > forged.cmm.bin
if "$EXTRACT" cmm forged.cmm.bin >/dev/null 2>&1; then fail "forged build hash accepted"; fi
# legacy format 1 (the current corpus, D5.13): rewrite only the header
python3 - "${cmm[0]}" legacy.cmm.bin <<'PY'
import sys
raw = open(sys.argv[1], "rb").read()
head, sep, body = raw.partition(b"\n\n")
lines = [l for l in head.split(b"\n") if not l.startswith((b"hooks=", b"build="))]
lines = [b"format=1" if l.startswith(b"format=") else l for l in lines]
open(sys.argv[2], "wb").write(b"\n".join(lines) + sep + body)
PY
if "$EXTRACT" cmm legacy.cmm.bin >/dev/null 2>&1; then fail "format 1 accepted without the flag"; fi
"$EXTRACT" cmm --legacy-format-1 legacy.cmm.bin > legacy.json || fail "--legacy-format-1 rejected a format-1 dump"
"$EXTRACT" cmm "${cmm[0]}" | cmp -s - legacy.json || fail "legacy extraction differs from format 2"
tmps=(d/*.tmp)
(( ${#tmps[@]} == 0 )) || fail "leftover temp files: ${tmps[*]}"

# --- 2. unmarshal + per-constructor counts ---
out=$("$COUNTS" "${lam[0]}" "${cmm[0]}")
echo "$out"
grep -q '^lambda Lfunction ' <<<"$out" || fail "no Lfunction counted"
grep -q '^lambda Pmulint ' <<<"$out" || fail "no Pmulint counted"
grep -q '^cmm Cfunction ' <<<"$out" || fail "no Cfunction counted"
grep -q '^cmm Cop:Capply ' <<<"$out" || fail "no Capply counted"

# --- 3. nothing written when unset or empty ---
rm -rf d ./*.o ./*.cm*
( unset IR2VEC_DUMP_DIR; ocamlfind ocamlopt -c align.ml )
IR2VEC_DUMP_DIR= ocamlfind ocamlopt -c align.ml
[[ ! -e d ]] || fail "dump dir created with IR2VEC_DUMP_DIR unset"
[[ -z "$(find "$WORK" -name '*.bin')" ]] || fail "dump written with IR2VEC_DUMP_DIR unset"

# --- 4. every fixture round-trips ---
for ml in *.ml; do
  IR2VEC_DUMP_DIR="$WORK/all" ocamlfind ocamlopt -c "$ml"
done
n_ml=$(ls *.ml | wc -l)
(( $(ls all/*.lambda.bin | wc -l) == n_ml )) || fail "missing lambda dumps"
(( $(ls all/*.cmm.bin | wc -l) == n_ml )) || fail "missing cmm dumps"
"$COUNTS" all/*.bin > all_counts.txt
echo "phase0: all $n_ml fixtures dumped and unmarshalled"
echo "PASS phase0_dumps"
