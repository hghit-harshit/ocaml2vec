# Decisions

## Phase 0: environment and compiler hooks

**D0.1: Platform: WSL2 Ubuntu, not native Windows.** The host is Windows 11. The spec's scripts, `/tmp` paths, and the opam package corpus (Phase 3) assume a Unix environment. The switch and build tree live in the WSL filesystem (`~/.opam`, `~/ir2vec-build`), and the repo stays on `D:` (reached as `/mnt/d/ocaml2vec`).

**D0.2: Pinned OCaml 5.5.1.** This is the latest stable `ocaml-base-compiler` in opam on 2026-09-23.

**D0.3: The repo root is the working directory.** The spec's `ocaml-ir2vec/` is this repository. A root `dune-workspace` plus `(dirs extractor tests docs)` makes `tests/fixtures` visible to `dune test` in `extractor/`, because dune won't allow dependencies outside the workspace.

**D0.4: One dump helper, in `asmgen.ml`.** Both hooks call `ir2vec_dump`. Only `ir2vec_dump_lambda` is exported through `asmgen.mli`, for `optcompile.ml` to call. This avoids adding a new compiler module, which would mean editing the compiler's build lists, and it keeps the patch to about 50 added lines in 3 files.

**D0.5: Dump naming and pairing.** Dumps are named `<unit>.<md5 of source>.<kind>.bin`.
- `unit` is `Compilenv.current_unit_name ()`.
- The source path is `!Location.input_name`. It holds the original `.ml` even when a preprocessor is used.

Both hooks derive the name the same way, so the two dumps of a unit always share one stem. The digest keeps units with the same name from different packages apart.

**D0.6: Dump format.**
- A text header of `key=value` lines: `IR2VEC-DUMP`, `format`, `kind`, `ocaml`, `unit`, `source` (escaped with `String.escaped`), `digest`. An empty line ends it.
- Then `Marshal.to_channel v []`.

The text header is readable from Python without unmarshalling. The OCaml reader (`extractor/src/dump.ml`) checks `format`, `kind`, and `ocaml = Config.version` before calling `Marshal.from_channel`, because unmarshalling is only type-safe with the exact same compiler.

**D0.7: Dump robustness.**
- The dump directory is created if missing.
- Each dump is written to a temp file in the dump directory and then `rename`d, so parallel builds never see partial files.
- If the dump fails, the temp file is removed and the exception propagates, failing the compile. There is no silent skip.

**D0.8: No Cmm dump for the native toplevel.** Hook B is skipped when `end_gen_implementation` is called with `?toplevel`, which is the native toplevel compiling phrases, not a compilation unit.

**D0.9: Hook A placement.** Hook A sits inside the non-flambda `clambda` function, on the record `{ program with Lambda.code }` that holds the simplified code, before the `-dlambda` printer. The flambda branch is untouched.

**D0.10: `effects.ml` declares effect primitives directly.** `Stdlib.Effect` exports only `%perform`. The fixture declares `%runstack`, `%resume` and `%reperform` externals over `Obj.t`, so that Phase 1 can see `Prunstack`, `Presume` and `Preperform`.

**D0.11: Per-constructor counts use `Printlambda.name_of_primitive`** for `Lprim`. Lambda and Cmm constructors use test-only exhaustive matches. These are compiler constructor names, not IR2Vec entity names, so rule 7 (entity names defined in one place) is unaffected.

**D0.12: No serializer fallback needed.** `Marshal` (no flags) handles both `Lambda.program` and `Cmm.phrase list` on all 8 fixtures, and they unmarshal cleanly in the same switch.

**D0.13: Dump file mode is 0600.** `Filename.temp_file` creates files as 0600, and `rename` keeps that mode. This is fine because dumps are produced and read by the same user. The compiler doesn't link `Unix`, so changing the mode would need extra code. Left as is.

**D0.14: Object-file check covers 5 fixtures, and both `.o` and `.cmx`/`.cmi`.** That's more than the spec's 3. It also compares the patched switch *with dumping on* against stock, which confirms the hooks don't perturb code generation.

### Phase 0 test results (2026-09-23)

- `dune test` → `PASS phase0_dumps`. Both dumps were written with correct names and headers. `dump_counts` unmarshalled both. Nothing was written with the variable unset or empty. All 8 fixtures round-tripped.
- `compiler-patch/check_objects.sh` → `PASS: 5 fixtures, .o/.cmx/.cmi identical to stock`, both for `patched` and `dumping`.
- The spec's literal command, `IR2VEC_DUMP_DIR=/tmp/d ocamlfind ocamlopt -c tests/fixtures/align.ml`, writes both dumps.
- `effects.ml` dump contains `Pperform`, `Presume`, `Prunstack` and `Preperform` (1 each).

### Resolved (2026-09-23): schema vs. OCaml 5.5.1

The original finding is kept below for the record. The resolution was confirmed by the project owner.

**D0.15: Drop the four entities that don't exist in 5.5.1.** These are `Pphyscomp`, `Pcheckbound`, `Patomic_fetch_add` and `Catomic_fetch_add`.
- Lambda goes from 114 to 111 primitives, which gives **148** entities.
- Cmm goes from 56 to 55 operations, which gives **77** entities.

If the pin moves to 5.6 and the constructors come back, the exhaustive matches will fail the build and they'll be re-added. That is the mechanism working as intended.

**D0.16: `Cload.is_atomic` was a schema omission, not a version difference.** 5.5.1 and trunk have the identical definition `Cload of { memory_chunk; mutability; is_atomic }`; the schema simply missed the third field. Do not re-litigate this.
- It becomes a count feature, `LOAD_ATOMIC` / `LOAD_NONATOMIC`, next to `LOAD_MUT` / `LOAD_IMMUT`. Cmm count features go from **81 to 83**.
- It is *not* folded into the opcode. Atomic loads are rare, so a `Cload_*_atomic` entity would be undertrained and would sit in almost the same context as its non-atomic twin. That is the collapse case in schema §0.1.

**D0.17: Pinned externs in the whitelist.** `config/vocab_config.json` (Phase 3) holds a pinned extern list on top of the top-64-by-frequency rule. Atomic fetch-and-add is now a plain `caml_atomic_fetch_add_field` call, so frequency alone could drop it. The list includes at least:
- `caml_atomic_*` (every name matching the prefix that appears in the corpus)
- `caml_modify`, `caml_compare`, `caml_equal`, `caml_string_compare`, `caml_string_equal`

Any other GC or atomic runtime name seen while building the corpus gets added.

**D0.18: The entity inventory is generated, not hand-maintained.**
- `docs/entities.5.5.1.json` is a build artifact. It's derived from the pinned compiler's installed `lambda.mli` / `cmm.mli`, parsed with compiler-libs, plus the split and exclusion rules in `extractor/src/entities.ml`.
- A test asserts the totals are 148 and 77.
- A second test checks that the exhaustive mapping functions produce exactly the inventory's opcodes, using one sample value per constructor.

This makes the schema version-parameterised instead of a document that drifts.

### Original finding: schema vs. OCaml 5.5.1 constructor lists

The schema was checked against trunk 5.6.0+dev. On 5.5.1, `lambda/lambda.mli` and `asmcomp/cmm.mli` differ as follows:

| Type | Schema | 5.5.1 | Missing in 5.5.1 |
|---|---|---|---|
| `Lambda.primitive` | 112 | 109 | `Pphyscomp`, `Pcheckbound`, `Patomic_fetch_add`. `%atomic_fetch_add` lowers to `Pccall caml_atomic_fetch_add_field`. |
| `Lambda.lambda` | 22 | 22 | none |
| `Cmm.operation` | 36 | 35 | `Catomic_fetch_add` |
| `Cmm.expression` | 19 | 19 | none. `Cvar_mut` exists. |

Also, `Cload` has an `is_atomic : bool` field that the schema doesn't list. This turned out to be a schema omission; see D0.16.

## Phase 1: Lambda extractor

**D1.1: Module layout.**
- `extractor/src/entities.ml` is the only place entity, relation and count-feature names are defined.
- `lambda_ent.ml` holds the exhaustive constructor→entity, `Type` and count mappings. It enables warnings 4 and 8 as errors through `[@@@ocaml.warning]` / `[@@@ocaml.warnerror]`, so a missing case *or* a wildcard fails the build. `test/phase1_exhaustive.sh` proves both by compiling mutated copies.
- `lambda_abs.ml` holds the traversal. `inventory.ml` generates `docs/entities.5.5.1.json`. `json_out.ml` is an in-house deterministic JSON writer, so there's no new dependency.

**D1.2: JSON shape.** It follows the BUILD_SPEC sketch, with these additions:
- A function record has `fid`, `name`, `kind` (`named`/`anonymous`/`module_init`), `stamp`, `loc`, `params` (name, stamp and type: needed for Phase 6 parameter-stamp alignment), `nodes`, `cases`, `counts`.
- Top level also has `digest`.
- A leaf position is `{"i","role","leaf","def"}`, where `def` is `null` or a list of node ids. It's a one-element list for let-bound defs and a sorted list for `MUTVAR`. A non-leaf position is `{"i","role","child","kind"}` (see D1.11), plus `"func"` for a cross-record reference (see D1.3).
- `cases` maps a switch node id to its arms, each `{"leaf":k}` or `{"child":id}`, including the default arm.

**D1.3: One owner per node (revised after review).** An `Lfunction` node is owned by the enclosing record, for triples and for vector sums alike.
- **Stub (in the owner):** the full node. `"func": <nested fid>`, and its body position is a cross-record reference `{"child": id, "func": <nested fid>}`, or the body's leaf kind if the body is a leaf. The owner emits the node's `Type` and `Child0` triples and includes it in its vector.
- **Root (in the nested record):** the same node repeated as id 0, marked `"owner": <parent fid>`, so the body has a parent inside its own record. Phase 3 and Phase 5 skip every node whose `owner` differs from the record's `fid`. That's a field check, not a convention.
- Schema §1.8 stands: a nested function's own vector excludes its root. D1.12 restores the arity and return kind that this drops.

