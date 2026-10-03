# OCaml IR2Vec — Entities and Relations (brief)

| Level | Encoding | Entities | Relations |
|---|---|---|---|
| Lambda | Symbolic | 151 | 12 |
| Cmm | Flow-Aware | 78 | 8 |

---

## Lambda level (Symbolic)

### Entities

#### Control and binding opcodes (22)

These are the Lambda nodes that aren't primitives.

- **Lapply_a1, _a2, _a3, _a4p:** a function call, with the argument count folded into the name.
- **Lfunction_a1, _a2, _a3, _a4p:** a function definition, with the parameter count folded in.
- **Llet, Lmutlet, Lletrec:** immutable, mutable and recursive bindings.
- **Lifthenelse, Lswitch, Lstringswitch:** branches and pattern-match dispatch.
- **Lstaticraise, Lstaticcatch:** local jumps, used for pattern-match fallthrough and loop exits.
- **Ltrywith:** an exception handler.
- **Lsequence, Lwhile, Lfor:** sequencing and loops.
- **Lassign:** a write to a mutable variable.
- **Lsend:** a method call on an object.

#### Primitive opcodes (114)

These are the built-in operations.

- **Globals:** Pgetglobal_self / _stdlib / _other read a module's block, split by which module it is. Psetglobal writes one.
- **Blocks and records:** Pmakeblock, Pmakelazyblock, Pfield, Pfield_computed, Psetfield, Psetfield_computed, Pfloatfield, Psetfloatfield, Pduprecord. These allocate, read, write and copy heap blocks.
- **Effects (OCaml 5):** Prunstack, Pperform, Presume, Preperform.
- **Externals and exceptions:** Pccall calls a C function; Praise raises an exception.
- **Boolean:** Psequand, Psequor, Pnot.
- **Integer arithmetic:** Pnegint, Paddint, Psubint, Pmulint, Pdivint, Pmodint, Pandint, Porint, Pxorint, Plslint, Plsrint, Pasrint, Poffsetint, Poffsetref.
- **Comparisons:** Pintcomp, Pphyscomp, Pcompare_ints, Pcompare_floats, Pcompare_bints, Pfloatcomp, Pbintcomp.
- **Float:** Pintoffloat, Pfloatofint, Pnegfloat, Pabsfloat, Paddfloat, Psubfloat, Pmulfloat, Pdivfloat.
- **Strings and bytes:** Pstringlength, Pstringrefu/s, Pbyteslength, Pbytesrefu/s, Pbytessetu/s, Pbytes_to_string, Pbytes_of_string. The `u` suffix means unchecked; `s` means bounds-checked.
- **Arrays:** Pmakearray, Pduparray, Parraylength, Parrayrefu/s, Parraysetu/s.
- **Tag tests and bounds checks:** Pisint, Pisout, Pcheckbound. Compiled pattern matching and bounds checking use these.
- **Boxed integers** (int32, int64, nativeint): Pbintofint, Pintofbint, Pcvtbint, plus the arithmetic Pnegbint, Paddbint, Psubbint, Pmulbint, Pdivbint, Pmodbint, Pandbint, Porbint, Pxorbint, Plslbint, Plsrbint, Pasrbint.
- **Bigarrays:** Pbigarrayref, Pbigarrayset, Pbigarraydim.
- **Raw loads and stores:** P{string,bytes,bigstring}_load_{16,32,64} and P{bytes,bigstring}_set_{16,32,64}. These read and write multi-byte integers in byte buffers.
- **Byte swap:** Pbswap16, Pbbswap.
- **Atomics and domains:** Patomic_load, Patomic_fetch_add, Pdls_get.
- **Miscellaneous:** Pignore, Popaque, Pint_as_pointer, Pctconst, Ppoll.

#### Types (5)

The kind of value a node produces.

- **INT:** an immediate integer.
- **FLOAT:** a float.
- **BINT:** a boxed int32, int64 or nativeint.
- **ADDR:** the element kind of an array of pointers.
- **GEN:** any OCaml value.

#### Operand kinds (10)

What a leaf operand is.

