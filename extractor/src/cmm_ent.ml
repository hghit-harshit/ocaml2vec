(* Constructor -> entity mappings for Cmm (schema §2.2–§2.4, §2.7, adjusted
   per DECISIONS.md D0.15/D0.16). As in [Lambda_ent], warnings 4 and 8 are
   errors: no wildcard over a variant, no missing constructor. *)
[@@@ocaml.warning "+4+8"]
[@@@ocaml.warnerror "+4+8"]

open Cmm
module E = Entities

let mty_name : machtype_component -> string = function
  | Val -> "VAL" | Addr -> "ADDR" | Int -> "INT" | Float -> "FLOAT"

let var_kind : machtype_component -> string = function
  | Val -> E.c_var_val | Addr -> E.c_var_addr | Int -> E.c_var_int
  | Float -> E.c_var_float

(* A machtype names a Type only if it has exactly one component. *)
let single (m : machtype) = if Array.length m = 1 then Some m.(0) else None

let chunk_ctor : memory_chunk -> string = function
  | Byte_unsigned -> "Byte_unsigned" | Byte_signed -> "Byte_signed"
  | Sixteen_unsigned -> "Sixteen_unsigned" | Sixteen_signed -> "Sixteen_signed"
  | Thirtytwo_unsigned -> "Thirtytwo_unsigned"
  | Thirtytwo_signed -> "Thirtytwo_signed" | Sixtyfour -> "Sixtyfour"
  | Word_int -> "Word_int" | Word_val -> "Word_val" | Single -> "Single"
  | Double -> "Double"

let opcode : operation -> string = function
  | Capply _ -> "Capply" | Cextcall _ -> "Cextcall"
  | Cload { memory_chunk; _ } -> E.with_chunk "Cload" (chunk_ctor memory_chunk)
  | Calloc -> "Calloc"
  | Cstore (c, _) -> E.with_chunk "Cstore" (chunk_ctor c)
  | Caddi -> "Caddi" | Csubi -> "Csubi" | Cmuli -> "Cmuli" | Cmulhi -> "Cmulhi"
  | Cdivi -> "Cdivi" | Cmodi -> "Cmodi" | Cand -> "Cand" | Cor -> "Cor"
  | Cxor -> "Cxor" | Clsl -> "Clsl" | Clsr -> "Clsr" | Casr -> "Casr"
  | Ccmpi _ -> "Ccmpi" | Caddv -> "Caddv" | Cadda -> "Cadda" | Ccmpa _ -> "Ccmpa"
  | Cnegf -> "Cnegf" | Cabsf -> "Cabsf" | Caddf -> "Caddf" | Csubf -> "Csubf"
  | Cmulf -> "Cmulf" | Cdivf -> "Cdivf" | Cfloatofint -> "Cfloatofint"
  | Cintoffloat -> "Cintoffloat" | Ccmpf _ -> "Ccmpf" | Craise _ -> "Craise"
  | Ccheckbound -> "Ccheckbound" | Copaque -> "Copaque" | Cdls_get -> "Cdls_get"
  | Cpoll -> "Cpoll"

(* Display only (cmm-tree / cmm-tac text): [opcode] plus the payload it drops.
   Never an entity name. *)
let int_cmp_name : integer_comparison -> string = function
  | Ceq -> "Ceq" | Cne -> "Cne" | Clt -> "Clt" | Cgt -> "Cgt" | Cle -> "Cle"
  | Cge -> "Cge"

let float_cmp_name : float_comparison -> string = function
  | CFeq -> "CFeq" | CFneq -> "CFneq" | CFlt -> "CFlt" | CFnlt -> "CFnlt"
  | CFgt -> "CFgt" | CFngt -> "CFngt" | CFle -> "CFle" | CFnle -> "CFnle"
  | CFge -> "CFge" | CFnge -> "CFnge"

let mut_name : Asttypes.mutable_flag -> string = function
  | Mutable -> "Mutable" | Immutable -> "Immutable"

let init_name : Lambda.initialization_or_assignment -> string = function
  | Assignment -> "Assignment" | Heap_initialization -> "Heap_initialization"
  | Root_initialization -> "Root_initialization"

let raise_name : Lambda.raise_kind -> string = function
  | Raise_regular -> "Raise_regular" | Raise_reraise -> "Raise_reraise"
  | Raise_notrace -> "Raise_notrace"

let opcode_full : operation -> string = function
  | Ccmpi c -> Printf.sprintf "Ccmpi(%s)" (int_cmp_name c)
  | Ccmpa c -> Printf.sprintf "Ccmpa(%s)" (int_cmp_name c)
  | Ccmpf c -> Printf.sprintf "Ccmpf(%s)" (float_cmp_name c)
  | Cextcall (name, _, _, alloc) ->
      Printf.sprintf "Cextcall(%s,%s)" name (if alloc then "alloc" else "noalloc")
  | Cload { memory_chunk; mutability; is_atomic } ->
      Printf.sprintf "Cload(%s,%s%s)" (chunk_ctor memory_chunk) (mut_name mutability)
        (if is_atomic then ",atomic" else "")
  | Cstore (c, init) -> Printf.sprintf "Cstore(%s,%s)" (chunk_ctor c) (init_name init)
  | Craise k -> Printf.sprintf "Craise(%s)" (raise_name k)
  | ( Capply _ | Calloc | Caddi | Csubi | Cmuli | Cmulhi | Cdivi | Cmodi | Cand
    | Cor | Cxor | Clsl | Clsr | Casr | Caddv | Cadda | Cnegf | Cabsf | Caddf
    | Csubf | Cmulf | Cdivf | Cfloatofint | Cintoffloat | Ccheckbound | Copaque
    | Cdls_get | Cpoll ) as op -> opcode op

