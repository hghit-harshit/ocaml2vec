# BUILD SPEC — OCaml IR2Vec: program embeddings from Lambda and Cmm

You are building a complete, working pipeline that produces IR2Vec-style vector embeddings for OCaml programs. **Read this whole document, plus the two schema docs it references, before writing any code.** Work in phases, and stop at the end of each one (see "Working rules").

---

## 1. Context

IR2Vec (VenkataKeerthy et al., ACM TACO 2020) embeds LLVM IR in two stages:

1. **Offline (once).** Flatten the IR into `(head, relation, tail)` triples over a small, finite set of entities. Train a knowledge-graph (KG) embedding model on the triples, and keep the entity vectors as a *seed vocabulary*.
2. **Online (every program).** Look up the seed vectors and compose them into instruction, then function, then program vectors, using weighted sums guided by dataflow analysis. No learning happens at this stage.

We are doing the same for OCaml, at two levels of the native compiler's pipeline:

| Level | IR | Encoding |
|---|---|---|
| 1 | **Lambda**, taken after `Simplif.simplify_lambda` | **Symbolic** |
| 2 | **Cmm**, taken after `Cmmgen.compunit`, lowered to three-address code (TAC) + a control-flow graph (CFG) | **Flow-Aware** |

**Source of truth:**

- **`docs/ocaml-ir2vec-schema.md`** is the authoritative spec: every entity, relation, `Type`-emission rule, count feature, lowering rule and worked example. Follow it exactly.
- **`docs/ocaml-ir2vec-entities-relations.md`** is a short summary of the same material.

If the pinned compiler disagrees with the schema (for example, a constructor that was added, removed or renamed), **stop and report the difference.** Don't improvise.

**Definition of done.** Running `ir2vec embed some_file.ml` on a new program outputs one vector per function and one per module, built from seed vocabularies trained on a corpus of real OCaml packages. All phase acceptance tests must pass.

---

## 2. Hard constraints

1. **Do not write an OCaml lexer, parser or type checker.** The compiler's front end does all of that; we intercept its IR.
2. **Do not parse `-dlambda` / `-dcmm` text.** Get the IR as OCaml values.
3. **Use the non-flambda compiler path only.**
4. **Pin one OCaml 5.x release:** the latest stable release available in opam, which must be ≥ 5.0. Record it in `VERSIONS.md`.
5. **Check every `compiler-libs` API you call against that version's installed `.mli` files.** Don't guess signatures from memory; they change between releases.
6. **Make every constructor→entity mapping an exhaustive pattern match with no wildcard,** and compile with warning 8 as an error. A constructor missing from the mapping must break the build.
7. **Training and inference must share one abstraction code path.** Entity names get defined in exactly one place.
8. **No silent fallbacks.** An unknown entity at inference is counted, logged and reported. Never quietly substitute a zero vector.
9. **Be deterministic.** Fix every seed. The same input must produce byte-identical vectors.
10. **Stay in scope.** No downstream task models, no GNNs, no flambda, no memory alias analysis. The schema's "v2" items are out of scope.

---

## 3. Architecture

```
 .ml ──► patched ocamlopt (switch "ir2vec")
            │  Hook A: Marshal Lambda.program   → <unit>.lambda.bin
            │  Hook B: Marshal Cmm.phrase list  → <unit>.cmm.bin
            ▼
 ir2vec-extract (OCaml, same switch's compiler-libs)
            │  Lambda → abstracted node JSON
            │  Cmm → TAC + CFG → abstracted JSON
            ▼
 python ir2vec
   stats / freeze-config  (extern whitelist, rare-family merges; frozen & versioned)
   triples                (schema relations, duplicates kept)
   train                  (ComplEx primary, TransE baseline) → seed vocabularies
   encode                 (lambda_sym, lambda_fa, cmm_sym, cmm_fa)
   embed                  (new program → vectors)
   check                  (plateau, distinctness, alignment)
```

**Division of work:**

- **OCaml** handles everything that needs `compiler-libs`: the hooks, extraction, Lambda abstraction, Cmm→TAC lowering, and JSON output.
- **Python** handles corpus-level vocabulary decisions, triple generation, training, dataflow analysis (reaching definitions, strongly connected components (SCCs), linear solves, liveness), encoding, metrics and the CLI.

**Repository layout:**

