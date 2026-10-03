# OCaml IR2Vec — Entity & Relation Schema

A two-level seed vocabulary for IR2Vec-style embeddings of OCaml programs.

| Level | IR | Encoding | Relations | Entities\* |
|---|---|---|---|---|
| 1 | Lambda, after `Simplif.simplify_lambda` | Symbolic | 12 | 151 |
| 2 | Cmm, after `Cmmgen.compunit`, lowered to three-address code + CFG | Flow-Aware | 8 | 78 |

\* Before rare-family merges (see §1.6 and §2.6).

Alongside the learned embedding, each function also gets explicit **count features**, which are *not* part of the knowledge graph: 87 for Lambda, 81 for Cmm.

**Source of truth.**
- **Constructor lists** are checked against `ocaml/ocaml` trunk (5.6.0+dev), in `lambda/lambda.mli` and `asmcomp/cmm.mli`.
- **Compiler behaviour** (function naming, direct-call resolution, inlining) is checked against `ocamlopt 4.14.1` dumps.
- **Scope:** the non-flambda compiler path only.
- **Before use:** re-verify everything on the pinned 5.x release.

---

## 0. Ground rules

1. **An entity belongs in the graph only if its neighbourhood differs from its siblings'.** Entities that appear only as tails of the same `(head, relation)` pairs collapse to a single point under *any* KG model. There are two fixes:
   - **Fold** the attribute into the opcode when it changes the node's context.
   - **Count** it explicitly as a feature when it doesn't.
2. **Emit deterministic `Type` triples.** Triples like `(Paddint, Type, INT)` anchor the type entities apart from each other. Without them, type distinctness dropped from 0.48 to 0.12 in testing.
3. **Positional relations stay positional.** Collapsing `Arg0`/`Arg1` into a single `Arg` makes operand order unrecoverable.
4. **KG model: ComplEx as primary, TransE as baseline.**
   - Each entity's vector is its `[real ; imag]` concatenation.
   - Relation vectors are discarded after training.
   - Two separate training runs, one per level, with separate entity IDs.
5. **Every payload is abstracted to a bounded set**, including identifiers, stamps, constant values, symbol names and field indices. The vocabulary is finite by construction.

---

## 1. Level 1 — Lambda (Symbolic)

### 1.1 Instructions and positions

- **Instructions:** every non-leaf Lambda node is one instruction.
- **Leaves:** `Lvar`, `Lmutvar` and `Lconst` are operand kinds, never instructions.
- **Transparent nodes:** `Levent` and `Lifused` are skipped; traversal descends straight to their child.

Every node has ordered positions. A **leaf** in position *i* produces an `Arg_i` triple, and a **non-leaf** produces a `Child_i` triple. Positions *i* ≥ 4 share `Arg4+` / `Child4+`.

| Node | Positions, in order | Value (V) or control (C) |
|---|---|---|
| `Lprim` | args | V |
| `Lapply_*` | args (the callee is not a position) | V |
| `Llet`, `Lmutlet` | def, body | V, C |
| `Lletrec` | defs…, body | V…, C |
| `Lifthenelse` | cond, then, else | V, C, C |
| `Lswitch`, `Lstringswitch` | scrutinee (arms go via `Case`) | V |
| `Lstaticraise` | args | V |
| `Lstaticcatch` | body, handler | C, C |
| `Ltrywith` | body, handler | C, C |
| `Lsequence` | first, second | C, C |
| `Lwhile` | cond, body | V, C |
| `Lfor` | lo, hi, body | V, V, C |
| `Lassign` | value | V |
| `Lfunction_*` | body | C |
| `Lsend` | obj, method, args | V |

Both value and control positions appear in training. **Only value positions contribute** to the Symbolic vector at inference.

### 1.2 Entities: opcodes (136)

#### Control and binding forms (22)

