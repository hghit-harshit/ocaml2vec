#!/usr/bin/env bash
# The build must fail if a constructor is unmapped (BUILD_SPEC rule 6).
# Compiles mutated copies of lambda_ent.ml (and cmm_ent.ml) with their own
# warning attributes:
#   1. one primitive case deleted          -> warning 8 (non-exhaustive), fatal
#   2. one case replaced by a wildcard     -> warning 4 (fragile match), fatal
#   3. unmodified                          -> compiles
set -euo pipefail
SRC=$(realpath "$1")
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
compile() {  # dir
  ( cd "$1" &&
    ocamlfind ocamlopt -package compiler-libs.optcomp -c entities.ml &&
    ocamlfind ocamlopt -package compiler-libs.optcomp -c lambda_ent.ml ) >"$1/log" 2>&1
}
setup() { mkdir -p "$WORK/$1"; cp "$SRC/entities.ml" "$SRC/lambda_ent.ml" "$WORK/$1/"; }

setup ok
compile "$WORK/ok" || { cat "$WORK/ok/log"; echo "FAIL: unmodified lambda_ent.ml does not compile"; exit 1; }

setup missing
sed -i 's/ | Ppoll -> "Ppoll"$//' "$WORK/missing/lambda_ent.ml"
! grep -q '"Ppoll"' "$WORK/missing/lambda_ent.ml" || { echo "FAIL: mutation 1 not applied"; exit 1; }
if compile "$WORK/missing"; then echo "FAIL: missing Ppoll case compiled"; exit 1; fi
grep -q 'Error (warning 8' "$WORK/missing/log" || { cat "$WORK/missing/log"; echo "FAIL: not warning 8"; exit 1; }

setup wildcard
sed -i 's/ | Ppoll -> "Ppoll"$/ | _ -> "Ppoll"/' "$WORK/wildcard/lambda_ent.ml"
if compile "$WORK/wildcard"; then echo "FAIL: wildcard case compiled"; exit 1; fi
grep -q 'Error (warning 4' "$WORK/wildcard/log" || { cat "$WORK/wildcard/log"; echo "FAIL: not warning 4"; exit 1; }

# Same checks for cmm_ent.ml
csetup() { mkdir -p "$WORK/$1"; cp "$SRC/entities.ml" "$SRC/lambda_ent.ml" "$SRC/cmm_ent.ml" "$WORK/$1/"; }
ccompile() {
  ( cd "$1" && for m in entities lambda_ent cmm_ent; do
      ocamlfind ocamlopt -package compiler-libs.optcomp -c $m.ml || exit 1; done ) >"$1/log" 2>&1
}
csetup cok; ccompile "$WORK/cok" || { cat "$WORK/cok/log"; echo "FAIL: cmm_ent.ml does not compile"; exit 1; }
csetup cmissing
sed -i 's/^  | Cpoll -> "Cpoll"$//' "$WORK/cmissing/cmm_ent.ml"
! grep -q '"Cpoll"' "$WORK/cmissing/cmm_ent.ml" || { echo "FAIL: cmm mutation 1 not applied"; exit 1; }
if ccompile "$WORK/cmissing"; then echo "FAIL: missing Cpoll case compiled"; exit 1; fi
grep -q 'Error (warning 8' "$WORK/cmissing/log" || { cat "$WORK/cmissing/log"; echo "FAIL: not warning 8"; exit 1; }
csetup cwild
sed -i 's/^  | Cpoll -> "Cpoll"$/  | _ -> "Cpoll"/' "$WORK/cwild/cmm_ent.ml"
if ccompile "$WORK/cwild"; then echo "FAIL: cmm wildcard compiled"; exit 1; fi
grep -q 'Error (warning 4' "$WORK/cwild/log" || { cat "$WORK/cwild/log"; echo "FAIL: not warning 4"; exit 1; }

echo "PASS phase1_exhaustive"
