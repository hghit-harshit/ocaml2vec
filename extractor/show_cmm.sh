#!/usr/bin/env bash
# show_cmm.sh [--print tree|tac] <file.ml>... [-- <ocamlfind flags>]
#
# Compiles each file once with the ir2vec switch (IR2VEC_DUMP_DIR set, in a
# temp dir) and writes the readable Cmm views next to the source:
#   foo.ml -> foo.cmm-tree.txt  (Cmm as dumped)
#             foo.cmm-tac.txt   (lowered TAC + CFG, what the vectors use)
# --print tree|tac prints that view to stdout instead of writing files.
# Flags after -- go to ocamlfind, e.g. -- -package str.
set -euo pipefail

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

print=""; files=(); flags=()
while (( $# )); do
  case $1 in
    --print) [[ ${2:-} == tree || ${2:-} == tac ]] || usage; print=$2; shift 2 ;;
    -h|--help) usage ;;
    --) shift; flags=("$@"); break ;;
    *) files+=("$1"); shift ;;
  esac
done
(( ${#files[@]} )) || usage

repo=$(cd "$(dirname "$0")/.." && pwd)
extract=$repo/_build/default/extractor/bin/ir2vec_extract.exe
# no-op unless the extractor's sources (or the compiler) changed
(cd "$repo" && opam exec --switch=ir2vec -- dune build ./extractor/bin/ir2vec_extract.exe)

work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
for f in "${files[@]}"; do
  [[ $f == *.ml && -f $f ]] || { echo "show_cmm: not an .ml file: $f" >&2; exit 1; }
  rm -rf "$work"/*; mkdir -p "$work/dump"
  IR2VEC_DUMP_DIR="$work/dump" opam exec --switch=ir2vec -- \
    ocamlfind ocamlopt -c ${flags[@]+"${flags[@]}"} -o "$work/$(basename "$f" .ml).cmx" "$f"
  dumps=("$work"/dump/*.cmm.bin)
  (( ${#dumps[@]} == 1 )) || { echo "show_cmm: expected one cmm dump for $f" >&2; exit 1; }
  if [[ -n $print ]]; then
    "$extract" "cmm-$print" "${dumps[0]}"
  else
    "$extract" cmm-tree "${dumps[0]}" -o "${f%.ml}.cmm-tree.txt"
    "$extract" cmm-tac "${dumps[0]}" -o "${f%.ml}.cmm-tac.txt"
    echo "${f%.ml}.cmm-tree.txt  ${f%.ml}.cmm-tac.txt"
  fi
done
