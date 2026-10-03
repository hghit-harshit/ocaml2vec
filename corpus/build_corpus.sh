#!/usr/bin/env bash
# Build the training corpus in the ir2vec switch (BUILD_SPEC Phase 3.1).
#
# For each package in packages.txt (minus exclude.txt):
#   1. install its dependencies without dumps;
#   2. (re)install the package with IR2VEC_DUMP_DIR set;
#   3. move the dumps to $CORPUS/dumps/<pkg> and extract every dump to
#      $CORPUS/json/<pkg>/<Unit>.<md5>.{lambda,cmm}.json.
# Failures are logged ($CORPUS/logs/<pkg>.log) and skipped. The per-package
# outcome is written to $CORPUS/manifest.tsv.
#
#   corpus/build_corpus.sh [pkg...]     # default: every package in packages.txt
#
# Env: IR2VEC_CORPUS_DIR (default ~/ir2vec-corpus), OPAMJOBS.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
SWITCH=ir2vec
CORPUS=${IR2VEC_CORPUS_DIR:-$HOME/ir2vec-corpus}
# opam's build sandbox binds /tmp read-write, so dumps land there first.
STAGE=/tmp/ir2vec-dumps
MANIFEST=$CORPUS/manifest.tsv

# Dune's shared cache would restore build artifacts without running ocamlopt,
# which would silently produce no dumps.
export DUNE_CACHE=disabled

mkdir -p "$CORPUS"/{dumps,json,logs} "$STAGE"
[[ -f "$MANIFEST" ]] || printf 'package\tversion\tstatus\tdumps\tlambda_json\tcmm_json\textract_failures\tnote\n' > "$MANIFEST"

opam exec --switch=$SWITCH -- dune build --root "$ROOT" extractor/bin/ir2vec_extract.exe \
  || { echo "cannot build ir2vec-extract" >&2; exit 1; }
EXTRACT=$ROOT/_build/default/extractor/bin/ir2vec_extract.exe
check_compiler

# The switch must still hold the patched 5.5.1 compiler: a solver downgrade
# once replaced it mid-run, silently producing packages without dumps (D4.11).
check_compiler() {
  local v lib
  v=$(opam exec --switch=$SWITCH -- ocamlopt -config-var version 2>/dev/null)
  lib=$(opam exec --switch=$SWITCH -- ocamlfind query compiler-libs.optcomp 2>/dev/null)
  if [[ "$v" != 5.5.1 ]] || ! grep -q ir2vec_dump_lambda "$lib/asmgen.mli" 2>/dev/null; then
    echo "FATAL: switch $SWITCH no longer has the patched OCaml 5.5.1 (found '$v')" >&2
    exit 3
  fi
  # Canary: the actual compiler binary must write dumps that the strict reader
  # accepts (hook revision + build hash, D5.13). A stock compiler writes none,
  # which would otherwise look like a package without units.
  local c; c=$(mktemp -d)
  echo 'let canary x = x + 1' > "$c/canary.ml"
  if ! ( cd "$c" && IR2VEC_DUMP_DIR="$c/d" opam exec --switch=$SWITCH -- \
           ocamlfind ocamlopt -c canary.ml && "$EXTRACT" cmm d/Canary.*.cmm.bin >/dev/null ) \
       >/dev/null 2>&1; then
    echo "FATAL: canary compile in $SWITCH produced no dump the extractor accepts" >&2
    rm -rf "$c"; exit 3
  fi
  rm -rf "$c"
}