**D1.4: The `Lapply` callee is walked, but is not a position (revised after review).** Callee nodes are emitted into the enclosing record. For a cross-module call, these are the `Pfield` heap read and the `Pgetglobal_*`. They get no incoming `Child` link, and the `Lapply`'s `Arg_i` indexing stays exactly as the schema says.
- The callee's head node carries `"callee_of": <Lapply id>`.
- **Ablatable:** dropping every node reachable from a `callee_of` head restores the no-callee variant. Measure this later.
- The schema's `(Lapply_a1, Child0, Psubint)` example is unaffected.

**D1.5: Tail position** (checked against the project owner's list; identical).
- **In tail position:** a function body, and `module_init`'s top expression.
- **Tail-preserving:** the bodies of `Llet`/`Lmutlet`/`Lletrec`; both `Lifthenelse` branches; the second part of `Lsequence`; `Lswitch`/`Lstringswitch` arms and default; both the body and handler of `Lstaticcatch` (just a local jump); the `Ltrywith` handler; and the transparent `Levent`/`Lifused`.
- **Never tail:** all operands and arguments, including the callee; all conditions; the `Llet` definition; the `Ltrywith` body (the handler stays on the stack); the `Lwhile` condition and body; the `Lfor` bounds and body; the `Lassign` value; the `Lsend` receiver and arguments.

**D1.6: Naming.**
- A named function's fid is `name/stamp`. The stamp is parsed from `Ident.unique_name`, which is `name ^ "_" ^ stamp`; 5.5.1 has no public stamp accessor.
- An anonymous function's fid is `anon/<n>`, numbered in pre-order within the unit.
- `module_init` takes the unit's name.
- 5.5.1 stamps differ from the schema's 4.14-era example (`fact/274`, not `fact/267`). Everything else in schema §1.9 matches exactly.
- Stamps depend on allocation order and shift between compiler versions. Goldens are per-version artifacts, regenerated with `dune promote`. Phase 6 alignment must compare stamps *between the two levels of one compilation*, never against literal values.

**D1.7: Typing environments.**
- The `value_kind` environment covers the whole unit, so captured variables keep their kind. It's filled from `Llet`/`Lmutlet`, `Lfunction` params and `Lstaticcatch` params.
- The `Lfor` index is `VAR_INT` (D1.14).
- Everything else is `VAR_GEN`, strictly per the schema. That includes `Lletrec` identifiers and the `Ltrywith` exception variable.
- Let-def references are per function: a use inside a nested closure gets `def: null`.

**D1.8: Count details.**
- `Pcvtbint` counts both its source and destination widths.
- `Pbintcomp` counts both its width and its predicate.
- The arm count includes the default/failaction. `ARMS_2` covers ≤ 2 arms.
- Count keys: `CALL_*`, `TAIL`/`NONTAIL`, `MUT`/`IMMUT`, `PRED_*`, `ARMS_*`, `W32`/`W64`/`WNAT`, and `EXT:<native name>`.

**D1.9: 5.5.1 details that don't change the entity set.**
- `structured_constant` has no `Const_string`; `Const_immstring` → `CONST_STRING`.
- `Levent` never occurs in native code, and its `Env.t` payload wouldn't marshal anyway.
- `Pgetglobal_self` means `Ident.same id program.module_ident`.

**D1.10: Build and test plumbing.**
- A root `dune-project` was added.
- `extractor/dune-project` declares the package `ir2vec`, which the public binary `ir2vec-extract` needs.
- The goldens and `docs/entities.5.5.1.json` are dune `diff` rules: `dune test` fails on drift and `dune promote` accepts a change.
- The shell tests use WSL's system `python3` for JSON assertions. That's test-only, with no packages.

**D1.11: Computed operands use a total `Type`→operand-kind map.** It is defined once in `Entities.computed_operand_kind`:

| Child's `Type` | Operand kind |
|---|---|
| `INT` | `VAR_INT` |
| `FLOAT` | `VAR_FLOAT` |
| `BINT` | `VAR_BINT` |
| `ADDR` | `VAR_GEN` |
| `GEN` | `VAR_GEN` |
| no `Type` | `VAR_GEN` |

This is not a judgement call. Lambda's `value_kind` has no `ADDR` constructor, so no leaf can ever produce `VAR_ADDR`. It could never be the tail of an `Arg_i` triple, and would be an untrained vector. `ADDR` stays a *type* entity, because `Parrayref*` on `Paddrarray` emits it as a `Type` tail, but it has no operand-kind counterpart.
- The extractor writes the result on every child position as `"kind"`, so Phase 5 reads it and doesn't redefine it.
- The map is also exported in `docs/entities.5.5.1.json` (`lambda.computed_operand_kind`).

**D1.12: Signature block in the Lambda count features.** Each `Lfunction` record counts its own arity (`ARITY_1`, `ARITY_2`, `ARITY_3`, `ARITY_4P`) and its return kind (`RET_INT`, `RET_FLOAT`, `RET_BINT`, `RET_GEN`).
- That's 8 dimensions, and Lambda count features go from **87 to 95**.
- It's needed because arity is folded into the opcode and the root node is owned by the parent (D1.3), so the function's own vector carries neither.
- Counts are per record, so they can't be double-counted. `module_init` has zeros.
- The keys are `RET_`-prefixed so they can't collide with type names in the count-key space.

**D1.14: The `Lfor` index is typed `VAR_INT`** (ruling after review). In 5.5.1 it's `Lfor of Ident.t * lambda * lambda * direction_flag * lambda`, so the IR carries no `value_kind`. But the language requires an int index, so this is a certainty, not a guess. This is a schema gap, in the same class as `is_atomic`. "Otherwise `GEN`" is for genuinely unknown cases, and `Lfor` is the only binder in 5.5.1 without a `value_kind`. Leaving it `VAR_GEN` would give loop-body arithmetic a systematically different operand kind from identical arithmetic elsewhere, and blur the integer-arithmetic cluster.

### Phase 1 open questions: resolved (2026-09-23)

1. `VAR_ADDR`: see D1.11.
2. The root is excluded from its own vector: see D1.3 and D1.12.
3. The `Lfor` index is `VAR_INT`: see D1.14.

## Phase 2: Cmm → TAC + CFG

**D2.1: Module layout.**
- `extractor/src/cmm_ent.ml` holds the exhaustive mappings: opcode (with chunk splits), `Type` emission, side effects, terminators and counts. Warnings 4 and 8 are errors, as in `lambda_ent.ml`, and `phase1_exhaustive.sh` mutation-tests both modules.
- `cmm_lower.ml` does the lowering. `cmm_abs.ml` classifies symbols and writes the JSON. `util.ml` holds helpers shared with the Lambda side.
- The CLI gains `ir2vec-extract cmm <dump>`.

**D2.2: Argument evaluation order is right to left, which contradicts BUILD_SPEC.** BUILD_SPEC says non-atomic arguments are "evaluated left-to-right". Right to left is used instead, because:
- it is the native backend's actual order (`Selectgen.emit_parts_list`: "force right-to-left evaluation order");
- it is the order in the authoritative schema §2.9 (`t2 = Caddi n,-2` precedes `t5 = Caddi n,-1`).

Operand *lists* keep source order, so `Arg_i` indexing is unaffected; only instruction order changes. Switching to left to right is a one-line change in `Cmm_lower.lower_args`. **Needs confirmation.**

**D2.3: Lowering contexts and joins.** Lowering is driven by three contexts: `Tail` (ends in `RET`), `Value` (produces an atomic operand) and `Effect` (discards the value).
- **Tail:** a control construct in tail context returns from each arm, with no join. That's why fact's TAC matches §2.9 exactly.
- **Value:** each arm defines a join variable (the `Clet`-bound name when there is one, else a fresh temp) and ends in a `JUMP` to a join block. If the arm's result is a `Cop`, that `Cop` defines the join variable directly; otherwise a `COPY` does.
- **Effect:** arms that fall through end in a `JUMP` to the join.
- Join variables are multiply defined and are listed in `mutable_vars`.
- The `JUMP`s and `COPY`s introduced by the lowering carry `"synthetic": true`, so they can be ablated. `JUMP` therefore covers both `Cexit` and join fall-through, which the flag distinguishes.

**D2.4: In 5.5.1, int-kind variables have machtype `Int`.** Cmmgen now types `Pintval` variables and parameters as `int` (e.g. `(n/275: int)`). So schema §2.3's claim that "tagged OCaml integers are `VAL`" is outdated.
- Effect on §2.9: `(Ccmpi, Arg0, VAR_VAL)` and `(Caddi, Arg0, VAR_VAL)` are `VAR_INT` on 5.5.1.
- Every other block, opcode, operand and order in §2.9 matches. `(Casr, Arg0, VAR_VAL)` still holds, because `Capply`'s result is `val`.
- The golden `tests/golden/fact.cmm.json` is a per-version artifact.

**D2.5: `Clet` bindings.**
- A `Clet` of a constant, a symbol or an immutable variable is an alias: no instruction, and uses see the aliased operand.
- A `Clet` of a mutable or join variable takes a snapshot (`x = COPY y`), because `y` can be redefined later.
- A `Clet` of a `Cop` makes `x` the instruction's `dst`.
- `Clet_mut` becomes `x = COPY v`, and `Cassign` becomes `x = ASSIGN v`, as in the schema.

**D2.6: `Cexit` is a parallel assignment.** Before the parameter `COPY`s, any operand that names another parameter of the same handler is snapshotted into a temp (a synthetic `COPY`). Without this, swap-shaped exits would read an already-overwritten value. `JUMP` then carries the exit arguments as operands (schema §2.5).

**D2.7: Exceptional edges.**
- Each block records `exn_succ`, the innermost enclosing `Ctrywith` handler, whenever an instruction is emitted into it while that handler is active. The block where the try begins is included, which is conservative.
- The exception variable is defined at handler entry, with no instruction, and is listed in `handler_params`.
- **Triples (Phase 3):** `Succ` for `BR`/`SWITCH`/`JUMP` comes from `succ`. `Succ` for a `Craise` inside a try comes from its block's `exn_succ`. The other `exn_succ` edges exist only for dataflow.

**D2.8: Divergence.** Code after a `raise`/`exit` is not lowered. Its `Cop`s are counted in `dead_cops`, and `n_cops` counts every `Cop` in the body independently. The invariant `lowered + dead_cops = n_cops` is tested per function, and the unit total is cross-checked against `dump_counts`. The stress run found 44 dead `Cop`s across 2,949 functions.

**D2.9: A 5.5.1 quirk: `Cmm.map_shallow` skips the scrutinee of `Cswitch`.** Both the lowering's `Cop` counter and `dump_counts` (from Phase 0) used it, so both undercounted. The stress run caught it. Each now has its own exhaustive child traversal; they're deliberately kept separate so the cross-check stays independent. The lowering itself was never affected.

**D2.10: Unit values.** `Ctuple []` in effect context emits nothing; in value or tail context it becomes `TUPLE` with no operands. An `Cassign` used as a value yields `CONST_INT`, because Cmm's unit is the constant 1.

**D2.11: Per-instruction fields.**
- `dst`, and `operands`, each `{kind, var?, sym?}`.
- `side_effect`: exactly BUILD_SPEC's list, minus `Catomic_fetch_add`, which doesn't exist in 5.5.1.
- `terminator`: `BR`, `SWITCH`, `JUMP`, `RET`, `Craise`.
- `synthetic`: see D2.3.
- A `COPY`'s or `ASSIGN`'s `Type` is the target variable's machtype (§2.4). For `Copaque`'s `Type`, constants and symbols count as `INT`, matching Selectgen.

**D2.12: Naming.**
- Variables are `name/stamp`, the same scheme as Lambda fids, which Phase 6's parameter-stamp alignment needs. Temps are `t<n>`.
- 5.5.1 symbols use `.`, not `__`: `camlAlign.fact_274`, `camlAlign.entry`. Phase 6 must match these, not schema §3's `caml<Unit>__entry`.

**D2.13: Stress test.** `extractor/test/stress_testsuite.sh` is manual and not in `dune test`. It compiles the pinned compiler's standalone `testsuite/tests/{basic,basic-more,lib-*}` programs with the hooks: 218 of 325 compile without special flags. It then runs both extractors and checks:
- the Phase 2 invariants;
- that extracted Lambda nodes, excluding owned roots, equal `dump_counts`' non-leaf constructor count, per unit.

Result (2026-09-24): 436 dumps, 0 extraction failures, 0 invariant violations, 0 Lambda node-count mismatches. That covers 2,949 Cmm functions, 87,961 instructions, 89,649 Lambda nodes and 59 distinct Cmm opcodes.

### Phase 2 rulings (2026-09-24)

**D2.2 (confirmed): Right-to-left argument evaluation.** It matches the native backend: `asmcomp/selectgen.ml`, in `emit_parts` / `emit_parts_list`, says "force right-to-left evaluation order as required by the Flambda [Un_anf] pass (and to be consistent with the bytecode compiler)". It is also the order in schema §2.9. BUILD_SPEC Phase 2 has been updated to match. `Next` triples depend on this order, so it must stay stable across the whole corpus. Changing it means regenerating every triple.

**D2.3 (riders):**
- **Join variables are never single-def.** They're listed in a separate `join_vars` field. Like `Clet_mut` variables, they're materialised with a `COPY` instead of being aliased by a `Clet`. Reaching definitions must find every arm's definition, so a use at the join sums the arms' vectors, which is IR2Vec's behaviour at a control-flow merge. Tests check that every variable with more than one definition is a mutable, join or handler variable.
- **Synthetic JUMPs count as real.** They are genuine control transfers, and excluding them would break the one-terminator-per-block invariant.
- **Synthetic COPYs are excluded from triples and from block and function sums, but stay transparent in dataflow.** A use of a join variable resolves through the COPY to the arm's defining instructions. In triples, `Next` and `Succ` bridge over them. This is the config flag `count_synthetic` (default `false`, frozen in `config/vocab_config.json`). **Ablatable.**

**D2.5 (details):**
- Alias chains resolve transitively: an alias is bound to the already-resolved operand.
- An alias that bottoms out at a parameter gives uses the parameter's operand kind and no definition.

**D2.8 (reporting): Dead code.** `dead_cops` goes into the Phase 7 report. A small number is expected; a large one signals a lowering bug.

**D2.14: `Type` for `Cdls_get` and `RETURN_ADDR`.** `Cdls_get` → `VAL` and `RETURN_ADDR` → `INT`, both confirmed on 5.5.1 (`Selectgen.oper_result_type`; `Creturn_addr` uses `typ_int`). This resolves the schema §2.4 "revisit". `Catomic_fetch_add` doesn't exist in 5.5.1.

**D2.15: Liveness rule for Phase 5.** An instruction counts if it is a **terminator**, or it has a side effect, or its `dst` is live. Terminators are never dead, as in LLVM, and dropping them would erase all control-flow signal from block vectors.

## Phase 3: corpus, vocabulary config, triples

**D3.1: Python environment.** A venv at `~/ir2vec-venv` (WSL), created with `python3 -m venv --without-pip`, with pip bootstrapped from `https://bootstrap.pypa.io/get-pip.py`. The system Python has no `ensurepip`, and `python3-venv` would need sudo. The package is `python/` (`pip install -e python[test]`), which provides the `ir2vec` CLI.
- New Python dependencies: `numpy`, `matplotlib` (plateau PNG), `pytest` (tests).

**D3.2: Merge candidates live in `entities.ml`** (`lambda_merge_families`, `cmm_merge_families`) and are exported in `docs/entities.5.5.1.json` (`merge_candidates`). Python reads them from there.
- `P_ATOMIC` is dropped: on 5.5.1 it would have one member (`Patomic_load`), so merging would only rename it.
- `C_RUNTIME` is `{Cdls_get, Cpoll, RETURN_ADDR}`.

**D3.3: Corpus location and layout.** The corpus is large and lives outside the repo: `$IR2VEC_CORPUS_DIR` (default `~/ir2vec-corpus`, in the WSL filesystem) holds `dumps/<pkg>/`, `json/<pkg>/`, `logs/<pkg>.log` and `manifest.tsv`. Package order comes from `corpus/packages.txt`, and units within a package are sorted by file name, so every traversal and the corpus hash are deterministic.

**D3.4: Building one package with dumps** (`corpus/build_corpus.sh`):
1. Install its dependencies without dumps.
2. `opam install`/`reinstall` the package with `IR2VEC_DUMP_DIR=/tmp/ir2vec-dumps/<pkg>`. opam's bwrap sandbox binds `/tmp` read-write, and the variable passes through opam and dune.
3. Move the dumps to the corpus and extract each one.

Details:
- `DUNE_CACHE=disabled`: the shared cache would restore artifacts without running `ocamlopt`, and so produce no dumps.
- `packages.txt` is in dependency order, because `opam reinstall P` also rebuilds P's installed dependents, whose dumps would land in P's directory.
- The first run exposed this anyway: a trial install of `csexp` was still present, so rebuilding `dune` rebuilt `csexp` into dune's dumps. The manifest's note column records it. The script now removes installed reverse dependencies before rebuilding, and the stray `Csexp` units were deleted from `dune`.
- Failures are logged per package and skipped.

**D3.5: Extern whitelist: exactly 64 names shared by both levels.**
- Pinned names come first: D0.17's patterns, resolved against the corpus's and the pinned stdlib's native names, sorted. Then the most frequent names fill the rest, ties broken by name.
- The pins are counted *inside* the 64, so the count-feature dimensions stay at 95 (Lambda) and 83 (Cmm). If there were more than 64 pins, `freeze-config` would fail rather than grow the vector.

**D3.6: Merge rule.** A family merges only if *every* member takes part in fewer than 1,000 pre-merge triples (as head or tail), counted with `count_synthetic = false`. The per-member counts are frozen in the config (`family_frequencies`) for provenance.

**D3.7: Freezing.** `config/vocab_config.json` records the OCaml version, the SHA-256 of the entity inventory and of the corpus, the threshold, `count_synthetic`, the pin patterns and resolved pins, the whitelist, the merges, and a `config_sha256` over all of that.
- Loading verifies the hash. `triples` refuses a config frozen against a different inventory, and warns (without recomputing) if the corpus changed.
- Only `ir2vec freeze-config` writes it, and `freeze-config` refuses stale stats.

**D3.8: Triples.**
- **Lambda:** `Type`, `Arg_i`/`Child_i` (4+ shared), and `Case` per arm, including the default, with ownership respected (D1.3). The stub's cross-record `Child0` resolves into the nested record. Callee nodes are included (D1.4).
- **Cmm:** `Type`, `Arg_i`, `Next` within a block, and `Succ` from `BR`/`SWITCH`/`JUMP` to the first kept opcode of each successor, plus from `Craise` to its block's `exn_succ` (D2.7). Synthetic COPYs are skipped and bridged (D2.3).
- Merges rename both heads and tails. Duplicates are kept.
- Output: `$CORPUS/triples/<level>.tsv` (no header) and `<level>.summary.json` (per-relation and per-entity counts, never-seen entities, unknown entities, hashes). Any unknown entity makes `ir2vec triples` exit non-zero (rule 8).

**D3.9: Golden triples.** `tests/golden/fact.{lambda,cmm}.triples.tsv` are generated from the golden extractions and reviewed. pytest asserts:
- `fact`'s Lambda triples equal schema §1.9 exactly (15);
- its Cmm triples equal the *complete* hand-derived §2.9 multiset (33), with `n` as `VAR_INT` (D2.4).

**D3.10: OCaml 5 packages added.** The first stats run (28 packages) found every effect and atomic primitive absent. `backoff`, `multicore-magic`, `saturn`, `domainslib`, `picos`, `kcas` and `moonpool` were appended to `packages.txt`. They add `Pperform` and many `caml_atomic_*` externs, but not `Patomic_load`/`Pdls_get`/`Prunstack`/`Presume`/`Preperform`. In 5.5.1, `Atomic.get`, `Domain.DLS.get` and `Effect.Deep.continue` are ordinary `val`s, so user code never contains those primitives. At Cmm level the inlined atomic loads show up in the `LOAD_ATOMIC` count.

**D3.11: Extra pinned externs** (the rule "add any GC or atomic runtime name you see"), added after the corpus review: `caml_initialize`, `caml_alloc_dummy`, `caml_update_dummy`, `caml_alloc_dummy_lazy`, `caml_update_dummy_lazy`, `caml_alloc_shr_check_gc`, `caml_obj_dup`.
- `caml_atomic_*` resolves to `caml_atomic_cas_field`, `caml_atomic_exchange_field`, `caml_atomic_fetch_add_field` and `caml_atomic_make_contended`. Before the OCaml 5 packages these had 1–2 occurrences each, so frequency alone would have dropped them.
- `caml_gc_*` (15 introspection externals in the stdlib) is deliberately *not* pinned.
- Total: 16 pinned + 48 by frequency = 64.

**D3.12: The pinned compiler's stdlib is a corpus package** (`ocaml-stdlib`, first in `packages.txt`). The primitives in D3.10 occur only inside the stdlib. `corpus/build_stdlib.sh` builds a copy of the patched tree without dumps, then rebuilds only `stdlib/*.cmx` with dumps. `build_corpus.sh` treats `ocaml-stdlib` as a pseudo-package.

**D3.13: A 5.5.1 hook bug: `-pack` (patch revision 2).** A `-pack` unit is synthesized from its members and has no source, so Hook B's `Digest.file` raised and, per D0.7, failed the compile. This broke `ocamlbuild`. When `Clflags.make_package` is set, the hook now prints `ir2vec: <unit>: -pack unit, not dumped` to stderr and dumps nothing. The switch was rebuilt, and `check_objects.sh` passes again. The codegen of the other packages is unchanged, and their dumps from revision 1 are valid.

**D3.14: Corpus skew.** `dune` contributes 940 of 1,836 units per level (including vendored libraries). Its private C stubs (`dune_clock_gettime_realtime`, `lev_watcher_is_active`, `lev_watcher_is_pending`) take 3 of the 48 frequency-ranked whitelist slots. This follows the spec's "top 64 by frequency" literally. **Open question:** rank by the number of packages that use a name instead.

### Phase 3 results (2026-09-25)

- **Corpus:** 37 packages, all built, 0 extraction failures: `ocaml-stdlib`, 28 general-purpose packages, 1 rebuilt after the D3.13 fix (`ocamlbuild`), and 7 OCaml 5 packages. That's 1,862 units per level, 54,361 Lambda functions and 64,187 Cmm functions. Corpus SHA-256 `c0163ff51371…`.
- **Triples:** 2,316,940 for Lambda and 4,668,894 for Cmm, with **0 unknown entities**.
- **Frozen config** `20e3555b192a…`:
  - Lambda merges: `P_RAW_LOAD`, `P_RAW_STORE`, `P_BIGARRAY`, `P_BSWAP`. Training vocabulary 148 → 132.
  - Cmm merges: `C_RUNTIME`, `Cstore_narrow`. Training vocabulary 77 → 71. `Cload_narrow` is *not* merged, because `Cload_32s` has 1,156 triples.
  - Whitelist: 16 pinned + 48 by frequency.

**Entity counts vs. schema:**

| | Schema | 5.5.1 inventory | Seen in corpus | Never seen |
|---|---|---|---|---|
| Lambda | 151 | 148 | 143 | `Psetglobal`, `Pduprecord`, `Pint_as_pointer`, `Ppoll`, `Psetfloatfield` |
| Cmm | 78 | 77 | 67 | `TUPLE`, `RETURN_ADDR`, `Cpoll`, `Cload_single`, `Cstore_single`, `Cload_byte_s`, `Cstore_byte_s`, `Cload_16s`, `Cstore_16s`, `Cstore_32s` |

- **Plateau:** `report/plateau.{csv,png}`. It is flat, below the inventory, with 0 unknowns, so no abstraction rule leaks. The gap to the inventory is coverage.
- Some never-seen entities are structural on this path and will stay untrained: `Psetglobal` isn't emitted by the closure (non-flambda) `transl_store_implementation`; `Cpoll` and `Ppoll` come from poll insertion after Cmm, or only from `[@poll error]`.
- **Dead code:** 255 dead `Cop`s out of 1,086,672 (0.023%), which is consistent with genuinely unreachable code (D2.8).

### Phase 3 rulings and rework (2026-09-25)

**D3.5 (confirmed).** Pins occupy slots inside the 64, in one list shared by both levels; `EXT_OTHER` is added at encoding. Each pin carries a one-line reason in the config (`pins`, `pinned_resolved`). A pin that never occurs in the corpus is kept, because it exists for inference-time programs. It is listed in `pinned_zero` and flagged in the report, so an always-zero dimension isn't mistaken for a bug.

**D4.1: Impossible entities.** These are verified against the 5.5.1 source, not assumed. They are excluded from the vocabulary, and any occurrence (in training triples or at inference) is a **hard error**, because it means a hook or lowering bug. Defined in `entities.ml` (`lambda_impossible`, `cmm_impossible`), each with its reason:
- **`Psetglobal`:** only `transl_implementation` (bytecode/flambda) and `transl_package` (bytecode) emit it. Native closure mode uses `transl_store_implementation` / `transl_store_package`.
- **`RETURN_ADDR`:** only `Thread_sanitizer.instrument` emits `Creturn_addr`, and the switch has `tsan: false`.
- The inventory test asserts `Config.flambda = false` and `Config.tsan = false`, the preconditions for both claims.

The review's grouping called `Ppoll`/`Cpoll` impossible. **They are not.** `Sys.poll_actions` is `external … = "%poll"` in 5.5.1's `sys.mli`, so user code produces `Ppoll`, and `cmmgen.ml:902` lowers it to `Cop(Cpoll, …)` before the hook. Only the *automatic* poll insertion comes later. They are treated as possible-but-absent.

**D4.2: Fallback map.** It applies to entities that can occur but have no training triples after merges. Candidates live in `entities.ml` (`lambda_fallbacks`, `cmm_fallbacks`), each with a reason. For example, `Cload_single → Cload_double`, `Cload_byte_s → Cload_byte_u`, `TUPLE → COPY`, `Ppoll → Pccall`, `Psetfloatfield → Psetfield`, `Pduprecord → Pduparray`, `Pint_as_pointer → Popaque`.
- `freeze-config` first checks whether a merge already covers the entity. Then it applies the candidate, resolved through merges, and requires its target to be trained.
- Any untrained entity without a trained fallback makes `freeze-config` fail.
- The resulting `fallback_map` is frozen per level. The config reports three distinct numbers per level: inventory, trained, and fallback-mapped (plus merged-away and impossible).

**D4.3: Whitelist ranking.** Names are ranked by the number of distinct packages that use them, with raw count as the tiebreak (then name). A non-pinned name must appear in at least 3 packages, which removes package-private C stubs such as dune's `lev_*`. If fewer than 64 names qualify, `freeze-config` fails rather than shrinking the vector.

**D4.4: Per-package cap of 15%** (`ir2vec select`, writing `$CORPUS/selection.json`).
- The cap is the largest per-package allowance *x* with *x* ≤ 0.15 · Σ min(nₚ, x), solved exactly.
- A package over the cap keeps its *x* units with the smallest SHA-256(unit name), so both levels select the same units and the sample is reproducible.
- **Coverage beats balance.** If capping would leave an entity with no triples, the first excluded unit (in manifest order, then hash order) containing it is added back as a recorded exemption.
- Order of operations: `select → stats → freeze-config → triples`. Every corpus command except `select` refuses to run without a selection, and the config records the cap parameters.
- To dilute `dune` rather than cap harder, 50 more pure-OCaml packages were added (corrected from "48" on 2026-10-01; the list has 50), spanning text and data formats, numerics (including Bigarray float32 via `gg` and `owl-base`), binary parsing (`ocplib-endian`, `decompress`), ppx and concurrency.

**D4.5: Low confidence.** Trained entities with fewer triples than the merge threshold (1,000) are frozen in `low_confidence` per level and flagged in the report. `Pperform`/`Presume`/`Prunstack`/`Preperform` are never merged (`config.NEVER_MERGE`), even when rare: low-confidence-but-present beats merged-away. They belong to no merge family anyway; the guard makes that explicit.

## Phase 4: training

**D4.6: A PyTorch trainer, not PyKEEN.** PyKEEN 1.11.1 deduplicates labeled triples: `pykeen/triples/triples_factory.py`, `_map_triples_elements_to_ids`, ends in `np.unique(ar=triples_of_ids, axis=0)`, with the comment "Using unique means implicit balancing of training samples". The schema keeps duplicates, so `python/ir2vec/train.py` is a small trainer. New dependency: `torch` 2.14.0 (CPU wheel).

**D4.7: Models.** Both use `dim` = 128 real dimensions, Adam (lr 1e-3), batch 4,096 and 4 negatives per positive, with head or tail corrupted uniformly with probability 0.5.
- **ComplEx:** rank 64, logistic (softplus) loss, L2 regularisation of 1e-5 on the embeddings in the batch. The entity vector is `concat(real, imag)`.
- **TransE:** L1 distance, margin ranking loss (margin 1), entity vectors renormalised to unit L2 norm after each step.

**D4.8: Split and evaluation.**
- A 95/5 split over triple *occurrences*, with a fixed seed.
- Evaluation is filtered, against every known triple of the level, on the *distinct* held-out triples, in both directions. Ties are ranked at their midpoint.
- Early stopping is on filtered hits@10, with MRR breaking ties, evaluated every epoch with patience 3 and at most 30 epochs. The best checkpoint is kept.
- The knowledge graph is tiny in distinct terms. The pre-cap Cmm corpus has 4.67M occurrences but only about 1,054 distinct triples, and just 3 of the 741 distinct held-out triples are "novel" (never seen in training). The held-out set therefore mostly measures memorisation, and the metrics saturate quickly. The report gives both the overall and the novel-subset metrics. Phase 7's distinctness check is the more informative quality signal.

**D4.9: Determinism.** Fixed seed (`20260925`), `torch.set_num_threads(4)` and `torch.use_deterministic_algorithms(True)`; the negatives and the shuffle use a seeded `torch.Generator`. Results are byte-identical for the same thread count, and a test checks this. Wall-clock timings in `history` are the only thing that varies.

**D4.10: Output.** `vocab/<level>.<model>.json` holds `{metadata, entities}`: one vector per *trained* entity (post-merge). Metadata covers model, dimension, rank, seed, threads, hyperparameters, torch version, the hashes of the triples, config, corpus and inventory, metrics, history, low-confidence entities, the fallback map and the impossible set. Relation vectors go separately to `vocab/<level>.<model>.relations.json` and are never used for encoding. The nearest-neighbour report goes to `report/nn_<level>_<model>.txt`.

**D4.11: Incident: opam replaced the patched compiler (2026-09-25).** `notty` 0.2.3 requires `ocaml < 5.4`. `opam install -y --deps-only notty` accepted the solver's plan to remove the pinned `ocaml-variants.5.5.1+ir2vec` and install `ocaml-base-compiler.5.3.0`. The pre-check hadn't caught this, because `--dry-run` "succeeds" with a downgrade.
- **Effect:** the 10 packages built after that point (`notty`, `printbox`, `gg`, `owl-base`, `odoc-parser`, `ppxlib`, `ppx_deriving`, `sedlex`, `lwt`, `otoml`) produced no dumps (status `no-dumps`).
- **No contamination:** the stock compiler has no hooks, and the dump reader rejects any header that isn't `ocaml=5.5.1`.
- **Fixes:**
  - `make_switch.sh` now sets the switch invariant to `ocaml-variants.5.5.1+ir2vec`, so a package needing another compiler fails instead of replacing it.
  - `build_corpus.sh` checks the compiler version and the presence of the hooks before the run and after every package, and aborts (exit 3) if either is wrong.
- **First fix attempt failed.** `opam switch set-invariant <name>` looks the name up as a repository compiler, and a locally pinned package isn't one; opam 2.5 needs `--packages=ocaml-variants.5.5.1+ir2vec`. The chained rebuild then ran without an invariant, and `notty` downgraded the compiler a second time. The new guard aborted the corpus build right after it, as designed. That run's object-file DIFFs came from comparing stock 5.5.1 with a switch holding 5.3.0; they say nothing about the patch.
- **Second attempt:** `set-invariant --packages=…`, steps chained with `&&`, a guard after the `--deps-only` step too, then a switch rebuild, `check_objects.sh`, and the 10 packages rebuilt. `notty` is expected to fail cleanly under the invariant.

### Phase 3 results after the rework (2026-09-25); supersedes the earlier results

- **Corpus:** 87 packages listed, 86 built (`notty` fails under the invariant, D4.11). 2,495 units per level before the cap.
- **Cap (15%):** at most 274 units per package, which binds only on `dune` (940 → 274, exactly 15.0%). That selects 1,829 units, with **0 coverage exemptions**: capping lost no entity.
- **Triples:** Lambda **2,690,094** (3,928 distinct), Cmm **5,799,815** (1,189 distinct). Both are above the one-million bar, and there are 0 unknown entities.
- **Distinct triples are few.** The occurrence counts are large, but the graph's structure is small, because the vocabulary is bounded by the schema (as with IR2Vec's LLVM vocabulary). More packages add frequency, not new edges.
- **Frozen config** `0806054e15dc…`:
  - **Whitelist:** 16 pins + 48 by number of packages, drawn from the 140 names used by at least 3 packages. No pin is absent from the corpus.
  - **Merges:** Lambda `P_RAW_LOAD`, `P_RAW_STORE`, `P_BIGARRAY`, `P_BSWAP`; Cmm `C_RUNTIME`, `Cstore_narrow`. `Cload_narrow` still doesn't merge (`Cload_32s` ≥ 1,000).

