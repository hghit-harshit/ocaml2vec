(* The single definition point for every IR2Vec entity, relation and
   count-feature name (schema §1–§2, adjusted for OCaml 5.5.1 per
   DECISIONS.md D0.15/D0.16). Mappers and the inventory generator both read
   from here; opcode names equal compiler constructor names except for the
   split families defined below. *)

(* ------------------------------------------------------------------ *)
(* Lambda level                                                         *)

type lty = INT | FLOAT | BINT | ADDR | GEN

let lty_name = function
  | INT -> "INT" | FLOAT -> "FLOAT" | BINT -> "BINT" | ADDR -> "ADDR"
  | GEN -> "GEN"

let lambda_types = List.map lty_name [INT; FLOAT; BINT; ADDR; GEN]

(* Leaf operand kinds (schema §1.3). *)
let var_int = "VAR_INT"
let var_float = "VAR_FLOAT"
let var_bint = "VAR_BINT"
let var_gen = "VAR_GEN"
let mutvar = "MUTVAR"
let const_int = "CONST_INT"
let const_float = "CONST_FLOAT"
let const_bint = "CONST_BINT"
let const_string = "CONST_STRING"
let const_block = "CONST_BLOCK"

let lambda_operand_kinds =
  [var_int; var_float; var_bint; var_gen; mutvar;
   const_int; const_float; const_bint; const_string; const_block]

(* Operand kind of a computed (non-leaf) operand: VAR_<child's Type>.
   Total by design (DECISIONS.md D1.11): ADDR has no operand-kind counterpart,
   since no value_kind yields it, so VAR_ADDR could never occur in a triple. *)
let computed_operand_kind : lty option -> string = function
  | Some INT -> var_int
  | Some FLOAT -> var_float
  | Some BINT -> var_bint
  | Some ADDR | Some GEN | None -> var_gen