| Entity | Notes |
|---|---|
| `Lapply_a1` `Lapply_a2` `Lapply_a3` `Lapply_a4p` | Arity folded in. Arity changes the operand pattern, so each composite has a distinct context. |
| `Lfunction_a1` `Lfunction_a2` `Lfunction_a3` `Lfunction_a4p` | Arity is the number of parameters. |
| `Llet` `Lmutlet` `Lletrec` | |
| `Lswitch` `Lstringswitch` | |
| `Lstaticraise` `Lstaticcatch` `Ltrywith` | |
| `Lifthenelse` `Lsequence` `Lwhile` `Lfor` | |
| `Lassign` `Lsend` | |

#### Primitives (114)

These are all 112 `Lambda.primitive` constructors, with `Pgetglobal` split into 3 composites. Every payload is dropped except where §1.4 or §1.7 uses it.

| Group | Entities |
|---|---|
| Globals (4) | `Pgetglobal_self` `Pgetglobal_stdlib` `Pgetglobal_other` `Psetglobal` |
| Blocks & records (9) | `Pmakeblock` `Pmakelazyblock` `Pfield` `Pfield_computed` `Psetfield` `Psetfield_computed` `Pfloatfield` `Psetfloatfield` `Pduprecord` |
| Effects (4) | `Prunstack` `Pperform` `Presume` `Preperform` |
| External & exceptions (2) | `Pccall` `Praise` |
| Boolean (3) | `Psequand` `Psequor` `Pnot` |
| Int arithmetic (14) | `Pnegint` `Paddint` `Psubint` `Pmulint` `Pdivint` `Pmodint` `Pandint` `Porint` `Pxorint` `Plslint` `Plsrint` `Pasrint` `Poffsetint` `Poffsetref` |
| Comparisons (7) | `Pintcomp` `Pphyscomp` `Pcompare_ints` `Pcompare_floats` `Pcompare_bints` `Pfloatcomp` `Pbintcomp` |
| Float (8) | `Pintoffloat` `Pfloatofint` `Pnegfloat` `Pabsfloat` `Paddfloat` `Psubfloat` `Pmulfloat` `Pdivfloat` |
| Strings & bytes (10) | `Pstringlength` `Pstringrefu` `Pstringrefs` `Pbyteslength` `Pbytesrefu` `Pbytessetu` `Pbytesrefs` `Pbytessets` `Pbytes_to_string` `Pbytes_of_string` |
| Arrays (7) | `Pmakearray` `Pduparray` `Parraylength` `Parrayrefu` `Parraysetu` `Parrayrefs` `Parraysets` |
| Tag tests & bounds (3) | `Pisint` `Pisout` `Pcheckbound` |
| Boxed integers (15) | `Pbintofint` `Pintofbint` `Pcvtbint` `Pnegbint` `Paddbint` `Psubbint` `Pmulbint` `Pdivbint` `Pmodbint` `Pandbint` `Porbint` `Pxorbint` `Plslbint` `Plsrbint` `Pasrbint` |
| Bigarray (3) | `Pbigarrayref` `Pbigarrayset` `Pbigarraydim` |
| Raw loads (9) | `Pstring_load_16` `Pstring_load_32` `Pstring_load_64` `Pbytes_load_16` `Pbytes_load_32` `Pbytes_load_64` `Pbigstring_load_16` `Pbigstring_load_32` `Pbigstring_load_64` |
| Raw stores (6) | `Pbytes_set_16` `Pbytes_set_32` `Pbytes_set_64` `Pbigstring_set_16` `Pbigstring_set_32` `Pbigstring_set_64` |
| Byte swap (2) | `Pbswap16` `Pbbswap` |
| Atomics & domains (3) | `Patomic_load` `Patomic_fetch_add` `Pdls_get` |
| Misc (5) | `Pignore` `Popaque` `Pint_as_pointer` `Pctconst` `Ppoll` |

`Pgetglobal` is split by module:

| Target module | Entity |
|---|---|
| the current compilation unit | `Pgetglobal_self` |
| `Stdlib` or `Stdlib__*` | `Pgetglobal_stdlib` |
| anything else | `Pgetglobal_other` |

### 1.3 Entities: types (5) and operand kinds (10)

**Types:**