- **VAR_INT, VAR_FLOAT, VAR_BINT, VAR_GEN:** an immutable variable, typed by its binding.
- **MUTVAR:** a read of a mutable variable.
- **CONST_INT, CONST_FLOAT, CONST_BINT, CONST_STRING:** literals, with the value itself dropped.
- **CONST_BLOCK:** a static structured constant, such as a constant list or tuple.

### Relations (12)

| Relation | Meaning | Example |
|---|---|---|
| **Type** | node → its result type | `(Paddint, Type, INT)` |
| **Arg0–Arg3, Arg4+** | node → the kind of the *leaf* in operand position i | `(Psubint, Arg1, CONST_INT)` |
| **Child0–Child3, Child4+** | node → the opcode of the *non-leaf* sub-expression in position i; encodes the tree structure | `(Lifthenelse, Child0, Pintcomp)` |
| **Case** | switch → the opcode (or leaf kind) of each arm; unordered | `(Lswitch, Case, Lapply_a1)` |

---

## Cmm level (Flow-Aware)

### Entities

#### Operation opcodes (56)

- **Calls and allocation:** Capply calls an OCaml function, Cextcall calls a C function, and Calloc allocates on the heap.
- **Memory access:** Cload_\* and Cstore_\* (11 each) read and write memory, with one entity per access width: byte_u, byte_s, 16u, 16s, 32u, 32s, 64, word_int, word_val, single, double.
- **Integer arithmetic:** Caddi, Csubi, Cmuli, Cmulhi, Cdivi, Cmodi, Cand, Cor, Cxor, Clsl, Clsr, Casr.
- **Pointer arithmetic:** Caddv produces a pointer the GC still tracks; Cadda produces a raw address it doesn't.
- **Comparisons:** Ccmpi compares integers, Ccmpa compares addresses (unsigned), and Ccmpf compares floats.
- **Float arithmetic:** Cnegf, Cabsf, Caddf, Csubf, Cmulf, Cdivf.
- **Conversions:** Cfloatofint, Cintoffloat.
- **Runtime:** Craise raises an exception, Ccheckbound checks array bounds, Copaque blocks optimisation, Catomic_fetch_add is an atomic add, Cdls_get reads domain-local storage, and Cpoll is a GC safepoint.

#### Structural opcodes (8)

These are created when Cmm is lowered to three-address code.

- **COPY and ASSIGN:** initialise and overwrite a mutable variable.
- **BR and SWITCH:** two-way and multi-way branches.
- **JUMP:** an exit to a catch handler. This is how loops and pattern-match fallthrough appear.
- **RET:** a function return.
- **TUPLE:** a multi-value result.
- **RETURN_ADDR:** a rare runtime operation.

#### Types (4)

Machine types.

- **INT:** an untagged machine integer.
- **VAL:** an OCaml value the GC scans. Tagged integers are VAL.
- **ADDR:** a derived pointer the GC does not scan.
- **FLOAT:** a float.

#### Operand kinds (10)

- **VAR_INT, VAR_VAL, VAR_ADDR, VAR_FLOAT:** a variable or temporary, by machine type.
- **CONST_INT, CONST_NATINT, CONST_FLOAT:** literals.
- **SYM_FUNC:** a symbol naming a function in this compilation unit, such as a direct call target.
- **SYM_DATA:** a symbol naming static data in this unit.
- **SYM_EXTERN:** a symbol from another unit or from the runtime.

### Relations (8)

| Relation | Meaning | Example |
|---|---|---|
| **Type** | instruction → its result machine type | `(Caddf, Type, FLOAT)` |
| **Arg0–Arg3, Arg4+** | instruction → the kind of operand i | `(Capply, Arg0, SYM_FUNC)`, which marks a direct call |
| **Next** | instruction → the opcode of the next instruction in the same basic block | `(Caddi, Next, Capply)` |
| **Succ** | branch or jump → the first opcode of each successor block; encodes the control-flow graph | `(BR, Succ, RET)` |

---

## Kept outside the graph (per-function counts)

These attributes would collapse into indistinguishable vectors in the knowledge graph, so they're counted per function instead:

- **Lambda:** callee kind, tail vs. non-tail call, mutability, comparison predicate, switch size, boxed-int width, and C external name.
- **Cmm:** comparison predicate, whether an extcall allocates, load mutability, store initialisation vs. assignment, switch size, and C external name.