```
ocaml-ir2vec/
  README.md  VERSIONS.md  DECISIONS.md  REPORT.md
  docs/ocaml-ir2vec-schema.md  docs/ocaml-ir2vec-entities-relations.md  docs/BUILD_SPEC.md
  compiler-patch/            ir2vec-hooks.patch, make_switch.sh
  extractor/                 dune project: bin/ir2vec_extract.ml, src/{lambda_abs,cmm_lower,cmm_abs,json_out}.ml
  config/                    weights.json, vocab_config.json (frozen)
  corpus/                    packages.txt, exclude.txt, build_corpus.sh
  python/                    pyproject.toml, ir2vec/{cli,stats,config,triples,train,encode/,align,embed,metrics}.py
  tests/fixtures/            fact.ml align.ml pq.ml counter.ml evenodd.ml effects.ml exn.ml closures.ml
  tests/golden/              expected JSON / triples
  vocab/                     trained seed vocabularies + metadata
```

---

## Phase 0 — Environment and compiler hooks

1. Install opam if it's missing. Obtain the pinned release's source and apply `compiler-patch/ir2vec-hooks.patch`. Build an opam switch named `ir2vec` from the patched source, for example by pinning `ocaml-variants` to the local tree. Script the whole thing in `make_switch.sh`.
2. Write the patch. Keep it minimal, and have it do nothing unless the env var `IR2VEC_DUMP_DIR` is set.
   - **Hook A:** in `driver/optcompile.ml`, non-flambda branch, immediately after `Simplif.simplify_lambda`. `Marshal` the `Lambda.program` (with the simplified code) to `$IR2VEC_DUMP_DIR/<unit>.<source-digest>.lambda.bin`.
   - **Hook B:** in `asmcomp/asmgen.ml` (`end_gen_implementation`), between `Cmmgen.compunit` and `compile_phrases`. `Marshal` the `Cmm.phrase list` to `….cmm.bin`.
   - **Header:** prefix each dump with a small header recording the format version, the OCaml version, the unit name and the source path.
3. **Fallback:** if `Marshal` fails because the IR contains functional or custom values, write a serializer for exactly the fields needed instead, and log the change in `DECISIONS.md`.

**Acceptance:**

- `IR2VEC_DUMP_DIR=/tmp/d ocamlfind ocamlopt -c tests/fixtures/align.ml` writes both dumps.
- A small test executable built in the same switch unmarshals both dumps and prints per-constructor counts.
- With `IR2VEC_DUMP_DIR` unset, nothing is written.
- Object files for 3 fixtures are identical to those from a stock switch of the same version. If you can't set up a stock switch, say so.

---

## Phase 1 — Extractor: Lambda → `<unit>.lambda.json`

Implement schema §1. Key rules:

**Nodes:**

- **Instructions vs leaves:** every non-leaf node is an instruction. `Lvar`, `Lmutvar` and `Lconst` are leaves.
- **Transparent nodes:** skip `Levent` and `Lifused`, descending straight to the child.
- **Positions:** follow the positions table in schema §1.1. Each position carries a role, `value` or `control`.

**Opcode entities:**

- **Arity composites:** `Lapply_a1..a3`, `Lapply_a4p` by argument count; `Lfunction_a1..a3`, `Lfunction_a4p` by parameter count.
- **Globals:** split `Pgetglobal` into `Pgetglobal_self` / `_stdlib` / `_other`, per schema §1.2.
- **`Type` emission:** follow schema §1.4 exactly. Implement it as one exhaustive function returning `Fixed ty | Instance … | NoType`.

**Operand kinds:**

- **Leaves:** follow schema §1.3. Type variables from an environment mapping each `Ident` to its `value_kind`, filled from `Llet`/`Lmutlet` bindings, `Lfunction` parameters and `Lstaticcatch` parameters. Anything else is `VAR_GEN`.

**Function records:**

- **Nested closures:** every `Lfunction` is its own function record. The parent keeps the `Lfunction` node itself but none of its body nodes.
- **Top-level code:** goes into a `module_init` record.
- **Naming:** an `Lfunction` bound directly by `Llet`/`Lletrec` is *named*, taking the identifier's name and stamp (from a public API such as `Ident.unique_name`; verify which exists). Otherwise it's *anonymous*. Record the source location from the node's `loc`.