| | Inventory | Trained entities | Trained vocabulary | Merged away | Fallback-mapped | Impossible |
|---|---|---|---|---|---|---|
| Lambda | 148 | 143 | 127 | 20 | 4 (`Pduprecord`, `Pint_as_pointer`, `Ppoll`, `Psetfloatfield`) | 1 (`Psetglobal`) |
| Cmm | 77 | 68 | 66 | 7 | 5 (`Cload_16s`, `Cload_byte_s`, `Cload_single`, `Cstore_single`, `TUPLE`) | 1 (`RETURN_ADDR`) |

- **Low confidence (< 1,000 triples):**
  - Lambda: 51 trained vectors (67 inventory entities, counting the members of the four merged families). Among them are the effect primitives (`Pperform` 16, `Presume` 20, `Prunstack` 12, `Preperform` 12), which stay unmerged as ruled, plus `Patomic_load` (8), `Pdls_get` (4), and most boxed-integer and float-conversion ops.
  - Cmm: 12, including `C_RUNTIME` (7) and `Cstore_byte_s` (4).
  - The full list with per-entity counts is in `report/entities.tsv`, produced by `ir2vec check entities`.

### Phase 4 results (2026-09-25)

The config is `0806054e15dc…`. Every model uses dim 128, seed 20260925 and 4 threads. The held-out set is the distinct triples of the 5% occurrence split. "Novel" means held-out distinct triples never seen in training.

