#!/usr/bin/env bash
# extract_fixture.sh <lambda|cmm> <ir2vec-extract> <fixture.ml>
# Compiles the fixture (by basename, in a temp dir) with IR2VEC_DUMP_DIR set
# and prints the extracted JSON for the requested level on stdout.
set -euo pipefail
level=$1; extract=$(realpath "$2"); src=$(realpath "$3")
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
cp "$src" "$work"/; cd "$work"
IR2VEC_DUMP_DIR="$work/dump" ocamlfind ocamlopt -c "$(basename "$src")"
dumps=(dump/*."$level".bin)
(( ${#dumps[@]} == 1 )) || { echo "expected one $level dump" >&2; exit 1; }
"$extract" "$level" "${dumps[0]}"