strip() { sed -e 's/#.*//' -e 's/[[:space:]]//g' "$1" | grep -v '^$'; }
mapfile -t EXCLUDED < <(strip "$HERE/exclude.txt")
if (( $# )); then PKGS=("$@"); else mapfile -t PKGS < <(strip "$HERE/packages.txt"); fi

record() {  # pkg version status dumps lam cmm xfail note
  # Replace the package's row in place (keeping manifest order = packages.txt
  # order, which the plateau plot uses), or append a new row.
  local tmp row; tmp=$(mktemp)
  row=$(printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s' "$@")
  awk -F'\t' -v p="$1" -v row="$row" \
    'NR > 1 && $1 == p { print row; done = 1; next } { print } END { if (!done) print row }' \
    "$MANIFEST" > "$tmp" && mv "$tmp" "$MANIFEST"
}

for pkg in "${PKGS[@]}"; do
  log=$CORPUS/logs/$pkg.log
  if printf '%s\n' "${EXCLUDED[@]}" | grep -qx "$pkg"; then
    echo "skip  $pkg (exclude.txt)"; record "$pkg" - excluded 0 0 0 0 "exclude.txt"; continue
  fi
  echo "build $pkg"
  : > "$log"
  if [[ "$pkg" == ocaml-stdlib ]]; then   # not an opam package (D3.12)
    if bash "$HERE/build_stdlib.sh" >> "$log" 2>&1; then
      shopt -s nullglob
      dumps=("$CORPUS/dumps/$pkg"/*.bin); lam=("$CORPUS/json/$pkg"/*.lambda.json)
      cmm=("$CORPUS/json/$pkg"/*.cmm.json); shopt -u nullglob
      echo "  ok: ${#dumps[@]} dumps, ${#lam[@]} lambda, ${#cmm[@]} cmm"
      record "$pkg" "$(opam exec --switch=$SWITCH -- ocamlopt -version)" ok         "${#dumps[@]}" "${#lam[@]}" "${#cmm[@]}" 0 "compiler stdlib (build_stdlib.sh)"
    else
      echo "  FAIL build (see $log)"; record "$pkg" - failed-build 0 0 0 0 ""
    fi
    continue
  fi
  if ! env -u IR2VEC_DUMP_DIR opam install --switch=$SWITCH -y --deps-only "$pkg" >> "$log" 2>&1; then
    echo "  FAIL deps (see $log)"; record "$pkg" - failed-deps 0 0 0 0 ""; continue
  fi
  check_compiler
  version=$(opam show --switch=$SWITCH -f version "$pkg" 2>/dev/null | head -1)
  # `opam reinstall` would rebuild installed reverse dependencies into this
  # package's dumps: remove them first; they come back later as dependencies
  # (without dumps) or in their own turn (D3.4).
  rdeps=$(opam list --switch=$SWITCH --installed --short --depends-on="$pkg" 2>/dev/null | tr '\n' ' ')
  note=""
  if [[ -n "${rdeps// /}" ]]; then
    note="removed dependents first: $rdeps"
    # shellcheck disable=SC2086
    if ! env -u IR2VEC_DUMP_DIR opam remove --switch=$SWITCH -y $rdeps >> "$log" 2>&1; then
      echo "  FAIL removing dependents (see $log)"; record "$pkg" - failed-deps 0 0 0 0 "$note"; continue
    fi
  fi
  rm -rf "${STAGE:?}/$pkg"
  if opam list --switch=$SWITCH --installed --short "$pkg" 2>/dev/null | grep -qx "$pkg"; then
    verb=reinstall
  else
    verb=install
  fi
  if ! IR2VEC_DUMP_DIR="$STAGE/$pkg" opam $verb --switch=$SWITCH -y "$pkg" >> "$log" 2>&1; then
    echo "  FAIL build (see $log)"; record "$pkg" "$version" failed-build 0 0 0 0 "$note"
    rm -rf "${STAGE:?}/$pkg"; check_compiler; continue
  fi
  check_compiler
  rm -rf "$CORPUS/dumps/$pkg" "$CORPUS/json/$pkg"
  mkdir -p "$CORPUS/dumps/$pkg" "$CORPUS/json/$pkg"
  shopt -s nullglob
  for f in "$STAGE/$pkg"/*.bin; do mv "$f" "$CORPUS/dumps/$pkg/"; done
  rm -rf "${STAGE:?}/$pkg"
  dumps=("$CORPUS/dumps/$pkg"/*.bin)
  xfail=0
  for d in "${dumps[@]}"; do
    b=$(basename "$d" .bin)                         # Unit.<md5>.<level>
    level=${b##*.}
    if ! "$EXTRACT" "$level" "$d" -o "$CORPUS/json/$pkg/$b.json" >> "$log" 2>&1; then
      xfail=$((xfail + 1)); echo "extract failed: $d" >> "$log"
      rm -f "$CORPUS/json/$pkg/$b.json"
    fi
  done
  lam=("$CORPUS/json/$pkg"/*.lambda.json); cmm=("$CORPUS/json/$pkg"/*.cmm.json)
  shopt -u nullglob
  status=ok; (( ${#dumps[@]} == 0 )) && status=no-dumps
  echo "  $status: ${#dumps[@]} dumps, ${#lam[@]} lambda, ${#cmm[@]} cmm, $xfail extract failures"
  record "$pkg" "$version" "$status" "${#dumps[@]}" "${#lam[@]}" "${#cmm[@]}" "$xfail" "$note"
done
# Keep manifest rows in packages.txt order (the plateau plot's x axis).
order=$(strip "$HERE/packages.txt" | tr '\n' ' ')
tmp=$(mktemp)
awk -F'\t' -v order="$order" '
  BEGIN { n = split(order, o, " "); for (i = 1; i <= n; i++) rank[o[i]] = i }
  NR == 1 { print "00000000\t" $0; next }
  { r = ($1 in rank) ? rank[$1] : 100000 + NR; printf "%08d\t%s\n", r, $0 }' "$MANIFEST" \
  | sort -n | cut -f2- > "$tmp" && mv "$tmp" "$MANIFEST"
echo "manifest: $MANIFEST"
