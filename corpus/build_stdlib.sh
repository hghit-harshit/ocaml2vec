#!/usr/bin/env bash
# Add the pinned compiler's own stdlib to the corpus as package "ocaml-stdlib"
# (DECISIONS.md D3.12). Several primitives (Patomic_load, Pdls_get, Prunstack,
# Presume, Preperform) occur only inside the stdlib: user code reaches them
# through ordinary stdlib functions.
#
# Builds a copy of the patched source tree without dumps, then rebuilds only
# stdlib/*.cmx with IR2VEC_DUMP_DIR set, extracts, and records the manifest row.
# Called by build_corpus.sh for the pseudo-package "ocaml-stdlib".
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
CORPUS=${IR2VEC_CORPUS_DIR:-$HOME/ir2vec-corpus}
WORK=${IR2VEC_BUILD_DIR:-$HOME/ir2vec-build}
SRC=$WORK/ocaml-5.5.1+ir2vec        # the tree make_switch.sh pinned
TREE=$WORK/stdlib-corpus-tree
EXTRACT=$ROOT/_build/default/extractor/bin/ir2vec_extract.exe
PKG=ocaml-stdlib

unset IR2VEC_DUMP_DIR
rm -rf "$TREE"
cp -a "$SRC" "$TREE"
cd "$TREE"
./configure --prefix="$TREE/_install" > configure.log 2>&1
make -j"${OPAMJOBS:-3}" > make.log 2>&1

# Rebuild the native stdlib objects only, with dumps.
rm -f stdlib/*.cmx stdlib/*.o stdlib/stdlib.cmxa stdlib/stdlib.a
rm -rf "$CORPUS/dumps/$PKG" "$CORPUS/json/$PKG"
mkdir -p "$CORPUS/dumps/$PKG" "$CORPUS/json/$PKG"
IR2VEC_DUMP_DIR="$CORPUS/dumps/$PKG" make -C stdlib allopt > make-stdlib.log 2>&1
for d in "$CORPUS/dumps/$PKG"/*.bin; do
  b=$(basename "$d" .bin)
  "$EXTRACT" "${b##*.}" "$d" -o "$CORPUS/json/$PKG/$b.json"
done
echo "$PKG: $(ls "$CORPUS/dumps/$PKG" | wc -l) dumps"