**Count features:**

- **Tail position:** compute it during the traversal: a function body is in tail position; let bodies, if branches and the second part of a sequence inherit; operands and try-bodies do not. **Do not use `ap_tailcall`.**
- **Callee kind:** use the rules table in schema §1.7.
- **Everything else:** counts per schema §1.7. Emit extern names *raw* as `EXT:<native name>`, using `Primitive.native_name`; Python applies the whitelist later.

**Def references** (needed by the Lambda-FA control encoder):

- **`Lvar x` bound by a let:** reference the defining expression's head node, if it's a non-leaf in the same function.
- **`Lmutvar x`:** reference every `Lmutlet`/`Lassign` in the function that defines `x`. This is deliberately conservative.
- **Otherwise:** `null`.

**JSON shape (sketch):**

```json
{"unit":"Align","source":"align.ml","ocaml":"5.x.y",
 "functions":[{"fid":"fact/267","name":"fact","kind":"named","loc":{"file":"align.ml","l1":1,"c1":13,"l2":1,"c2":55},
   "nodes":[{"id":0,"op":"Lfunction_a1","type":"INT",
             "positions":[{"i":0,"role":"control","child":1}]},
            {"id":3,"op":"Pintcomp","type":"INT",
             "positions":[{"i":0,"role":"value","leaf":"VAR_INT","def":null},
                          {"i":1,"role":"value","leaf":"CONST_INT","def":null}]}],
   "cases":{}, "counts":{"CALL_SELF":1,"NONTAIL":1,"PRED_LE":1}}]}
```

**Acceptance:**

- A golden JSON snapshot for `fact.ml` and `align.ml` matches.
- The build fails if any `Lambda.primitive` or `Lambda.lambda` constructor is unmapped.
- `effects.ml` produces `Pperform` / `Presume` / `Prunstack` nodes.
- In `align.ml`, the anonymous function is recorded as anonymous, with its location.

---

## Phase 2 — Extractor: Cmm → TAC + CFG → `<unit>.cmm.json`

Implement schema §2.1–§2.4. Key rules:

**Lowering:**

- **Operands:** each `Cop` becomes exactly one TAC instruction with atomic operands. Non-atomic arguments are lowered first into fresh temps, evaluated **right-to-left**: the native backend's own order (`asmcomp/selectgen.ml`, `emit_parts` / `emit_parts_list`: "force right-to-left evaluation order") and the order of schema §2.9. Operand lists keep source order. See DECISIONS.md D2.2.
- **Control constructs:** use the schema §2.1 table for `Clet`, `Clet_mut`/`COPY`, `Cassign`/`ASSIGN`, `Cifthenelse`/`BR`, `Cswitch`/`SWITCH`, `Ccatch` (one block per handler), `Csequence`, `Ctuple`, `Creturn_addr` and `RET`.
- **`Cexit`:** emit explicit `COPY`s into the handler's parameters, then `JUMP`.
- **`Ctrywith`:** in v1, add edges from every block of the body to the handler.
- **Mutable variables:** handle `Cvar_mut` if it exists in the pinned version. If it doesn't, track mutable variables through `Clet_mut`.

**Opcode entities:**

- **Split `Cload` / `Cstore` by `memory_chunk`** into the 11 + 11 composites of schema §2.2.
- **Add the 8 structural opcodes.**
- **`Type` emission:** follow schema §2.4.

**Operand kinds:**

- **Variables:** `VAR_<machtype>`. Track machtypes from parameters, `Clet_mut`, handler parameters and the defining instruction's `Type`; default to `VAL`.
- **Constants:** `CONST_*`.
- **Symbols:** `SYM_FUNC` / `SYM_DATA` / `SYM_EXTERN`, classified against the unit's own `Cfunction` and `Cdata` symbols.

**Per-instruction fields:**

- **`dst`:** the variable the instruction defines, or null.
- **`operands`:** each with a kind, plus a variable name where it has one.
- **`side_effect`:** true for all `Cstore_*`, `Capply`, `Cextcall`, `Craise`, `Ccheckbound`, `Cpoll` and `Catomic_fetch_add`.

**Per-block fields:** `succ`, the list of successor blocks.

**Per-function fields:**