| Entity | Source |
|---|---|
| `INT` | `Pintval`; immediate fields; `Pintarray`; int-valued primitives |
| `FLOAT` | `Pfloatval`; `Pfloatarray`; float primitives |
| `BINT` | `Pboxedintval _` (all widths merged; the width goes to the count features) |
| `ADDR` | `Paddrarray` |
| `GEN` | `Pgenval`; pointer fields; `Pgenarray`; allocations |

**Operand kinds** (leaf abstraction):

| Entity | Leaf |
|---|---|
| `VAR_INT` `VAR_FLOAT` `VAR_BINT` `VAR_GEN` | `Lvar x`, typed by x's binding kind: a `Llet`/`Lmutlet` value_kind, `Lfunction` parameter kind, or `Lstaticcatch` parameter kind. Otherwise `VAR_GEN`. |
| `MUTVAR` | `Lmutvar x` |
| `CONST_INT` | `Const_int`, `Const_char` |
| `CONST_FLOAT` | `Const_float` |
| `CONST_BINT` | `Const_int32`, `Const_int64`, `Const_nativeint` |
| `CONST_STRING` | `Const_string`, `Const_immstring` |
| `CONST_BLOCK` | `Const_block`, `Const_float_array` |

At inference, a **computed operand** (a non-leaf in a value position) is represented as `VAR_<k>`, where *k* is the child's `Type` from §1.4. If the child has no `Type`, it's `VAR_GEN`.

### 1.4 `Type` emission

**Deterministic (anchors; always emitted):**

| Tail | Heads |
|---|---|
| `INT` | `Pnegint` `Paddint` `Psubint` `Pmulint` `Pdivint` `Pmodint` `Pandint` `Porint` `Pxorint` `Plslint` `Plsrint` `Pasrint` `Poffsetint` `Pintcomp` `Pphyscomp` `Pcompare_ints` `Pcompare_floats` `Pcompare_bints` `Pfloatcomp` `Pbintcomp` `Pnot` `Psequand` `Psequor` `Pisint` `Pisout` `Pstringlength` `Pbyteslength` `Parraylength` `Pstringrefu` `Pstringrefs` `Pbytesrefu` `Pbytesrefs` `Pintoffloat` `Pintofbint` `Pbswap16` `Pbigarraydim` `Pctconst` `Pstring_load_16` `Pbytes_load_16` `Pbigstring_load_16` |
| `FLOAT` | `Paddfloat` `Psubfloat` `Pmulfloat` `Pdivfloat` `Pnegfloat` `Pabsfloat` `Pfloatofint` `Pfloatfield` |
| `BINT` | `Pbintofint` `Pcvtbint` `Pnegbint` `Paddbint` `Psubbint` `Pmulbint` `Pdivbint` `Pmodbint` `Pandbint` `Porbint` `Pxorbint` `Plslbint` `Plsrbint` `Pasrbint` `Pbbswap` `Pstring_load_32` `Pstring_load_64` `Pbytes_load_32` `Pbytes_load_64` `Pbigstring_load_32` `Pbigstring_load_64` |
| `GEN` | `Pmakeblock` `Pmakelazyblock` `Pduprecord` `Pmakearray` `Pduparray` `Pfield_computed` `Pbytes_to_string` `Pbytes_of_string` `Pgetglobal_self` `Pgetglobal_stdlib` `Pgetglobal_other` |

**Instance-dependent:**

| Head | Tail |
|---|---|
| `Llet`, `Lmutlet` | the bound variable's value_kind |
| `Lfunction_*` | the return value_kind |
| `Pfield` | `Immediate` → `INT`; `Pointer` → `GEN` |
| `Parrayrefu`, `Parrayrefs` | array_kind: `Pgenarray` → `GEN`, `Paddrarray` → `ADDR`, `Pintarray` → `INT`, `Pfloatarray` → `FLOAT` |

**No `Type` triple.** These nodes return unit, don't return, or have an unknown result kind:

