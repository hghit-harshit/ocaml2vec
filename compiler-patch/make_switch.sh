#!/usr/bin/env bash
# Build the opam switch "ir2vec": OCaml 5.5.1 (non-flambda) + ir2vec-hooks.patch.
#
#   compiler-patch/make_switch.sh            # patched switch "ir2vec"
#   compiler-patch/make_switch.sh --stock    # also "ir2vec-stock" (unpatched, same version)
#
# Env: IR2VEC_BUILD_DIR (default ~/ir2vec-build) holds the patched source tree.
# Rerunning rebuilds the switch from scratch.
set -euo pipefail

OCAML_VERSION=5.5.1
SWITCH=ir2vec
STOCK_SWITCH=ir2vec-stock
PKG_VERSION="$OCAML_VERSION+ir2vec"
TOOLS="ocamlfind dune"

HERE=$(cd "$(dirname "$0")" && pwd)
PATCH="$HERE/ir2vec-hooks.patch"
WORK=${IR2VEC_BUILD_DIR:-$HOME/ir2vec-build}
SRC="$WORK/ocaml-$PKG_VERSION"

WITH_STOCK=0
[[ "${1:-}" == "--stock" ]] && WITH_STOCK=1

# The compiler build must never produce dumps of its own stdlib.
unset IR2VEC_DUMP_DIR

# --- 1. system prerequisites (opam and the tools it shells out to) ---
missing=()
for t in opam gcc make patch git curl unzip bzip2 m4 bwrap pkg-config; do
  command -v "$t" >/dev/null || missing+=("$t")
done
if (( ${#missing[@]} )); then
  echo "Missing tools: ${missing[*]}; installing via apt (needs sudo)." >&2
  sudo apt-get update
  sudo apt-get install -y opam build-essential patch git curl unzip bzip2 m4 \
    bubblewrap pkg-config
fi

if [[ ! -d "${OPAMROOT:-$HOME/.opam}" ]]; then
  opam init -y --bare --no-setup
fi
opam update

# --- 2. patched source tree ---
mkdir -p "$WORK"
rm -rf "$SRC"
git clone -q --depth 1 -b "$OCAML_VERSION" https://github.com/ocaml/ocaml.git "$SRC"
git -C "$SRC" apply --verbose "$PATCH"

# --- 3. patched switch: pin ocaml-variants to the local tree ---
if opam switch list --short | grep -qx "$SWITCH"; then
  opam switch remove -y "$SWITCH"
fi
opam switch create "$SWITCH" --empty
opam pin add -y -n --switch="$SWITCH" --kind=path \
  "ocaml-variants.$PKG_VERSION" "$SRC"
opam install -y --switch="$SWITCH" "ocaml-variants.$PKG_VERSION" $TOOLS
# Pin the compiler as the switch invariant: without it, installing a package
# that needs another OCaml silently replaces the patched compiler (D4.11).
opam switch set-invariant -y --switch="$SWITCH" --packages="ocaml-variants.$PKG_VERSION"

# --- 4. optional stock switch for object-file comparison ---
if (( WITH_STOCK )); then
  if opam switch list --short | grep -qx "$STOCK_SWITCH"; then
    opam switch remove -y "$STOCK_SWITCH"
  fi
  opam switch create "$STOCK_SWITCH" "ocaml-base-compiler.$OCAML_VERSION"
  opam install -y --switch="$STOCK_SWITCH" $TOOLS
fi

# --- 5. sanity: non-flambda, right version, hooks present ---
opam exec --switch="$SWITCH" -- ocamlopt -config | grep -E '^(version|flambda):'
if [[ "$(opam exec --switch="$SWITCH" -- ocamlopt -config-var flambda)" != "false" ]]; then
  echo "error: switch $SWITCH is flambda-enabled" >&2; exit 1
fi
LIBDIR=$(opam exec --switch="$SWITCH" -- ocamlfind query compiler-libs.optcomp)
grep -q ir2vec_dump_lambda "$LIBDIR/asmgen.mli" \
  || { echo "error: hooks missing from installed asmgen.mli" >&2; exit 1; }
echo "switch $SWITCH ready"