| Level | Model | Vectors | Epochs (best) | MRR | hits@1 | hits@10 | Novel MRR | Novel hits@10 |
|---|---|---|---|---|---|---|---|---|
| Lambda | ComplEx | 127 | 30 (30) | 0.912 | 0.879 | 0.969 | 0.244 | 0.458 (n=24) |
| Lambda | TransE | 127 | 26 (23) | 0.821 | 0.692 | 0.988 | 0.175 | 0.521 (n=24) |
| Cmm | ComplEx | 66 | 28 (25) | 0.967 | 0.954 | 0.995 | 0.202 | 0.667 (n=6) |
| Cmm | TransE | 66 | 14 (11) | 0.889 | 0.802 | 0.998 | 0.403 | 0.833 (n=6) |

- There are 1,983 distinct held-out triples for Lambda and 859 for Cmm. The novel subsets are tiny (24 and 6), so their metrics are noisy. As expected (D4.8), the overall metrics mostly measure fit to known structure.
- Lambda ComplEx reached the 30-epoch cap while still improving slightly: its MRR went from 0.9102 to 0.9117 between epochs 29 and 30. A higher cap is a cheap follow-up.

**Nearest-neighbour sanity checks** (`report/nn_<level>_<model>.txt`):

| Pair | ComplEx | TransE |
|---|---|---|
| `Paddint ~ Psubint` | 1st, cos 0.83 | 1st |
| `Pmulint ~ Pdivint` | 1st | 3rd |
| `Paddfloat ~ Psubfloat` | 1st | 2nd |
| `Lapply_a1 ~ Lapply_a2` | 1st | 2nd |
| `Caddf ~ Cmulf` | 2nd, cos 0.92 | 1st |
| `Caddf ~ Csubf` | 1st | 2nd |
| `BR ~ SWITCH` | 1st | 5th |
| `Cload_word_val ~ Cload_word_int` | 1st | 2nd |