- **Control forms:** `Lapply_*` `Lletrec` `Lifthenelse` `Lswitch` `Lstringswitch` `Lstaticraise` `Lstaticcatch` `Ltrywith` `Lsequence` `Lwhile` `Lfor` `Lassign` `Lsend`
- **Setters and unit-returning primitives:** `Psetglobal` `Psetfield` `Psetfield_computed` `Psetfloatfield` `Parraysetu` `Parraysets` `Pbytessetu` `Pbytessets` `Pbytes_set_16` `Pbytes_set_32` `Pbytes_set_64` `Pbigstring_set_16` `Pbigstring_set_32` `Pbigstring_set_64` `Pbigarrayset` `Poffsetref` `Pcheckbound` `Pignore` `Ppoll`
- **Unknown result kind:** `Pccall` `Praise` `Popaque` `Pint_as_pointer` `Pbigarrayref` `Prunstack` `Pperform` `Presume` `Preperform` `Patomic_load` `Patomic_fetch_add` `Pdls_get`

### 1.5 Relations (12)

| Relation | Head | Tail | Emitted when |
|---|---|---|---|
| `Type` | an opcode | a type (§1.3) | per §1.4 |
| `Arg0` `Arg1` `Arg2` `Arg3` `Arg4+` | any node | an operand kind (§1.3) | a **leaf** is in position *i* |
| `Child0` `Child1` `Child2` `Child3` `Child4+` | any node | the child's opcode | a **non-leaf** is in position *i*. This replaces `Next`, because Lambda is a tree. |
| `Case` | `Lswitch`, `Lstringswitch` | the arm's opcode, or its leaf kind | once per arm, including the default. Non-positional. |

There is no `Next` relation at this level. Sequencing is encoded by `Lsequence` and its `Child0`/`Child1`.

### 1.6 Rare-family merge candidates

Decide these once from corpus statistics, then freeze and version the decision. Merge a family only if **every** member falls below the frequency threshold.

| Merged entity | Members |
|---|---|
| `P_RAW_LOAD` | the 9 raw loads (Type becomes instance-dependent: 16-bit → `INT`, 32/64-bit → `BINT`) |
| `P_RAW_STORE` | the 6 raw stores |
| `P_BIGARRAY` | `Pbigarrayref` `Pbigarrayset` `Pbigarraydim` |
| `P_BSWAP` | `Pbswap16` `Pbbswap` |
| `P_ATOMIC` | `Patomic_load` `Patomic_fetch_add` |

### 1.7 Count features (87, outside the graph)

These are per-function counts, transformed with `log(1+x)` and concatenated to the embedding.

| Feature group | Buckets | Counted on |
|---|---|---|
| Callee kind (5) | `CALL_SELF` `CALL_LOCAL` `CALL_STDLIB` `CALL_MODULE` `CALL_DYNAMIC` | each `Lapply_*`, from its callee expression |
| Tail position (2) | `TAIL` `NONTAIL` | each `Lapply_*`. Computed by the traversal, **not** taken from `ap_tailcall`. |
| Mutability (2) | `MUT` `IMMUT` | `Pmakeblock`, `Pfield`, `Pmakearray`, `Pduparray` |
| Predicate (6) | `EQ` `NE` `LT` `LE` `GT` `GE` | `Pintcomp`, `Pfloatcomp` (negated float forms map to their base), `Pbintcomp`, `Pphyscomp` |
| Switch size (4) | `ARMS_2` `ARMS_3_4` `ARMS_5_8` `ARMS_9P` | `Lswitch`, `Lstringswitch` |
| Boxed-int width (3) | `W32` `W64` `WNAT` | every boxed-int op |
| Extern (65) | the top-64 `Pccall` names in the corpus, plus `EXT_OTHER` | each `Pccall` (frozen whitelist) |

Callee kinds are determined from the callee expression:

| Callee expression | Callee kind |
|---|---|
| the enclosing `letrec` function's own identifier | `CALL_SELF` |
| `field i (Pgetglobal_self)`, or a function bound locally | `CALL_LOCAL` |
| via `Pgetglobal_stdlib` | `CALL_STDLIB` |
| via `Pgetglobal_other` | `CALL_MODULE` |
| anything else | `CALL_DYNAMIC` |

### 1.8 Inference (Symbolic)