(* Type emission, schema §2.4. *)
type type_emission =
  | Fixed of machtype_component
  | Result of machtype        (* Capply / Cextcall: declared result machtype *)
  | Of_arg0                   (* Copaque: its argument's machtype *)
  | NoType

let op_type : operation -> type_emission = function
  | Caddi | Csubi | Cmuli | Cmulhi | Cdivi | Cmodi | Cand | Cor | Cxor | Clsl
  | Clsr | Casr | Ccmpi _ | Ccmpa _ | Ccmpf _ | Cintoffloat ->
      Fixed Int
  | Cload { memory_chunk = ( Byte_unsigned | Byte_signed | Sixteen_unsigned
                           | Sixteen_signed | Thirtytwo_unsigned
                           | Thirtytwo_signed | Sixtyfour | Word_int ); _ } ->
      Fixed Int
  | Cload { memory_chunk = (Single | Double); _ } -> Fixed Float
  | Cload { memory_chunk = Word_val; _ } -> Fixed Val
  | Caddf | Csubf | Cmulf | Cdivf | Cnegf | Cabsf | Cfloatofint -> Fixed Float
  | Cadda -> Fixed Addr
  | Caddv | Calloc -> Fixed Val
  (* confirmed on 5.5.1: Selectgen.oper_result_type Cdls_get = typ_val (D2.14) *)
  | Cdls_get -> Fixed Val
  | Capply ty | Cextcall (_, ty, _, _) -> Result ty
  | Copaque -> Of_arg0
  | Cstore _ | Craise _ | Ccheckbound | Cpoll -> NoType

(* BUILD_SPEC Phase 2 side-effect list (Catomic_fetch_add absent in 5.5.1). *)
let side_effect : operation -> bool = function
  | Cstore _ | Capply _ | Cextcall _ | Craise _ | Ccheckbound | Cpoll -> true
  | Cload _ | Calloc | Caddi | Csubi | Cmuli | Cmulhi | Cdivi | Cmodi | Cand
  | Cor | Cxor | Clsl | Clsr | Casr | Ccmpi _ | Caddv | Cadda | Ccmpa _ | Cnegf
  | Cabsf | Caddf | Csubf | Cmulf | Cdivf | Cfloatofint | Cintoffloat | Ccmpf _
  | Copaque | Cdls_get -> false

(* Craise ends its basic block. *)
let is_terminator : operation -> bool = function
  | Craise _ -> true
  | Capply _ | Cextcall _ | Cload _ | Calloc | Cstore _ | Caddi | Csubi | Cmuli
  | Cmulhi | Cdivi | Cmodi | Cand | Cor | Cxor | Clsl | Clsr | Casr | Ccmpi _
  | Caddv | Cadda | Ccmpa _ | Cnegf | Cabsf | Caddf | Csubf | Cmulf | Cdivf
  | Cfloatofint | Cintoffloat | Ccmpf _ | Ccheckbound | Copaque | Cdls_get
  | Cpoll -> false

let pred_feature : integer_comparison -> string = Lambda_ent.pred_feature
let fpred_feature : float_comparison -> string = Lambda_ent.fpred_feature

let mut_feature : Asttypes.mutable_flag -> string = function
  | Mutable -> E.load_mut | Immutable -> E.load_immut

let store_feature : Lambda.initialization_or_assignment -> string = function
  | Assignment -> E.assign_store
  | Heap_initialization | Root_initialization -> E.init

(* Count features carried by an operation (schema §2.7 + D0.16). *)
let op_counts : operation -> string list = function
  | Ccmpi c | Ccmpa c -> [pred_feature c]
  | Ccmpf c -> [fpred_feature c]
  | Cextcall (name, _, _, alloc) ->
      [E.ext name; (if alloc then E.alloc else E.noalloc)]
  | Cload { mutability; is_atomic; _ } ->
      [mut_feature mutability;
       (if is_atomic then E.load_atomic else E.load_nonatomic)]
  | Cstore (_, init) -> [store_feature init]
  | Capply _ | Calloc | Caddi | Csubi | Cmuli | Cmulhi | Cdivi | Cmodi | Cand
  | Cor | Cxor | Clsl | Clsr | Casr | Caddv | Cadda | Cnegf | Cabsf | Caddf
  | Csubf | Cmulf | Cdivf | Cfloatofint | Cintoffloat | Craise _ | Ccheckbound
  | Copaque | Cdls_get | Cpoll -> []