- **`params`** and **`mutable_vars`**.
- **Counts:** per schema §2.7, with raw `EXT:` names.
- **Identity:** the symbol name and the location from `fun_dbg`. Verify field names against the installed `cmm.mli`.

**Acceptance:**

- **Lowering invariants:** each `Cop` becomes exactly one instruction; each block ends in exactly one terminator; every variable use is a parameter, a handler parameter, or has at least one definition in the function.
- **Golden test:** the lowered TAC for `fact.ml` matches schema §2.9, modulo temp names.
- **Call shapes:** in `align.ml`, `fact`'s self-call has operand 0 = `SYM_FUNC`, and `use` contains two indirect `Capply`s whose callee is a loaded variable (because `twice` was inlined).

---

## Phase 3 — Corpus, vocabulary config, triples (Python)

1. **`corpus/build_corpus.sh`:** in the `ir2vec` switch, `opam install` each package in `packages.txt` with `IR2VEC_DUMP_DIR` set, then run `ir2vec-extract` on every dump.
   - Start with about 20 pure-OCaml packages that install cleanly on the pinned version, chosen by you.
   - Log failures and skip them.
   - Honour `exclude.txt`, which lists future evaluation benchmarks.
2. **`ir2vec stats`:** the frequency of every opcode, operand kind and extern name, per level.
3. **`ir2vec freeze-config`** writes `config/vocab_config.json` containing:
   - **the extern whitelist:** the top 64 native names by frequency, shared by both levels;
   - **rare-family merges** per schema §1.6 / §2.6: merge a family only if *every* member is below a threshold (default 1,000 triples);
   - **provenance:** a hash of the corpus and the config version.

   The config is **never recomputed implicitly**; it changes only when this command is rerun explicitly.
4. **`ir2vec triples --level lambda|cmm`** generates triples per schema §1.5 / §2.5, applying the frozen config. **Keep duplicate triples**, because frequency is signal. Output a TSV of `head, relation, tail` plus a summary.
   - **Lambda:** `Type`; for each position, `Arg_i` for a leaf or `Child_i` for a non-leaf child, with positions ≥ 4 mapped to `Arg4+` / `Child4+`; `Case` for each switch arm.
   - **Cmm:** `Type`; `Arg_i` for each operand; `Next` within a block; `Succ` from each terminator to the first opcode of each successor block.
5. **`ir2vec check plateau`:** the cumulative entity count against the number of packages, as CSV and PNG.

**Acceptance:**

- The golden triples for `fact.ml` match schema §1.9 and §2.9.
- The entity counts per level are reported and compared against the schema (151 / 78 before merges).
- The plateau plot is produced.

---

## Phase 4 — Training

- **Models:** ComplEx is primary; TransE is the baseline.
- **Library:** use PyKEEN **only if** it can train on duplicate triples without deduplicating them. Verify this in its code or docs. Otherwise, write a small PyTorch trainer:
  - TransE: margin ranking loss with negative sampling.
  - ComplEx: logistic loss with negative sampling and L2 regularisation.
- **Dimensions:** 128 real dimensions per level by default, configurable. For ComplEx that means rank 64, and the entity vector is `concat(real, imag)`.
- **Validation:** a 95/5 train/held-out split. Early-stop on filtered hits@10 with a patience setting. Report MRR and hits@1/10.
- **Output:** `vocab/<level>.<model>.json` mapping each entity to its vector, plus metadata: model, dimension, seed, config hash, corpus hash and metrics. Save relation vectors separately; they are never used for encoding.

**Acceptance:**

- Both models train end-to-end on both levels.
- Metrics are logged.
- A nearest-neighbour sanity report is printed for the expected clusters in schema §4, such as `Paddint`–`Psubint` and `Caddf`–`Cmulf`.

---

## Phase 5 — Encoders (`python/ir2vec/encode/`)

Build four encoders on one shared engine. Weights come from `config/weights.json`: `Wo=1, Wt=0.5, Wa=0.2, Wc=0.2`.

- **`lambda_sym`** (schema §1.8):
  - node = `Wo·op + Wt·type + Wa·Σ` over value-position operands;
  - a leaf operand contributes its operand-kind vector; a child operand contributes `VAR_<child's Type>`, or `VAR_GEN` if the child has no `Type`;
  - function = the sum of its nodes.