$$[\![n]\!] = W_o[\![op]\!] + W_t[\![type]\!] + W_a \textstyle\sum_{\text{value pos } i} v_i \qquad (W_o, W_t, W_a) = (1, 0.5, 0.2)$$

- **Function vector:** the sum over nodes in the function body, stopping at a nested `Lfunction_*`. The nested node itself counts in its parent; its body counts only in its own function.
- **Module vector:** the sum of all function vectors plus the top-level initialisation nodes.

### 1.9 Worked example

```
(function n/268[int] : int
  (if (<= n/268 1) 1 (* n/268 (apply fact/267 (- n/268 1)))))
```

```
(Lfunction_a1, Type,   INT)            (Pmulint,   Type,   INT)
(Lfunction_a1, Child0, Lifthenelse)    (Pmulint,   Arg0,   VAR_INT)
(Lifthenelse,  Child0, Pintcomp)       (Pmulint,   Child1, Lapply_a1)
(Lifthenelse,  Arg1,   CONST_INT)      (Lapply_a1, Child0, Psubint)
(Lifthenelse,  Child2, Pmulint)        (Psubint,   Type,   INT)
(Pintcomp,     Type,   INT)            (Psubint,   Arg0,   VAR_INT)
(Pintcomp,     Arg0,   VAR_INT)        (Psubint,   Arg1,   CONST_INT)
(Pintcomp,     Arg1,   CONST_INT)

counts: CALL_SELF=1  NONTAIL=1  LE=1
```

---
## 2. Level 2 — Cmm (Flow-Aware)

### 2.1 Lowering: Cmm → three-address code + CFG

Each lowered line is one instruction. Every operand is atomic: a variable, a temp, or a constant.

| Cmm | Lowered form |
|---|---|
| `Cop(op, args)` | `t = op a1 … an`; non-atomic args are lowered first into fresh temps |
| `Clet(x, e, b)` | `x = ⟨e⟩`: a single definition (SSA-like) |
| `Clet_mut(x, ty, e, b)` | `x = COPY ⟨e⟩`; x is marked mutable |
| `Cassign(x, e)` | `x = ASSIGN ⟨e⟩`: a new definition that kills the previous one |
| `Cvar`, `Cvar_mut` | uses |
| `Cifthenelse(c, e1, e2)` | `BR t → B_then, B_else`, both flowing into `B_join` |
| `Cswitch(e, idx, cases)` | `SWITCH t → case blocks` |
| `Ccatch(rec, handlers, body)` | one block per handler; handler parameters are variables. `catch rec` is how loops appear. |
| `Cexit(n, args)` | `params_n = args` (definitions), then `JUMP → handler n` |
| `Ctrywith(body, x, h)` | a handler block; in v1, edges from every body block to it. x is defined at handler entry. |
| `Csequence` | concatenate |
| `Ctuple` | `TUPLE` |
| `Creturn_addr` | `RETURN_ADDR` |
| `Cphantom_let` | dropped |
| the function's result | `RET t` |

### 2.2 Entities: opcodes (64)

**Cmm operations (56).** These are the 36 `Cmm.operation` constructors, with `Cload` and `Cstore` each split by memory chunk:

| Group | Entities |
|---|---|
| Calls & allocation (3) | `Capply` `Cextcall` `Calloc` |
| Loads (11) | `Cload_byte_u` `Cload_byte_s` `Cload_16u` `Cload_16s` `Cload_32u` `Cload_32s` `Cload_64` `Cload_word_int` `Cload_word_val` `Cload_single` `Cload_double` |
| Stores (11) | `Cstore_byte_u` `Cstore_byte_s` `Cstore_16u` `Cstore_16s` `Cstore_32u` `Cstore_32s` `Cstore_64` `Cstore_word_int` `Cstore_word_val` `Cstore_single` `Cstore_double` |
| Integer arithmetic (12) | `Caddi` `Csubi` `Cmuli` `Cmulhi` `Cdivi` `Cmodi` `Cand` `Cor` `Cxor` `Clsl` `Clsr` `Casr` |
| Pointer arithmetic (2) | `Caddv` (derived GC value) `Cadda` (derived address) |
| Comparisons (3) | `Ccmpi` `Ccmpa` `Ccmpf` |
| Float arithmetic (6) | `Cnegf` `Cabsf` `Caddf` `Csubf` `Cmulf` `Cdivf` |
| Conversions (2) | `Cfloatofint` `Cintoffloat` |
| Control & runtime (6) | `Craise` `Ccheckbound` `Copaque` `Catomic_fetch_add` `Cdls_get` `Cpoll` |