The float, integer, arity and memory-width families cluster under both models. ComplEx gives tighter clusters.

**Weaknesses to carry into Phase 7:**
- **Low-confidence entities cluster with each other**, not with semantic relatives. `Pperform`'s nearest neighbours are `Patomic_load`, `Pbytes_of_string`, `Preperform` and `Pdls_get`, all under 20 triples. With so few updates, their vectors stay close to initialisation.
- **The Cmm type entities are close to rare opcodes.** Under ComplEx, `INT`'s nearest neighbours are `C_RUNTIME` and `Cstore_byte_s`. The Phase 7 distinctness check should quantify how separated the types are.
- **`Pfield ~ Psetfield` is far apart** (19th under ComplEx, 30th under TransE). That's expected: loads and stores have very different contexts.

**Outputs:** `vocab/{lambda,cmm}.{complex,transe}.json` (entity vectors plus metadata) and `vocab/*.relations.json`. The training logs are in `report/train_<level>_<model>.log`.

### Phase 4 rulings (2026-09-25)

**D4.2 (confirmed): Fallbacks, applied at lookup only.** All four judgement calls are kept: `TUPLE → COPY`, `Pduprecord → Pduparray`, `Ppoll → Pccall` (a poll is an entry into the runtime), and `Pint_as_pointer → Popaque` (placed by co-occurrence: low-level unsafe code). The fallback is applied only when a vector is looked up (`encode/vocab.py`); counts, reports and triples keep the original name. Every use is counted and reported.