- **`lambda_fa`** (control condition): the same, except an operand with def references uses the sum of its defining nodes' vectors. Resolve cycles with the SCC solver below.
- **`cmm_sym`** (control condition): the Flow-Aware formula with every operand replaced by its operand-kind vector.
- **`cmm_fa`** (schema §2.8):
  1. **Reaching definitions:** iterative dataflow over the blocks. Only mutable variables and handler parameters need it; immutable variables have exactly one definition.
  2. **Cycles:** build the definition→use dependency graph, run Tarjan's SCC algorithm, and process the SCCs in topological order.
     - A singleton SCC is computed directly.
     - A cyclic SCC is solved as `(I − Wa·M)X = B` with `numpy.linalg.solve`, all dimensions at once. `M[i][j]` counts the operand slots of *i* that *j* reaches. **Never round.**
     - If the matrix is ill-conditioned (condition number > 1e12), retry with `Wa − δ` and log it.
  3. **Liveness:** an instruction counts if it has a side effect or its `dst` is live.
  4. **Aggregation:** block = sum of live instructions; function = sum of blocks.
  5. **Calls, pass 2:** `F += Wc·Σ F_callee`, using each callee's pass-1 vector, for every direct local call (a `SYM_FUNC` naming a function in this unit).
- **Unknown entities:** count and log them. Tests fail on any unknown entity in a fixture.

**Acceptance tests:**

- `pq.ml` (`p = (x+y)*(x-y)` vs `q = let a = x+y in (a-y)*a`): the two functions are identical under `lambda_sym` and distinct under `lambda_fa` and `cmm_fa`. Report `cmm_sym`'s result without asserting on it.
- `counter.ml` (a `for` loop that updates a ref): the self-dependency is detected as a cyclic SCC, and the solver residual `‖X − (B + Wa·M·X)‖` is below 1e-9.
- `evenodd.ml` (mutual recursion): pass-2 call propagation terminates and gives finite vectors.
- For a function where no operand has a definition, such as `let f x y = x + y` at the Lambda level, the FA and Sym results are equal.
- Two runs produce byte-identical output.

---

## Phase 6 — `ir2vec embed` for new programs

- **Input:** a single `.ml` file (compiled with `ocamlfind ocamlopt -c`, with configurable `-package` flags) or a dune project directory (`dune build`).
  - Compile in the `ir2vec` switch with `IR2VEC_DUMP_DIR` pointing at a temp directory.
  - Extract, then encode with the **frozen** config and the chosen vocabularies.
- **Alignment** of Lambda and Cmm functions (schema §3):
  - named functions match by stamp;
  - anonymous functions match by source location, falling back to parameter stamps;
  - the Lambda `module_init` record matches `caml<Unit>__entry` (verify this symbol name on the pinned version);
  - unmatched functions are reported.
- **Output:** JSON by default, with a `--format npy` option.
  - **Per function:** names, IDs, location, `lambda_sym`, `lambda_fa`, `cmm_sym`, `cmm_fa`, whitelisted counts for both levels, node counts, and
    `final = concat(L2(lambda_sym), L2(cmm_fa), log1p(counts_lambda), log1p(counts_cmm), log1p(node_counts))`.
  - **Per module:** the summed vectors and their `final`.
  - **Metadata:** vocabulary hashes, config hash and weights.

**Acceptance:**

- `ir2vec embed tests/fixtures/align.ml` returns 4 functions plus the module init, all aligned (the anonymous function matched by location), with documented dimensions and zero unknown entities.
- A fresh file that isn't in the corpus embeds without errors.

---

## Phase 7 — Checks and report

- **`ir2vec check distinctness`:** for each sibling group listed in schema §4 (per level: types, operand kinds, `Lapply_a*`, `Lfunction_a*`, `Pgetglobal_*`, `Cload_*`, `Cstore_*`):
  - score = mean within-group cosine distance ÷ mean cosine distance over all entity pairs;
  - flag any group below 0.1;
  - show ComplEx and TransE side by side.
- **`ir2vec check alignment`:** the Lambda↔Cmm match rate over the whole corpus.
- **`REPORT.md`** covers:
  - the pinned version;
  - corpus statistics and failed packages;
  - entity counts compared with the schema;
  - the plateau plot;
  - training metrics;
  - the distinctness table;
  - the alignment rate;
  - unknown-entity counts;
  - known limitations.

---
# Phase 8 — Visualisation and geometry evidence
 