The chunk suffixes map to `Cmm.memory_chunk` as follows:

| Suffix | Chunk |
|---|---|
| `byte_u`, `byte_s` | `Byte_unsigned`, `Byte_signed` |
| `16u`, `16s` | `Sixteen_unsigned`, `Sixteen_signed` |
| `32u`, `32s` | `Thirtytwo_unsigned`, `Thirtytwo_signed` |
| `64` | `Sixtyfour` |
| `word_int`, `word_val` | `Word_int`, `Word_val` |
| `single`, `double` | `Single`, `Double` |

**Structural opcodes (8)**, introduced by the lowering: `COPY` `ASSIGN` `BR` `SWITCH` `JUMP` `RET` `TUPLE` `RETURN_ADDR`

### 2.3 Entities: types (4) and operand kinds (10)

**Types:** `INT` `VAL` `ADDR` `FLOAT`. These are the single-component machtypes. Tagged OCaml integers are `VAL`, so `INT` means untagged machine integers.

**Operand kinds:**

| Entity | Operand |
|---|---|
| `VAR_INT` `VAR_VAL` `VAR_ADDR` `VAR_FLOAT` | a variable or temp, typed by its machtype. The type comes from function parameters, `Clet_mut`, handler parameters, or the defining instruction's `Type`. Default: `VAR_VAL`. |
| `CONST_INT` | `Cconst_int` (tagged or untagged; the value is dropped) |
| `CONST_NATINT` | `Cconst_natint` |
| `CONST_FLOAT` | `Cconst_float` |
| `SYM_FUNC` | `Cconst_symbol s` where s names a `Cfunction` in this unit |
| `SYM_DATA` | `Cconst_symbol s` where s names a `Cdata` item in this unit |
| `SYM_EXTERN` | any other `Cconst_symbol`: another unit, the runtime, or externals |

### 2.4 `Type` emission

**Deterministic (anchors; always emitted):**

| Tail | Heads |
|---|---|
| `INT` | `Caddi` `Csubi` `Cmuli` `Cmulhi` `Cdivi` `Cmodi` `Cand` `Cor` `Cxor` `Clsl` `Clsr` `Casr` `Ccmpi` `Ccmpa` `Ccmpf` `Cintoffloat` `Cload_byte_u` `Cload_byte_s` `Cload_16u` `Cload_16s` `Cload_32u` `Cload_32s` `Cload_64` `Cload_word_int` |
| `FLOAT` | `Caddf` `Csubf` `Cmulf` `Cdivf` `Cnegf` `Cabsf` `Cfloatofint` `Cload_single` `Cload_double` |
| `ADDR` | `Cadda` |
| `VAL` | `Caddv` `Calloc` `Cload_word_val` |

**Instance-dependent:**

| Head | Tail |
|---|---|
| `Capply`, `Cextcall` | the declared result machtype, if it has exactly one component |
| `COPY`, `ASSIGN` | the target variable's machtype |
| `Copaque` | its argument's machtype |

**No `Type` triple (v1):** all 11 `Cstore_*`, plus `Craise` `Ccheckbound` `Cpoll` `Catomic_fetch_add` `Cdls_get` `BR` `SWITCH` `JUMP` `RET` `TUPLE` `RETURN_ADDR`. Revisit `Catomic_fetch_add`, `Cdls_get` and `RETURN_ADDR` once their result machtypes are confirmed on the pinned version.

### 2.5 Relations (8)

| Relation | Head | Tail | Emitted when |
|---|---|---|---|
| `Type` | an opcode | a type (§2.3) | per §2.4 |
| `Arg0` `Arg1` `Arg2` `Arg3` `Arg4+` | any instruction | an operand kind (§2.3) | for each operand, in order |
| `Next` | any instruction | the next instruction's opcode | both are in the same basic block; terminators have no `Next` |
| `Succ` | `BR`, `SWITCH`, `JUMP`, and `Craise` inside a `Ctrywith` | the first opcode of each successor block | once per successor edge |