**D5.1: Frequency smoothing with `sampling_alpha`.** Training samples distinct triples with probability ∝ count^α (default **0.75**, word2vec's exponent); α = 1 is exactly occurrence sampling. Rare entities (`Pdls_get` has 4 triples, `Paddint` hundreds of thousands) otherwise get effectively no gradient. Smoothing compresses the dynamic range but keeps the order. α is chosen by evidence: α = 1.0 vs 0.75, compared on distinctness and on the rare-family neighbour report (see the Phase 5 α results).

**D5.2: No selection on held-out metrics; stop on a loss plateau.** With 3,928 and 1,189 distinct triples, MRR and hits measure memorisation, and the novel subsets (n = 24, n = 6) carry no weight.
- Selection criteria, in order: distinctness (Phase 7), nearest-neighbour sanity, downstream tasks.
- An epoch is 250 steps × 4,096 samples. Training stops when the loss gains less than 0.1% (relative) over 5 epochs, or at the 60-epoch safety net. The final weights are kept.
- Held-out MRR and hits are computed once at the end, for the record only.
- Each entity's movement from initialisation (‖final − initial‖ / ‖initial‖) is saved in the metadata; it measures "barely trained" directly.

**D5.3: ComplEx is primary**, on geometry (distinctness, clusters), not on link metrics. TransE stays trained and shipped. Corpus growth stops, except to cover missing entities.

## Phase 5: encoders

**D5.4: Lookup rules** (`encode/vocab.py`), in this order:
1. An impossible entity raises `ImpossibleEntity` (hard error).
2. Merge family.
3. Trained vector.
4. Fallback (counted).
5. Otherwise unknown: counted, logged once per entity, reported in the result, and a zero contribution. `ir2vec encode` and `embed` exit non-zero when anything is unknown. A vocabulary trained under a different config (`config_sha256`) is refused.

**D5.5: One engine** (`encode/engine.py`). Every cell reduces a function to X = B + C·X:
- **Components:** Tarjan, iterative and index-ordered, emitting components dependencies-first.
- **Singletons:** computed directly.
- **Cyclic components:** `numpy.linalg.solve` on (I − C_SS) X_S = rhs, all dimensions at once, never rounded.
- **Ill-conditioning:** if cond > 1e12, the Wa-weighted entries are rebuilt with Wa − δ (δ += 0.01), and each retry is logged and reported.
- **Residuals:** reported per function.

**D5.6: `pq.ml` cannot be identical under `lambda_sym`.** BUILD_SPEC expects p and q to be "identical under lambda_sym". They cannot be: q is `let a = x+y in (a-y)*a`, which is an `Llet` node, and schema §1.8 sums every node. With every operand `VAR_INT` either way, q − p equals exactly the `Llet` node's vector (Wo·Llet + Wt·INT + Wa·VAR_INT). The test asserts that equality (to 1e-12) instead. They are distinct under `lambda_fa` (beyond the `Llet` term) and under `cmm_fa`. `cmm_sym` is reported, not asserted: it also differs (‖q − p‖ ≈ 7.4 with ComplEx).

**D5.7: Lambda cells.**
- Value positions only.
- A leaf contributes its operand kind; a child contributes its computed kind (D1.11).
- A record sums the nodes it owns (D1.3).
- `lambda_fa` replaces a leaf's kind with the sum of its defining nodes, when the leaf has def references. Children keep their computed kind: the spec changes only operands with def references.

**D5.8: Cmm cells.**
- **Reaching definitions:** iterative over normal and exceptional edges, only for mutable, join and handler variables. An exceptional edge carries its source block's IN ∪ OUT, because an exception can leave the block before its definitions run.
- **Synthetic COPYs are transparent:** X_copy = A(operand) with weight 1, and they are excluded from sums unless `count_synthetic`.
- **Liveness:** standard backward liveness over normal and exceptional edges. An instruction counts if it is a terminator, has a side effect, or has a live `dst` (D2.15).
- **Pass 2:** per direct local call site (`Capply`, operand 0 `SYM_FUNC` naming a function of the unit), `F += Wc · F_callee(pass 1)`.
- `cmm_sym` uses the same liveness and pass 2, so the two Cmm cells differ only in A_j.

**D5.9: Every fixture is a golden at both levels.** `tests/golden/<fixture>.{lambda,cmm}.json` are dune `diff` rules. The Python encoder tests read them, so `dune test` keeps them in sync with the extractor.

**D5.10: The encoders take vocabulary paths as arguments** (`ir2vec encode --vocab-lambda … --vocab-cmm …`), so every cell runs against either model.

**D5.13: Dump provenance (patch revision 3, dump format 2).**
- The header adds `hooks=3` and `build=<MD5 of the running compiler executable>` (computed once per process).
- The reader requires format 2, hooks revision 3, and `build` equal to the MD5 of the `ocamlopt` the extractor itself was built with.
  - That hash is generated at build time (`extractor/src/gen_build_id.sh` → `Build_id`, a dune rule depending on `%{ocamlopt}`), so rebuilding the compiler regenerates it.
  - `Config.bindir` couldn't be used: it is empty in 5.5's relocatable install, and the first attempt failed on exactly that.
  - `ocamlopt` is a symlink to `ocamlopt.opt`, so the content hashes agree.
- `phase0_dumps.sh` checks the header fields, and that a dump with a forged `build` is rejected.
- Format-1 dumps (the existing corpus) are readable only with `--legacy-format-1`, which is needed only to re-extract that corpus; its JSON is already extracted.
- `build_corpus.sh` compiles a canary before the run and after every package, and requires the strict reader to accept its dump. A stock compiler writes no dumps, which the canary now distinguishes from a package with no units.

### Phase 5: α experiment results (2026-09-25). Decision: α = 0.75

**Setup:** 8 runs, α ∈ {1.0, 0.75} × {ComplEx, TransE} × {Lambda, Cmm}, same seed and config. Every run stopped on the loss plateau (16–40 epochs), never at the 60-epoch safety net. Full tables: `report/alpha/distinctness.md` (`ir2vec check distinctness`), plus `report/alpha/a*/nn_*.txt`.

**Distinctness** (within-group ÷ all-pairs cosine distance; the flag is < 0.1):

| ComplEx, groups | α = 1.0 | α = 0.75 |
|---|---|---|
| Lambda `Lapply_a*`, `Lfunction_a*`, `Pgetglobal_*` | 0.530, 0.372, 0.270 | 0.516, 0.341, 0.262 |
| Lambda types, operand kinds | 0.826, 0.688 | 0.645, 0.633 |
| Cmm `Cload_*`, `Cstore_*` | 0.652, 0.362 | 0.632, 0.405 |
| Cmm types, operand kinds | 0.966, 0.909 | 0.847, 0.811 |

- No group is flagged in any run, including TransE, whose scores are 0.50–0.94.
- Smoothing lowers the separation of the types and operand kinds (they are tails of very frequent triples), but they stay 6–8× above the flag.

**Rare families** (ComplEx; lower cohesion means more collapsed):
- **Low-confidence cohesion** (mean pairwise distance among low-confidence entities ÷ all pairs): Lambda 0.516 → **0.690**, Cmm 0.344 → **0.469**.
- **Neighbour cosines** for the effect primitives, atomics and `Pdls_get` fall from 0.80–0.89 to 0.58–0.82. `Presume` gains a non-rare neighbour (`ADDR`), and `Cstore_byte_s` gains `Cstore_narrow`, its own semantic family.
- **Most rare entities still have mostly-rare neighbours**, so the collapse is reduced, not removed.

**Mechanism: "barely moved" is not the cause.** Movement from initialisation is about the same for rare and common entities (ComplEx 4.51 vs 4.69 at α = 1.0; TransE 0.71 vs 0.84). Rare entities move substantially, but into a *shared* region. The likely driver is negative sampling: a rarely-positive entity is mostly seen as a corrupted negative, so all such entities receive the same push. This also explains why more epochs would not help.

**Common clusters are preserved:** `Paddint ~ Psubint`, `Pmulint ~ Pdivint`, `Lapply_a1 ~ Lapply_a2`, `Cload_word_val ~ Cload_word_int` and `BR ~ SWITCH` are all rank 1 or 2 under both settings. `Ccmpi ~ Ccmpa` improves from 7th to 4th.

**Decision.** Distinctness is a collapse check, and both settings pass it. Nearest-neighbour sanity then decides, and it favours **α = 0.75**: less rare-entity collapse, with every common cluster kept. The α = 0.75 vocabularies are now `vocab/{lambda,cmm}.{complex,transe}.json`, and both settings are kept under `vocab/exp/`. Held-out MRR happened to be higher at α = 0.75 too, but it was not used (D5.2).

**Open (not acted on):** type-constrained or frequency-aware negative sampling would address the mechanism directly. It is left for a later decision.

**D5.13 (applied, 2026-09-25):** the switch was rebuilt with patch revision 3 (54 added lines).
- `check_objects.sh` still reports object files identical to stock, so the hooks don't perturb code generation.
- `dune test` and `pytest` (68) pass, and the build-script canary passes.
- Legacy format-1 corpus dumps are rejected without `--legacy-format-1` and accepted with it.
- The already-extracted corpus JSON is unaffected, so no re-dump was needed.

### Phase 5 rulings (2026-09-25)

**D5.6 (supersedes a BUILD_SPEC acceptance item).** The Phase 5 item "`pq.ml`: the two functions are identical under `lambda_sym`" is replaced by: *q − p under `lambda_sym` equals exactly q's `Llet` node vector, to 1e-12.* p and q do not have the same node multiset, so identity was never the correct prediction. The replacement is also stronger: it checks that Symbolic ignores dataflow *and* that nothing else leaks in. The summation rule is unchanged. Binding nodes (`Llet`, `Lmutlet`) are real content, and they stay in the sums.

**D5.14: The rare-entity collapse is a known limitation, not acted on.** The mechanism (uniform negative sampling pushes rarely-positive entities into a shared region) and the displacement evidence (4.51 vs 4.69) are written up in REPORT.md. Type-constrained negative sampling is the first thing to try once a downstream task exists to score it. Tuning against nearest-neighbour inspection alone would overfit to intuitions.

**D5.15: The corpus stays at dump format 1.** It is not re-dumped. `--legacy-format-1` stays working and tested (`phase0_dumps.sh`: rejected without the flag, accepted with it, extraction identical to format 2). The next full corpus rebuild re-dumps under revision 3. REPORT.md states what the format-1 corpus does and does not guarantee.

## Phase 6: `ir2vec embed`

**D6.1: Inputs.**
- **A single `.ml` file.** A sibling `.mli` is compiled first. `--package P` (repeatable) is passed to `ocamlfind ocamlopt -c -package …`.
- **A dune project.** It is built from a fresh copy (excluding `_build`, `_opam`, `.git`) with `dune build --root .`. `--install-deps` first runs `opam install --deps-only` from the project's `*.opam`. The switch invariant (D4.11) keeps that from touching the compiler.
- Compilation runs in the `ir2vec` switch with `IR2VEC_DUMP_DIR` set and `DUNE_CACHE=disabled`. No dumps is an error pointing at the compiler (the canary's check).
- Every dump is extracted with the strict (format 2) reader.

**D6.2: Alignment** (`python/ir2vec/align.py`). Per unit, in this order:
1. `module_init` ↔ `<prefix>.entry`. BUILD_SPEC's `caml<Unit>__entry` is `caml<Unit>.entry` on 5.5.1, and packed units prefix the pack path (`camlOcamlbuild_pack.Bool.entry`). The function name is always the text after the last `.`.
2. Named functions ↔ the Cmm name's trailing `_<stamp>`.
3. Remaining functions (anonymous, or named without a stamp match) ↔ the unique unmatched Cmm function with the same source location.
4. Then ↔ the unique unmatched Cmm function whose parameter stamps include all of the Lambda ones (closures add an environment parameter).

An ambiguous candidate set is never guessed; the function stays unmatched.

**Corpus results** (`ir2vec check alignment` → `report/alignment.{json,tsv}`):

| | Count |
|---|---|
| Lambda functions | 63,363 |
| Matched | 63,265 (**99.85%**) |
| … entry / stamp / location / params | 1,829 / 43,794 / 15,455 / 2,187 |
| Unmatched Lambda: named / anonymous / `module_init` | 9 / 89 / 0 (probably inlined away by closure conversion) |
| Cmm-only: synthesised closures / optional-argument inner / other | 6,219 / 1,359 / 0 |

- Synthesised closures are closure conversion's `fun_<N>` functions (eta-expansions, wrappers). Optional-argument inner functions are `*_inner_<N>`.
- **Cross-check of the fragile path:** for all 43,794 stamp matches and all 15,455 location matches, the Lambda parameter stamps are included in the Cmm ones. There are **0 disagreements**.
- `report/alignment.tsv` lists every unmatched function by package, unit, side, category and location.

**D6.3: Unaligned functions are embedded, not dropped.** A Lambda-only or Cmm-only function keeps zeros in the missing level's blocks. It is tagged `category` (`aligned`, `lambda_only:<named|anonymous|module_init>`, `cmm_only`) with `aligned: false`. The module vector sums every function of the unit, which by construction is schema §1.8's module vector at the Lambda level.

**D6.4: The final vector has 438 dimensions**, asserted in the output (`metadata.dims`) and by tests:
- `L2(lambda_sym)`: 128
- `L2(cmm_fa)`: 128
- `log1p(counts_lambda)`: **95** (the inventory's 30 fixed features, then the frozen 64-name whitelist, then `EXT_OTHER`)
- `log1p(counts_cmm)`: **83** (18 fixed features, the same 64-name whitelist, then `EXT_OTHER`)
- `log1p(node_counts)`: 4 (`lambda_nodes`, owned; `cmm_instructions`, excluding synthetic COPYs; `cmm_blocks`; `cmm_counted`, live per D2.15)

The feature names are listed in `metadata.count_features`. An extern outside the whitelist goes to `EXT_OTHER`, and an unknown count feature is an error.

**D6.5: Output.** JSON by default (to stdout or `-o FILE`). `--format npy -o DIR` writes `functions.npy` (N × 438), `modules.npy` (M × 438) and `index.json` (row → unit, fid, Cmm name, alignment, location, plus metadata). The metadata records the vocabulary paths, SHA-256s, models and α, the config hash, the weights and the dimensions.

**D6.6: Exit codes.** 0 on success; 1 if there are unknown entities (without `--allow-unknown`; lookups are counted per cell, so one missing entity shows up once per Lambda or Cmm cell that looks it up); 2 on a build or extraction failure; 3 on an impossible entity.

**D6.7: Test project** `tests/embed_project` (excluded from the repo's own dune build through `data_only_dirs`): a `wordcount` library depending on `re`, plus an executable. `embed --install-deps` builds it in about 30 s: 2 units, 14/14 functions aligned, 0 unknown lookups.

### Phase 6 rulings (2026-10-01)

**D6.3 (confirmed): Unaligned functions stay as flat, tagged rows.** Folding Cmm-only closures into a parent is an aggregation choice for the downstream task. The encoder doesn't make it.

**D7.1: The parent link is metadata, never folding.** Every Cmm-only row carries two fields:
- `parent_cmm`: the unique *other* Cmm function whose code refers to its symbol, i.e. a closure's allocator or an `*_inner` function's wrapper (`align.cmm_parents`).
- `parent_fid`: the Lambda fid aligned to that parent.

Both are null when there is no unique referrer (for example a static closure in data, or several referrers). Null is an honest answer.

On the corpus, of the 7,578 Cmm-only functions:
- 6,576 (86.8%) get a Lambda `parent_fid`;
- 279 get only a `parent_cmm`, because the referrer is itself Cmm-only;
- 723 get neither.

**D6.8: The module vector sums all rows, including the Cmm-only ones.** At the Lambda level this is schema §1.8. At the Cmm level, dropping synthesised closures would under-represent closure-heavy code, which is exactly the OCaml-specific signal worth keeping. Consequences, also stated in REPORT.md:
- The module's cells equal the sum of **all** of the unit's rows: aligned, Lambda-only and Cmm-only. They do **not** equal the sum of the aligned rows alone.
- The module's `final` is not the sum of the rows' `final`s, because the L2 and log1p transforms apply after summing.

**D6.9: Symbol naming is a convention, not an API.** Alignment relies on 5.5.1's symbol conventions:
- `caml<Unit>.<name>_<stamp>`, with `.` rather than `__`, and a pack-path prefix for `-for-pack` units;
- `<prefix>.entry`;
- `fun_<N>` for synthesised closures;
- `<name>_inner_<N>` for optional-argument inner functions.

These are compiler conventions, like the stamps (D1.6), and must be rechecked after any version bump. `test_phase6.py` covers the entry and packed-prefix forms, so a change fails loudly.

## Phase 7: checks and report

**D7.2: `ir2vec check encode`** runs all four cells over every selected unit with the shipped vocabularies. It gives the corpus-scale inference numbers (unknown, fallback and impossible lookups; cyclic components, residuals and retries; non-finite vectors) in `report/encode_check.<model>.json`, and exits non-zero on any unknown, impossible or non-finite result.

**D7.3: `ir2vec check distinctness`** implements schema §4 and BUILD_SPEC Phase 7: per level and sibling group, the mean within-group cosine distance ÷ the mean over all entity pairs, flagged below 0.1, with ComplEx and TransE side by side (`report/distinctness.md`). The same command also reports the rare-family neighbours and the low-confidence cohesion ratio (D5.1).

**D7.4: Not done: schema §4's tail-call folding experiment** (splitting `Lapply_aK` into tail and non-tail variants and keeping the split only if it passes distinctness). It isn't in BUILD_SPEC's phase list. Tail position stays a count feature (`TAIL`/`NONTAIL`).

## Phase 8: visualisation and geometry evidence

**D8.0: Category map (`config/categories.json`)**, final after review (2026-10-01). Categories are for display only, in display order: **15 for Lambda, 12 for Cmm**.
- Every inventory entity and every merge-family name is in exactly one category per level. `python/ir2vec/categories.py` loads the map and rejects duplicates, and `tests/test_phase8.py` asserts coverage of the inventory, the merge families and the trained vocabularies.
- Members of merged families are listed under their family's category for completeness, but plotted only through the family vector.
- A `status` map marks `Cload_narrow` as **unused**: the family did not merge (`Cload_32s` has ≥ 1,000 triples), so it has no vector. A test ties the status to the frozen merges.

**Rulings applied (changes to the proposal):**
1. New **conversions** category: Lambda `Pintoffloat`, `Pfloatofint`, `Pbintofint`, `Pintofbint`, `Pcvtbint`; Cmm `Cfloatofint`, `Cintoffloat`. `Pbytes_to_string`/`Pbytes_of_string` stay in strings and bytes.
2. `Poffsetref` → blocks and records.
3. New Lambda **runtime intrinsics** category: `Ppoll`, `Patomic_load`, `Pdls_get`. Atomics are kept out of effects, because that membership would be confounded with rarity. misc keeps `Pignore`, `Popaque`, `Pint_as_pointer`, `Pctconst`.
4. "comparisons" is renamed **comparisons and tests** at both levels.
5. `Cload_narrow` is marked unused instead of being dropped.

**Confirmed as proposed, and stated on every caption (`common.CATEGORY_NOTES`):**
- `Praise` is a control form (Lambda) while `Craise` is runtime (Cmm): a level asymmetry.
- `P_BSWAP` is in int arithmetic and `P_BIGARRAY` in arrays.
- The merged `P_RAW_LOAD`/`P_RAW_STORE` sit in strings and bytes, though they span strings, bytes and bigstrings.

**D8.1: What is plotted (spec corrections A and B).**
- Only entities with their own vector appear in §8.1, §8.2 and §8.4, as points, matrix rows or neighbours.
- Fallback-mapped (4 Lambda, 5 Cmm) and impossible (1 per level) entities are never plotted. Each figure's .tsv lists them with the fallback target, and the caption states the counts (`LevelVocab.caption`).
- Merged members and unused families are listed the same way.
- Low-confidence vectors are drawn hollow.
- Each level gets a **rarity control panel**: all plotted entities coloured by log10 training triples, ignoring category (`seeds_<level>_<model>_rarity`).

**D8.2: Seed-scatter conventions.**
- **Per-panel PCA.** Each comparison panel fits its own 2-component PCA (numpy SVD) on the points it plots. The all-entities facet grid and the rarity panel share one PCA over all entities.
- **Sign convention.** The largest-|loading| of each component is made positive.
- **Honesty annotations.** Titles give PC1, PC2 and the total explained variance. Each named group is labelled with its full-dimensional distinctness d and member count.
- **Colour.** Categorical slots 1–3 only (blue, orange, aqua; all-pairs CVD-validated for scatter). Anything else in a panel is a grey context layer.
- **All-entities view.** With 12–15 categories this is a facet grid (one facet per category over the grey rest) rather than 15 hues.
- **Loads vs stores (Cmm).** Hue = load/store; the chunk is encoded as marker shape, so hue never carries more than two classes.
- **Extra panel.** A "conversions vs int vs float" panel was added at both levels. It is the counterpart of IR2Vec Figure 6(d) and was made possible by ruling 1.

**D8.3: Canonical figure environment and determinism.**
- **Environment.** Figures are generated in the ir2vec venv (WSL) with matplotlib 3.11.2 and numpy 2.5.3. The versions and every output's sha256 are written to `report/figures/MANIFEST.tsv`.
- **SVG byte stability.** SVGs are byte-identical on regeneration: `svg.hashsalt` is fixed, and the Date/Creator/Software metadata is removed. A test regenerates a heatmap and a seed panel and compares the bytes.
- **Scope.** Byte identity is claimed within one environment, not across matplotlib versions.
- **Why the PNGs are byte-stable, and why it survives an upgrade.** The mechanism is explicit metadata in `common.save`, not `SOURCE_DATE_EPOCH` (which is not set).
  - matplotlib's PNG writer adds only a `Software` key (it carries the matplotlib version) and writes no timestamp unless one is supplied. We pass `metadata={"Software": None}`, so a PNG carries no version or date.
  - For SVG, `Date: None` and `Creator: None` replace the timestamp path, which is the one that would otherwise read `SOURCE_DATE_EPOCH`. `svg.hashsalt` fixes element ids.
  - `test_figures_are_byte_identical_on_regeneration` regenerates PNG and SVG and asserts identical bytes. It also asserts that neither a version string nor a date is present, so a matplotlib upgrade that adds a new default key fails the test instead of silently breaking the property.
  - What can still change across versions is the rendering itself (antialiasing, font layout); hence the single-environment scope.
- **Dependencies.** No new ones: numpy and matplotlib were already declared. There is no sklearn, t-SNE or UMAP: PCA is the only projection (t-SNE/UMAP were optional in the spec), and the probe is numpy logistic regression.

**D8.4: Heatmap and neighbours.**
- The heatmap is the full-dimensional cosine matrix, ordered by category display order then name, with boundaries drawn. The .tsv records the order and the full matrix.
- The title gives mean within- vs between-category cosine.
- Neighbours: top-3 by cosine, with ties broken by name. The headline is the top-1 same-category rate against its chance rate: the mean over entities of (category size − 1)/(N − 1).

**D8.5: Analogy test protocol.**
- **Statistic.** cos(b − a, d − c) for each specified quadruple.
- **Primary null (as specified).** 10,000 random quadruples of 4 distinct entities from the same vocabulary, `default_rng(8005)`. The percentile is the share of null draws strictly below the observed value, with ties counted half.
- **Decision rule (fixed before looking).** A quadruple "holds" when it is above the Bonferroni-corrected null percentile 100·(1 − 0.05/k), with k = testable quadruples at that level. Above the 95th percentile but not the corrected one is reported as such. Otherwise it "does not hold".
- **Untestable quadruples.** A quadruple containing a fallback-mapped entity is untestable and reported as such. It is never scored through the fallback target, whose difference vector would be degenerate. This covers `(Cload_byte_u, Cload_byte_s)` vs `(Cload_16u, Cload_16s)`.
- **Addition: category-matched null**, reported beside the verdict and not replacing it. The random-pair null cannot tell a relation offset from two pairs that merely join the same two clusters. The matched null draws each position from the tested entity's own category (2,000 draws). A quadruple that is not above it is explained by category membership alone. cos(a, c) and cos(b, d) are recorded too.
- **Ruling (2026-10-01): the matched null stays a side column, not part of the pass rule.**
  - The pass rule was fixed before looking, which is what makes the two passes credible. Changing it afterwards would cost that, even with no verdict moving.
  - The two nulls answer different questions: "is the offset non-random?" vs "is it more than category membership?". Folding them into one verdict would have hidden the load → store diagnosis: 91.6th percentile on the random null, explained away by the matched one.
  - The matched-null percentile is a **required** column: the .tsv, the figure and the REPORT table always carry it, and a test asserts it for every testable quadruple.
  - REPORT §13.2 states the one-line reading rule: ≥ 95 means more than category membership; < 95 with a high random-null percentile means explained by category membership alone.

**D8.6: Function-level projection.**
- **Plotted vector.** L2(lambda_sym) ⊕ L2(cmm_fa), 256-D only. `functions.draw` and `probe.run` assert the width.
- **Rows.** Aligned functions of the selected corpus; unaligned rows are counted, not used.
- **module_init rows are excluded** (ruling 2026-10-01): 1,829 of them, one per unit. They are aligned, contrary to my first assumption, but excluded anyway.
  - **Why.** It is top-level initialisation code, not a function anyone wrote.
  - **Measured.** `Pgetglobal_self` + `Lsequence` + `Psetfield` make up 52% of module_init's Lambda nodes (stores into the module block), against about 5% `Pgetglobal_self` in functions, where the other two are not in the top 8. module_init also holds a third of all Lambda nodes (429k vs 861k).
  - **Effect if included.** It would pull the PCA toward a structure that says nothing about functions.
  - **Where it is stated.** The figure caption and the .tsv.
  - **Possible extension.** A separate module-init panel, showing how units differ in their initialisation work, was not built.
- **Labels are read from the IR, not the vector:**
  - recursive: Lambda `CALL_SELF` > 0.
  - allocating: an owned `Pmakeblock`/`Pmakearray` node or a `Calloc`.
  - arity: the signature block, with 3 and 4P merged into "≥3" to fit three slots.
  - effects: an owned effect primitive.
  - package: the 3 largest in the sample, plus grey.
- **Caveat on the allocating and effects labels.** Their opcodes are learned entities, so they are partly visible by construction. Recursion and arity are not entities.
- **PCA and sampling.** PCA is fitted on every row. The plot shows a deterministic sample: sha256(package/unit/fid)[:12] mod m = 0, with m chosen for ≤ ~4,000 points and recorded.
- **Cache.** The matrix is cached under `$IR2VEC_CORPUS_DIR/cache/`, keyed by the vocabulary hashes.

**D8.7: Linear probe.**
- **Model.** numpy Newton/IRLS logistic regression. Ridge 1.0 on the weights (not the bias). Standardisation is fitted on each training fold.
- **Folds.** 5-fold stratified, with folds assigned by the row-key hash.
- **Reported.** AUC mean ± std; accuracy vs the majority-class baseline; a shuffled-label control (labels permuted with seed 8007, same folds).
- **Two further controls (added after the first run showed recursion at AUC 0.97, since recursion is not an entity):**
  - **size only:** the same probe on log1p(Lambda node count) alone, measuring how much of a property is just function size.
  - **package-grouped folds:** whole packages assigned to folds, largest first, each to the smallest fold, so near-duplicate code cannot straddle train and test. Folds lacking a class are skipped and counted.
- **Minimum class size.** A property with fewer than 10 examples in the minority class is reported as "too few" and not probed.
- **Tasks.** recursive, allocating, uses effects, arity ≥ 2 (rows with a signature).
- **Excluded.** Package is not probed: it measures style, not semantics.

**D8.8: CLI.**
- `ir2vec figures {seeds|heatmap|distinctness|neighbours|analogy|functions|probe|all} [--model complex|transe|both] [--vocab-lambda F --vocab-cmm F] [--corpus DIR] [--out-dir DIR]`.
- `probe` is a separate target from `functions`.
- The two `--vocab-*` flags go together and must be the same model.