(* Lambda.lambda constructors that are not opcodes. *)
let lambda_leaf_ctors = ["Lvar"; "Lmutvar"; "Lconst"]
let lambda_transparent_ctors = ["Levent"; "Lifused"]
let lambda_prim_ctor = "Lprim"  (* replaced by the primitive's opcode *)

(* Arity-split forms: Lapply_a1..a3, Lapply_a4p; same for Lfunction. *)
let arity_split_ctors = ["Lapply"; "Lfunction"]
let arity_suffixes = ["a1"; "a2"; "a3"; "a4p"]

let arity_suffix n =
  if n < 1 then invalid_arg (Printf.sprintf "arity_suffix %d" n)
  else if n >= 4 then "a4p"
  else "a" ^ string_of_int n

let with_arity ctor n = ctor ^ "_" ^ arity_suffix n

(* Pgetglobal split by target module (schema §1.2). *)
type global_class = Self | Stdlib | Other

let global_ctor = "Pgetglobal"

let global_suffix = function
  | Self -> "self" | Stdlib -> "stdlib" | Other -> "other"

let global_suffixes = List.map global_suffix [Self; Stdlib; Other]

let with_global cls = global_ctor ^ "_" ^ global_suffix cls

let lambda_relations =
  ["Type"; "Arg0"; "Arg1"; "Arg2"; "Arg3"; "Arg4+";
   "Child0"; "Child1"; "Child2"; "Child3"; "Child4+"; "Case"]

(* Positions >= 4 share one relation. *)
let positional prefix i =
  if i >= 4 then prefix ^ "4+" else prefix ^ string_of_int i

(* Lambda count features (schema §1.7), excluding the extern buckets,
   which come from the frozen whitelist (Python side). *)
let call_self = "CALL_SELF"
let call_local = "CALL_LOCAL"
let call_stdlib = "CALL_STDLIB"
let call_module = "CALL_MODULE"
let call_dynamic = "CALL_DYNAMIC"
let tail = "TAIL"
let nontail = "NONTAIL"
let mut_ = "MUT"
let immut = "IMMUT"
let pred_eq = "PRED_EQ"
let pred_ne = "PRED_NE"
let pred_lt = "PRED_LT"
let pred_le = "PRED_LE"
let pred_gt = "PRED_GT"
let pred_ge = "PRED_GE"
let w32 = "W32"
let w64 = "W64"
let wnat = "WNAT"

let arms n =
  if n <= 2 then "ARMS_2" else if n <= 4 then "ARMS_3_4"
  else if n <= 8 then "ARMS_5_8" else "ARMS_9P"

let arms_buckets = ["ARMS_2"; "ARMS_3_4"; "ARMS_5_8"; "ARMS_9P"]
let preds = [pred_eq; pred_ne; pred_lt; pred_le; pred_gt; pred_ge]

(* Raw extern names: "EXT:<native name>"; Python maps them to the frozen
   whitelist or EXT_OTHER. *)
let ext name = "EXT:" ^ name
let n_extern_buckets = 65  (* top-64 whitelist + EXT_OTHER *)

(* Signature block (D1.12): a function's own arity and return kind. Its root
   Lfunction node is owned by the parent, so its own vector lacks both. *)
let arity_feature n = "ARITY_" ^ (if n >= 4 then "4P" else string_of_int n)
let arity_features = List.map arity_feature [1; 2; 3; 4]
let return_feature (t : lty) = "RET_" ^ lty_name t
let return_features = List.map return_feature [INT; FLOAT; BINT; GEN]

let lambda_count_features =
  [call_self; call_local; call_stdlib; call_module; call_dynamic;
   tail; nontail; mut_; immut] @ preds @ arms_buckets @ [w32; w64; wnat]
  @ arity_features @ return_features

(* Rare-family merge candidates (schema §1.6). Applied by Python's
   freeze-config only if every member is rare; P_ATOMIC is dropped on 5.5.1,
   where it would have a single member (D3.2). *)
let lambda_merge_families =
  [ "P_RAW_LOAD",
    [ "Pstring_load_16"; "Pstring_load_32"; "Pstring_load_64";
      "Pbytes_load_16"; "Pbytes_load_32"; "Pbytes_load_64";
      "Pbigstring_load_16"; "Pbigstring_load_32"; "Pbigstring_load_64" ];
    "P_RAW_STORE",
    [ "Pbytes_set_16"; "Pbytes_set_32"; "Pbytes_set_64";
      "Pbigstring_set_16"; "Pbigstring_set_32"; "Pbigstring_set_64" ];
    "P_BIGARRAY", [ "Pbigarrayref"; "Pbigarrayset"; "Pbigarraydim" ];
    "P_BSWAP", [ "Pbswap16"; "Pbbswap" ] ]

(* Entities that cannot occur on the pinned path (native, non-flambda,
   tsan: false). Excluded from the vocabulary; an occurrence at inference is a
   hard error: it means a hook or lowering bug (D4.1). *)
let lambda_impossible =
  [ "Psetglobal",
    "only transl_implementation (bytecode/flambda) and transl_package \
     (bytecode) emit it; native closure mode uses transl_store_*" ]

(* Deterministic fallbacks for entities that can occur but may have no
   training triples: (entity, trained stand-in, reason). freeze-config applies
   one only if the entity has no triples after merges (D4.2). *)
let lambda_fallbacks =
  [ "Ppoll", "Pccall", "Sys.poll_actions: a runtime call with no result kind";
    "Pduprecord", "Pduparray", "copy of an immutable block";
    "Pint_as_pointer", "Popaque", "identity-like, unknown result kind";
    "Psetfloatfield", "Psetfield", "field store of a float record";
    "Pfloatfield", "Pfield", "field load of a float record";
    "Pbytes_of_string", "Pbytes_to_string", "the converse identity copy";
    "Pbytes_to_string", "Pbytes_of_string", "the converse identity copy";
    "Pmakelazyblock", "Pmakeblock", "block allocation";
    "Patomic_load", "Pfield", "a (relaxed) field load";
    "Pdls_get", "Pfield", "a field load from domain-local state";
    "Preperform", "Pperform", "effect performance";
    "Presume", "Prunstack", "continuation resumption";
    "Prunstack", "Presume", "continuation resumption" ]

(* ------------------------------------------------------------------ *)
(* Cmm level                                                            *)

let cmm_types = ["INT"; "VAL"; "ADDR"; "FLOAT"]

let c_var_int = "VAR_INT"
let c_var_val = "VAR_VAL"
let c_var_addr = "VAR_ADDR"
let c_var_float = "VAR_FLOAT"
let c_const_int = "CONST_INT"
let c_const_natint = "CONST_NATINT"
let c_const_float = "CONST_FLOAT"
let sym_func = "SYM_FUNC"
let sym_data = "SYM_DATA"
let sym_extern = "SYM_EXTERN"

let cmm_operand_kinds =
  [c_var_int; c_var_val; c_var_addr; c_var_float;
   c_const_int; c_const_natint; c_const_float; sym_func; sym_data; sym_extern]

(* Cload / Cstore split by memory chunk: (memory_chunk constructor, suffix). *)
let chunk_split_ctors = ["Cload"; "Cstore"]

let chunk_suffixes =
  [ "Byte_unsigned", "byte_u"; "Byte_signed", "byte_s";
    "Sixteen_unsigned", "16u"; "Sixteen_signed", "16s";
    "Thirtytwo_unsigned", "32u"; "Thirtytwo_signed", "32s";
    "Sixtyfour", "64"; "Word_int", "word_int"; "Word_val", "word_val";
    "Single", "single"; "Double", "double" ]

let with_chunk ctor chunk_ctor =
  match List.assoc_opt chunk_ctor chunk_suffixes with
  | Some s -> ctor ^ "_" ^ s
  | None -> invalid_arg ("unknown memory_chunk " ^ chunk_ctor)

(* Structural opcodes introduced by the Cmm -> TAC lowering (schema §2.2). *)
let copy = "COPY"
let assign = "ASSIGN"
let br = "BR"
let switch = "SWITCH"
let jump = "JUMP"
let ret = "RET"
let tuple = "TUPLE"
let return_addr = "RETURN_ADDR"

let cmm_structural = [copy; assign; br; switch; jump; ret; tuple; return_addr]

(* Rare-family merge candidates (schema §2.6; C_RUNTIME without the
   Catomic_fetch_add that 5.5.1 lacks). *)
let cmm_merge_families =
  [ "Cload_narrow", [ "Cload_16u"; "Cload_16s"; "Cload_32u"; "Cload_32s"; "Cload_64" ];
    "Cstore_narrow",
    [ "Cstore_16u"; "Cstore_16s"; "Cstore_32u"; "Cstore_32s"; "Cstore_64" ];
    "C_RUNTIME", [ "Cdls_get"; "Cpoll"; return_addr ] ]

let cmm_impossible =
  [ return_addr,
    "only Thread_sanitizer.instrument emits Creturn_addr; the switch has tsan: false" ]

let cmm_fallbacks =
  [ "Cload_single", "Cload_double", "float load of the other width";
    "Cstore_single", "Cstore_double", "float store of the other width";
    "Cload_byte_s", "Cload_byte_u", "same width, other signedness";
    "Cstore_byte_s", "Cstore_byte_u", "same width, other signedness";
    "Cload_16s", "Cload_16u", "same width, other signedness";
    "Cstore_16s", "Cstore_16u", "same width, other signedness";
    "Cload_32s", "Cload_32u", "same width, other signedness";
    "Cstore_32s", "Cstore_32u", "same width, other signedness";
    tuple, copy, "structural move of operands into a value";
    "Cpoll", "Cextcall", "a runtime call with a side effect";
    "Cdls_get", "Cload_word_val", "a value load from domain-local state" ]

let cmm_relations =
  ["Type"; "Arg0"; "Arg1"; "Arg2"; "Arg3"; "Arg4+"; "Next"; "Succ"]

let alloc = "ALLOC"
let noalloc = "NOALLOC"
let load_mut = "LOAD_MUT"
let load_immut = "LOAD_IMMUT"
let load_atomic = "LOAD_ATOMIC"          (* D0.16 *)
let load_nonatomic = "LOAD_NONATOMIC"
let init = "INIT"
let assign_store = "ASSIGN_STORE"

let cmm_count_features =
  preds @ [alloc; noalloc; load_mut; load_immut; load_atomic; load_nonatomic;
           init; assign_store]
  @ arms_buckets