Operand-order conventions:

| Instruction | Operands, in order |
|---|---|
| `Capply` | callee (`SYM_FUNC` for a direct call, a loaded `VAR_VAL` for an indirect one), then the arguments. Indirect calls pass the closure last. |
| `Cstore_*` | address, then value |
| `BR`, `SWITCH` | the condition or index |
| `RET` | the returned value |
| `COPY`, `ASSIGN` | the source |
| `JUMP` | the exit arguments |

There is no `Callee` relation at this level: `Capply`'s `Arg0` already distinguishes direct calls from indirect ones.

### 2.6 Rare-family merge candidates

| Merged entity | Members |
|---|---|
| `Cload_narrow` | `Cload_16u` `Cload_16s` `Cload_32u` `Cload_32s` `Cload_64` (Type `INT`) |
| `Cstore_narrow` | the corresponding stores |
| `C_RUNTIME` | `Catomic_fetch_add` `Cdls_get` `Cpoll` `RETURN_ADDR` |

### 2.7 Count features (81, outside the graph)

| Feature group | Buckets | Counted on |
|---|---|---|
| Predicate (6) | `EQ` `NE` `LT` `LE` `GT` `GE` | `Ccmpi`, `Ccmpa`, `Ccmpf` (negated float forms map to their base) |
| Extcall alloc (2) | `ALLOC` `NOALLOC` | each `Cextcall` (its `bool` payload) |
| Load mutability (2) | `LOAD_MUT` `LOAD_IMMUT` | each `Cload_*` |
| Store kind (2) | `INIT` `ASSIGN_STORE` | each `Cstore_*` (`initialization_or_assignment`) |
| Switch size (4) | `ARMS_2` `ARMS_3_4` `ARMS_5_8` `ARMS_9P` | each `SWITCH` |
| Extern (65) | the same frozen top-64 whitelist, plus `EXT_OTHER` | each `Cextcall` |

### 2.8 Inference (Flow-Aware)

$$[\![I]\!] = W_o[\![op]\!] + W_t[\![type]\!] + W_a \textstyle\sum_j A_j$$

$A_j$ is the sum of the vectors of operand $j$'s reaching definitions. If the operand has no definition (a parameter or a constant), $A_j$ is its operand-kind vector instead.

1. **Reaching definitions** come from iterative dataflow. They're only needed for mutable variables and handler parameters; immutable variables have exactly one definition.
2. **Cycles:** find strongly connected components (Tarjan) over the definition→use graph. Solve each cyclic component with $(I - W_a M)X = B$, where $M_{ij}$ counts the operand slots of $i$ that $j$ reaches. Don't truncate values.
3. **Liveness:** an instruction counts if it has a side effect or its result is live.
4. **Aggregation:** block = sum of live instructions; function = sum of blocks.
5. **Calls, pass 2:** add $W_c \cdot F_{callee}$ for each direct local call, using the callee's pass-1 function vector.

**Cmm-Symbolic** is the control condition: the same formula with every $A_j$ set to its operand-kind vector.

### 2.9 Worked example

```
(function camlAlign__fact_267 (n/268: val)
 (if (<= n/268 3) 3
   (+ (* (+ n/268 -1) (>>s (app "camlAlign__fact_267" (+ n/268 -2) val) 1)) 1)))
```

```
B0: t1 = Ccmpi n, 3            B2: t2 = Caddi  n, -2
    BR t1 → B1, B2                 t3 = Capply SYM_FUNC, t2
B1: RET 3                          t4 = Casr   t3, 1
                                   t5 = Caddi  n, -1
                                   t6 = Cmuli  t5, t4
                                   t7 = Caddi  t6, 1
                                   RET t7
```

