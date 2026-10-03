#!/usr/bin/env bash
# Phase 0 acceptance: object files from the patched switch (with and without
# IR2VEC_DUMP_DIR) are byte-identical to those from the stock switch.
# Needs both switches: make_switch.sh --stock
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
FIXTURES="$HERE/../tests/fixtures"
FILES=(fact.ml align.ml closures.ml effects.ml exn.ml)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

build() {  # <switch> <outdir> [dump-dir]
  mkdir -p "$2"; cp "${FILES[@]/#/$FIXTURES/}" "$2"/
  ( cd "$2"
    for f in "${FILES[@]}"; do
      if [[ -n "${3:-}" ]]; then
        IR2VEC_DUMP_DIR="$3" opam exec --switch="$1" -- ocamlfind ocamlopt -c "$f"
      else
        env -u IR2VEC_DUMP_DIR opam exec --switch="$1" -- ocamlfind ocamlopt -c "$f"
      fi
    done )
}

build ir2vec-stock "$WORK/stock"
build ir2vec "$WORK/patched"
build ir2vec "$WORK/dumping" "$WORK/dumps"

status=0
for f in "${FILES[@]}"; do
  for ext in o cmx cmi; do
    b="${f%.ml}.$ext"
    for v in patched dumping; do
      if cmp -s "$WORK/stock/$b" "$WORK/$v/$b"; then
        echo "same  $v/$b"
      else
        echo "DIFF  $v/$b"; status=1
      fi
    done
  done
done
(( status == 0 )) && echo "PASS: ${#FILES[@]} fixtures, .o/.cmx/.cmi identical to stock"
exit $status