Append this to `docs/BUILD_SPEC.md`. All the working rules from that document still apply: stop at the end of the phase and report, record decisions in `DECISIONS.md`, no new dependencies without a line there, and everything deterministic.
 
## Goal
 
Produce the figures and numbers that show what the seed vocabularies and the function vectors actually look like. This is the OCaml counterpart of IR2Vec's Figure 6, plus several things that paper's figures can't support.
 
**Honesty rules, applied to every figure in this phase:**
 
1. **Every projection prints the explained variance** of the components shown, in the title. A 2-D view of a 128-D space can make distinct points overlap, so a reader needs to know how much is being discarded.
2. **No claim about similarity or collapse comes from a projection.** Full-dimensional cosine distinctness is the measurement; the plot only illustrates it. Annotate each group in the figure with its distinctness score.
3. **Low-confidence entities** (the 51 Lambda and 12 Cmm trained on fewer than 1,000 triples) use hollow markers. **Fallback-mapped entities** use a distinct marker shape. A reader must be able to see which points are weakly evidenced.
4. **Each figure writes its underlying numbers** to a `.tsv` beside it, so every visual claim is checkable without rerunning anything.
5. **Captions carry the vocabulary hash**, the model and the α setting.
## Deliverables
 
Output PNG and SVG to `report/figures/`, with a matching `.tsv` for each. Add a Figures section to `REPORT.md` that embeds them with captions.
 
CLI: `ir2vec figures {seeds|heatmap|distinctness|neighbours|analogy|functions|all} --vocab-lambda … --vocab-cmm … [--model …]`
 
### 8.0 Category map
 
Write `config/categories.json`, mapping every entity in both vocabularies to a display category. Suggested categories:
 
- **Lambda:** int arithmetic, float arithmetic, boxed-int, comparisons, blocks and records, arrays, strings and bytes, control forms, effects, globals and externs, misc, types, operand kinds.
- **Cmm:** int arithmetic, float arithmetic, pointer arithmetic, comparisons, loads, stores, calls and allocation, runtime, structural, types, operand kinds.
Every trained entity must be in exactly one category; a test asserts full coverage.
 
### 8.1 Seed scatter plots (the Figure 6 counterpart)
 
2-component PCA over each level's entity vectors, computed with `numpy.linalg.svd` (no new dependency). **Fix the sign convention** — force the largest-magnitude loading of each component positive — or the figures won't be reproducible across runs.
 
Produce one panel per comparison, points labelled with entity names and coloured by category.
 
- **Lambda:** types alone; int vs float arithmetic; arithmetic vs operand kinds; int vs boxed-int arithmetic; control forms vs primitives; effects vs the rest.
- **Cmm:** types alone; int vs float arithmetic; loads vs stores, coloured by chunk; calls and allocation vs arithmetic; structural opcodes vs operations.
Also produce an "all entities" panel per level.
 
**Acceptance:** every panel shows explained variance; group distinctness annotated; hollow and shaped markers correct; regenerating gives byte-identical SVGs.
 
### 8.2 Cosine similarity heatmap
 
Full-dimensional, no projection loss. Rows and columns ordered by category, with category boundaries drawn. One heatmap per level per model.
 
This is the honest version of 8.1: category structure should appear as blocks along the diagonal.
 
**Acceptance:** matrix symmetric with unit diagonal; row and column order recorded in the `.tsv`; block structure visible for both models.
 
### 8.3 Distinctness bar chart
 
You already have every number needed, in the Phase 7 checks and under `vocab/exp/`. Plot per sibling group, grouped bars for ComplEx vs TransE, and a second figure for α = 1.0 vs α = 0.75. Draw the 0.1 flag line.
 
**Acceptance:** the bars reproduce the Phase 7 table exactly; the α figure reproduces the D5.1 comparison.
 
### 8.4 Nearest-neighbour figure
 
Top-3 neighbours per entity with cosine scores, rendered as a sectioned table image, one section per category. Mark low-confidence entities. This is the evidence that survives when a projection can't be trusted.
 
**Acceptance:** the expected clusters from schema §4 are visible in the appropriate sections; the same data goes to the `.tsv`.
 
### 8.5 Analogy test
 
IR2Vec claims `add − sub ≈ fadd − fsub`. Test the equivalent claim here across parallel families, and **report it against a null distribution**, not on its own.
 