```
(Ccmpi, Type, INT)        (BR,    Arg0, VAR_INT)     (Capply, Type, VAL)
(Ccmpi, Arg0, VAR_VAL)    (BR,    Succ, RET)         (Capply, Arg0, SYM_FUNC)
(Ccmpi, Arg1, CONST_INT)  (BR,    Succ, Caddi)       (Capply, Arg1, VAR_INT)
(Ccmpi, Next, BR)         (RET,   Arg0, CONST_INT)   (Capply, Next, Casr)
(Caddi, Type, INT)        (Caddi, Arg1, CONST_INT)   (Casr,   Type, INT)
(Caddi, Arg0, VAR_VAL)    (Caddi, Next, Capply)      (Casr,   Arg0, VAR_VAL)   ...

counts: LE=1
```

---

## 3. Summary

| | Lambda | Cmm |
|---|---|---|
| Opcodes | 136 (22 forms + 114 primitives) | 64 (56 operations + 8 structural) |
| Types | 5 | 4 |
| Operand kinds | 10 | 10 |
| **Graph entities** | **151** | **78** |
| **Relations** | **12**: `Type`, `Arg0–3`, `Arg4+`, `Child0–3`, `Child4+`, `Case` | **8**: `Type`, `Arg0–3`, `Arg4+`, `Next`, `Succ` |
| Count features | 87 | 81 |

Final function representation:

$$f = \big[\,\text{L2}(\text{Lambda-Sym}) \;;\; \text{L2}(\text{Cmm-FA}) \;;\; \log(1+\text{counts}_{\text{Lambda}}) \;;\; \log(1+\text{counts}_{\text{Cmm}}) \;;\; \log(1+\text{node counts})\,\big]$$

Lambda and Cmm functions are aligned as follows:

| Case | Match on |
|---|---|
| named functions | the identifier stamp, e.g. `fact/267` ↔ `camlAlign__fact_267` |
| anonymous functions | the source location first, then parameter stamps |
| module initialisation | the top-level code ↔ `caml<Unit>__entry` |

**Leakage rule:** Cmm is post-inlining. For any task that predicts a decision the compiler makes before Cmm (inlining, specialisation), use Lambda features only.

---

## 4. Validation checklist

- [ ] **Entity-count plateau:** plot the number of entities against the number of opam packages. It must flatten; if it keeps growing, an abstraction rule is leaking.
- [ ] **Distinctness check:** for every sibling group, compute mean pairwise cosine distance within the group divided by the mean over all entities. Any group scoring below about 0.1 has collapsed; fold it or move it to counts. Groups to check:
  - Lambda types
  - Lambda operand kinds
  - `Lapply_a*`, `Lfunction_a*`, `Pgetglobal_*`
  - Cmm types
  - Cmm operand kinds
  - `Cload_*`, `Cstore_*`
- [ ] **Tail-call folding test:** try splitting `Lapply_aK` into `Lapply_aK_tail` / `Lapply_aK_nontail`. Keep the split only if those composites pass the distinctness check. Otherwise tail position stays a count feature.
- [ ] **Model comparison:** train ComplEx and TransE on the real triples and compare distinctness and opcode clustering.
- [ ] **Rare merges:** decide §1.6 and §2.6 from corpus frequencies, then freeze and version them together with the extern whitelist.
- [ ] **Version check:** re-verify constructor lists, function naming and alignment on the pinned 5.x release.

---

## 5. Changes from earlier drafts

- **Attribute relations removed from the graph:** `Arity`, `Tail`, `Mut`, `Pred`, `Arms`, `Callee`, `Extern`, `Alloc` and `Init` collapsed under every KG model. Arity and memory chunk are now folded into opcodes; the rest are count features.
- **All deterministic `Type` triples are emitted,** because they anchor the type entities.
- **`BINT32`/`BINT64`/`BINTNAT` merged into `BINT`,** with width moved to counts. All three appeared only as tails of the same boxed-int heads, so they would have collapsed.
- **`GLOBAL_*` operand kinds replaced by `Pgetglobal_*` opcodes.** The operand kinds would have had identical neighbourhoods, whereas the opcodes have different contexts (for example, only `self` is the target of init-time `setfield`s).
- **Unit-returning nodes emit no `Type`.**