For each pair of parallel families, compute the cosine between the two difference vectors. Suggested pairs:
 
- **Lambda:** (Paddint, Psubint) vs (Paddfloat, Psubfloat); (Paddint, Paddbint) vs (Psubint, Psubbint); (Parrayrefu, Parraysetu) vs (Parrayrefs, Parraysets); (Pstringrefu, Pbytesrefu) vs (Pstringlength, Pbyteslength); (Lapply_a1, Lapply_a2) vs (Lfunction_a1, Lfunction_a2).
- **Cmm:** (Caddi, Csubi) vs (Caddf, Csubf); (Cload_word_val, Cstore_word_val) vs (Cload_double, Cstore_double); (Cload_byte_u, Cload_byte_s) vs (Cload_16u, Cload_16s).
**Null baseline:** sample 10,000 random entity pairs, compute cosines between their difference vectors, and report mean, standard deviation, and each real result's percentile against that distribution. A cosine of 0.3 means nothing until you know what chance looks like.
 
**Acceptance:** results reported for both models with the null distribution; the write-up states plainly whether the analogy property holds, in either direction. A negative result is a valid outcome and must not be softened.
 
### 8.6 Function-level projection
 
Take the whole-corpus encode output (1,829 units).
 
**Critical — avoid circularity.** Plot **only the learned blocks**: `L2(lambda_sym) ⊕ L2(cmm_fa)`, 256 dimensions. Do **not** include the 95 + 83 count features or the 4 node counts. Properties such as allocation, recursion and arity are *derived from the count block*, so plotting the full 438-dimensional vector and colouring by those properties would guarantee separation and prove nothing.
 
Colour by properties derived from the count block, used as labels only:
 
- recursive vs non-recursive (`CALL_SELF > 0`)
- allocating vs not (`Pmakeblock`, `Pmakearray`, `Calloc` counts)
- arity, from the signature block
- effect-using vs not
- package (treat sceptically: this can reflect naming idioms rather than semantics)
PCA is the primary view. t-SNE or UMAP is optional for this figure only, given the point count; if used, fix the seed and state on the figure that **neighbourhoods are meaningful but distances are not**. Sample deterministically by hash if the plot is too dense, and record the sample size.
 
**Acceptance:** each property gets its own panel; the caption states that only the learned blocks are plotted and why; the sampling rule is recorded.
 
### 8.7 Linear probe (recommended)
 
A picture invites eyeballing; a number settles it. For each binary property in 8.6, fit a logistic-regression probe on the 256-dimensional learned vector with 5-fold cross-validation, and report AUC with a standard deviation, plus a majority-class baseline.
 
Implement it in numpy to avoid a new dependency, or add scikit-learn with a line in `DECISIONS.md`.
 
**Interpretation, to state in the report:** a probe measures **linear decodability**, not usefulness. A high AUC means the learned vectors carry that signal; it is not a downstream task result, and the Phase 7 boundary statement stands unchanged.
 
**Acceptance:** AUC table for both models with baselines; the interpretation caveat present.
 
## Report
 
Add a **Figures** section to `REPORT.md` embedding 8.1–8.7 with captions, and a short **What the geometry shows** subsection that states, in plain terms:
 
- which expected clusters hold and which don't;
- whether the analogy property holds, against the null;
- what the rare-entity region looks like in the plots, cross-referenced to the existing limitation entry;
- which properties are linearly decodable from the learned blocks and which aren't.
Where a result is negative or ambiguous, say so directly. The value of this phase is an honest picture of the geometry, not a flattering one.
 

## Working rules

- **Stop at the end of every phase.** Report what you built, the test results, any deviations from this spec, and open questions. Append the decisions to `DECISIONS.md`, then wait for me to say continue.
- **When blocked** (an API mismatch, a `Marshal` failure, a constructor that isn't in the schema), use the documented fallback if there is one. Otherwise stop and ask. Never stub silently or fake output.
- **Tests:** use `dune test` for OCaml and `pytest` for Python. Every acceptance item above needs an automated test where one is feasible.
- **Code quality:**
  - small modules;
  - type hints in Python;
  - comments only where the logic isn't obvious (lowering, dataflow, the solver);
  - no new dependencies without a line in `DECISIONS.md`.
