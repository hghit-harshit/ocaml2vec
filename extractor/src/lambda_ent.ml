(* Constructor -> entity mappings for Lambda (schema §1.2–§1.4, §1.7).
   Warning 4 (fragile match, i.e. any wildcard over a variant) and warning 8
   (non-exhaustive) are errors in this module: a constructor added to or
   removed from the pinned compiler breaks the build. *)
[@@@ocaml.warning "+4+8"]
[@@@ocaml.warnerror "+4+8"]

open Lambda
module E = Entities

type type_emission = Fixed of E.lty | Instance of E.lty | NoType

let ty_of_value_kind : value_kind -> E.lty = function
  | Pgenval -> GEN | Pintval -> INT | Pfloatval -> FLOAT
  | Pboxedintval _ -> BINT

let ty_of_array_kind : array_kind -> E.lty = function
  | Pgenarray -> GEN | Paddrarray -> ADDR | Pintarray -> INT
  | Pfloatarray -> FLOAT

(* Operand kind of an [Lvar] whose binding kind is known (schema §1.3). *)
let var_kind : value_kind -> string = function
  | Pgenval -> E.var_gen | Pintval -> E.var_int | Pfloatval -> E.var_float
  | Pboxedintval _ -> E.var_bint

let const_kind : structured_constant -> string = function
  | Const_int _ | Const_char _ -> E.const_int
  | Const_float _ -> E.const_float
  | Const_int32 _ | Const_int64 _ | Const_nativeint _ -> E.const_bint
  | Const_immstring _ -> E.const_string
  | Const_block _ | Const_float_array _ -> E.const_block

let global_class ~self id : E.global_class =
  let name = Ident.name id in
  if Ident.same id self then Self
  else if name = "Stdlib" || String.starts_with ~prefix:"Stdlib__" name then
    Stdlib
  else Other

let prim_opcode ~self : primitive -> string = function
  | Pgetglobal id -> E.with_global (global_class ~self id)
  | Pbytes_to_string -> "Pbytes_to_string" | Pbytes_of_string -> "Pbytes_of_string"
  | Pignore -> "Pignore" | Psetglobal _ -> "Psetglobal"
  | Pmakeblock _ -> "Pmakeblock" | Pmakelazyblock _ -> "Pmakelazyblock"
  | Pfield _ -> "Pfield" | Pfield_computed -> "Pfield_computed"
  | Psetfield _ -> "Psetfield" | Psetfield_computed _ -> "Psetfield_computed"
  | Pfloatfield _ -> "Pfloatfield" | Psetfloatfield _ -> "Psetfloatfield"
  | Pduprecord _ -> "Pduprecord"
  | Prunstack -> "Prunstack" | Pperform -> "Pperform" | Presume -> "Presume"
  | Preperform -> "Preperform"
  | Pccall _ -> "Pccall" | Praise _ -> "Praise"
  | Psequand -> "Psequand" | Psequor -> "Psequor" | Pnot -> "Pnot"
  | Pnegint -> "Pnegint" | Paddint -> "Paddint" | Psubint -> "Psubint"
  | Pmulint -> "Pmulint" | Pdivint _ -> "Pdivint" | Pmodint _ -> "Pmodint"
  | Pandint -> "Pandint" | Porint -> "Porint" | Pxorint -> "Pxorint"
  | Plslint -> "Plslint" | Plsrint -> "Plsrint" | Pasrint -> "Pasrint"
  | Pintcomp _ -> "Pintcomp"
  | Pcompare_ints -> "Pcompare_ints" | Pcompare_floats -> "Pcompare_floats"
  | Pcompare_bints _ -> "Pcompare_bints"
  | Poffsetint _ -> "Poffsetint" | Poffsetref _ -> "Poffsetref"
  | Pintoffloat -> "Pintoffloat" | Pfloatofint -> "Pfloatofint"
  | Pnegfloat -> "Pnegfloat" | Pabsfloat -> "Pabsfloat"
  | Paddfloat -> "Paddfloat" | Psubfloat -> "Psubfloat"
  | Pmulfloat -> "Pmulfloat" | Pdivfloat -> "Pdivfloat"
  | Pfloatcomp _ -> "Pfloatcomp"
  | Pstringlength -> "Pstringlength" | Pstringrefu -> "Pstringrefu"
  | Pstringrefs -> "Pstringrefs"
  | Pbyteslength -> "Pbyteslength" | Pbytesrefu -> "Pbytesrefu"
  | Pbytessetu -> "Pbytessetu" | Pbytesrefs -> "Pbytesrefs"
  | Pbytessets -> "Pbytessets"
  | Pmakearray _ -> "Pmakearray" | Pduparray _ -> "Pduparray"
  | Parraylength _ -> "Parraylength" | Parrayrefu _ -> "Parrayrefu"
  | Parraysetu _ -> "Parraysetu" | Parrayrefs _ -> "Parrayrefs"
  | Parraysets _ -> "Parraysets"
  | Pisint -> "Pisint" | Pisout -> "Pisout"
  | Pbintofint _ -> "Pbintofint" | Pintofbint _ -> "Pintofbint"
  | Pcvtbint _ -> "Pcvtbint" | Pnegbint _ -> "Pnegbint"
  | Paddbint _ -> "Paddbint" | Psubbint _ -> "Psubbint"
  | Pmulbint _ -> "Pmulbint" | Pdivbint _ -> "Pdivbint"
  | Pmodbint _ -> "Pmodbint" | Pandbint _ -> "Pandbint"
  | Porbint _ -> "Porbint" | Pxorbint _ -> "Pxorbint"
  | Plslbint _ -> "Plslbint" | Plsrbint _ -> "Plsrbint"
  | Pasrbint _ -> "Pasrbint" | Pbintcomp _ -> "Pbintcomp"
  | Pbigarrayref _ -> "Pbigarrayref" | Pbigarrayset _ -> "Pbigarrayset"
  | Pbigarraydim _ -> "Pbigarraydim"
  | Pstring_load_16 _ -> "Pstring_load_16" | Pstring_load_32 _ -> "Pstring_load_32"
  | Pstring_load_64 _ -> "Pstring_load_64"
  | Pbytes_load_16 _ -> "Pbytes_load_16" | Pbytes_load_32 _ -> "Pbytes_load_32"
  | Pbytes_load_64 _ -> "Pbytes_load_64"
  | Pbytes_set_16 _ -> "Pbytes_set_16" | Pbytes_set_32 _ -> "Pbytes_set_32"
  | Pbytes_set_64 _ -> "Pbytes_set_64"
  | Pbigstring_load_16 _ -> "Pbigstring_load_16"
  | Pbigstring_load_32 _ -> "Pbigstring_load_32"
  | Pbigstring_load_64 _ -> "Pbigstring_load_64"
  | Pbigstring_set_16 _ -> "Pbigstring_set_16"
  | Pbigstring_set_32 _ -> "Pbigstring_set_32"
  | Pbigstring_set_64 _ -> "Pbigstring_set_64"
  | Pctconst _ -> "Pctconst" | Pbswap16 -> "Pbswap16" | Pbbswap _ -> "Pbbswap"
  | Pint_as_pointer -> "Pint_as_pointer" | Patomic_load -> "Patomic_load"
  | Popaque -> "Popaque" | Pdls_get -> "Pdls_get" | Ppoll -> "Ppoll"

(* Opcode of a non-leaf node. Leaves and transparent nodes are not nodes. *)
let node_opcode ~self : lambda -> string = function
  | Lapply ap -> E.with_arity "Lapply" (List.length ap.ap_args)
  | Lfunction lf -> E.with_arity "Lfunction" (List.length lf.params)
  | Llet _ -> "Llet" | Lmutlet _ -> "Lmutlet" | Lletrec _ -> "Lletrec"
  | Lprim (p, _, _) -> prim_opcode ~self p
  | Lswitch _ -> "Lswitch" | Lstringswitch _ -> "Lstringswitch"
  | Lstaticraise _ -> "Lstaticraise" | Lstaticcatch _ -> "Lstaticcatch"
  | Ltrywith _ -> "Ltrywith" | Lifthenelse _ -> "Lifthenelse"
  | Lsequence _ -> "Lsequence" | Lwhile _ -> "Lwhile" | Lfor _ -> "Lfor"
  | Lassign _ -> "Lassign" | Lsend _ -> "Lsend"
  | (Lvar _ | Lmutvar _ | Lconst _ | Levent _ | Lifused _) as l ->
      invalid_arg
        (Format.asprintf "node_opcode: not a node: %a" Printlambda.lambda l)

(* Type emission, schema §1.4. *)
let prim_type : primitive -> type_emission = function
  | Pnegint | Paddint | Psubint | Pmulint | Pdivint _ | Pmodint _ | Pandint
  | Porint | Pxorint | Plslint | Plsrint | Pasrint | Poffsetint _ | Pintcomp _
  | Pcompare_ints | Pcompare_floats | Pcompare_bints _ | Pfloatcomp _
  | Pbintcomp _ | Pnot | Psequand | Psequor | Pisint | Pisout | Pstringlength
  | Pbyteslength | Parraylength _ | Pstringrefu | Pstringrefs | Pbytesrefu
  | Pbytesrefs | Pintoffloat | Pintofbint _ | Pbswap16 | Pbigarraydim _
  | Pctconst _ | Pstring_load_16 _ | Pbytes_load_16 _ | Pbigstring_load_16 _ ->
      Fixed INT
  | Paddfloat | Psubfloat | Pmulfloat | Pdivfloat | Pnegfloat | Pabsfloat
  | Pfloatofint | Pfloatfield _ ->
      Fixed FLOAT
  | Pbintofint _ | Pcvtbint _ | Pnegbint _ | Paddbint _ | Psubbint _
  | Pmulbint _ | Pdivbint _ | Pmodbint _ | Pandbint _ | Porbint _ | Pxorbint _
  | Plslbint _ | Plsrbint _ | Pasrbint _ | Pbbswap _ | Pstring_load_32 _
  | Pstring_load_64 _ | Pbytes_load_32 _ | Pbytes_load_64 _
  | Pbigstring_load_32 _ | Pbigstring_load_64 _ ->
      Fixed BINT
  | Pmakeblock _ | Pmakelazyblock _ | Pduprecord _ | Pmakearray _ | Pduparray _
  | Pfield_computed | Pbytes_to_string | Pbytes_of_string | Pgetglobal _ ->
      Fixed GEN
  | Pfield (_, Immediate, _) -> Instance INT
  | Pfield (_, Pointer, _) -> Instance GEN
  | Parrayrefu k | Parrayrefs k -> Instance (ty_of_array_kind k)
  (* setters and unit-returning primitives *)
  | Psetglobal _ | Psetfield _ | Psetfield_computed _ | Psetfloatfield _
  | Parraysetu _ | Parraysets _ | Pbytessetu | Pbytessets | Pbytes_set_16 _
  | Pbytes_set_32 _ | Pbytes_set_64 _ | Pbigstring_set_16 _
  | Pbigstring_set_32 _ | Pbigstring_set_64 _ | Pbigarrayset _ | Poffsetref _
  | Pignore | Ppoll
  (* unknown result kind *)
  | Pccall _ | Praise _ | Popaque | Pint_as_pointer | Pbigarrayref _
  | Prunstack | Pperform | Presume | Preperform | Patomic_load | Pdls_get ->
      NoType

let node_type : lambda -> type_emission = function
  | Llet (_, k, _, _, _) | Lmutlet (k, _, _, _) -> Instance (ty_of_value_kind k)
  | Lfunction lf -> Instance (ty_of_value_kind lf.return)
  | Lprim (p, _, _) -> prim_type p
  | Lapply _ | Lletrec _ | Lifthenelse _ | Lswitch _ | Lstringswitch _
  | Lstaticraise _ | Lstaticcatch _ | Ltrywith _ | Lsequence _ | Lwhile _
  | Lfor _ | Lassign _ | Lsend _ ->
      NoType
  | (Lvar _ | Lmutvar _ | Lconst _ | Levent _ | Lifused _) as l ->
      invalid_arg
        (Format.asprintf "node_type: not a node: %a" Printlambda.lambda l)

(* Count features carried by a primitive (schema §1.7, except callee/tail,
   which need the traversal). *)
let mut_feature : Asttypes.mutable_flag -> string = function
  | Mutable -> E.mut_ | Immutable -> E.immut

let pred_feature : integer_comparison -> string = function
  | Ceq -> E.pred_eq | Cne -> E.pred_ne | Clt -> E.pred_lt | Cle -> E.pred_le
  | Cgt -> E.pred_gt | Cge -> E.pred_ge

(* Negated float comparisons map to their base predicate. *)
let fpred_feature : float_comparison -> string = function
  | CFeq -> E.pred_eq | CFneq -> E.pred_ne
  | CFlt | CFnlt -> E.pred_lt | CFle | CFnle -> E.pred_le
  | CFgt | CFngt -> E.pred_gt | CFge | CFnge -> E.pred_ge

let width_feature : boxed_integer -> string = function
  | Pint32 -> E.w32 | Pint64 -> E.w64 | Pnativeint -> E.wnat

let prim_counts : primitive -> string list = function
  | Pmakeblock (_, m, _) | Pfield (_, _, m) | Pmakearray (_, m)
  | Pduparray (_, m) -> [mut_feature m]
  | Pintcomp c -> [pred_feature c]
  | Pfloatcomp c -> [fpred_feature c]
  | Pbintcomp (w, c) -> [width_feature w; pred_feature c]
  (* Pcvtbint counts both source and destination widths. *)
  | Pcvtbint (src, dst) -> [width_feature src; width_feature dst]
  | Pcompare_bints w | Pbintofint w | Pintofbint w | Pnegbint w | Paddbint w
  | Psubbint w | Pmulbint w | Pdivbint { size = w; _ }
  | Pmodbint { size = w; _ } | Pandbint w | Porbint w | Pxorbint w
  | Plslbint w | Plsrbint w | Pasrbint w | Pbbswap w -> [width_feature w]
  | Pccall d -> [E.ext (Primitive.native_name d)]
  | Pgetglobal _ | Psetglobal _ | Pbytes_to_string | Pbytes_of_string | Pignore
  | Pmakelazyblock _ | Pfield_computed | Psetfield _ | Psetfield_computed _
  | Pfloatfield _ | Psetfloatfield _ | Pduprecord _ | Prunstack | Pperform
  | Presume | Preperform | Praise _ | Psequand | Psequor | Pnot | Pnegint
  | Paddint | Psubint | Pmulint | Pdivint _ | Pmodint _ | Pandint | Porint
  | Pxorint | Plslint | Plsrint | Pasrint | Pcompare_ints | Pcompare_floats
  | Poffsetint _ | Poffsetref _ | Pintoffloat | Pfloatofint | Pnegfloat
  | Pabsfloat | Paddfloat | Psubfloat | Pmulfloat | Pdivfloat | Pstringlength
  | Pstringrefu | Pstringrefs | Pbyteslength | Pbytesrefu | Pbytessetu
  | Pbytesrefs | Pbytessets | Parraylength _ | Parrayrefu _ | Parraysetu _
  | Parrayrefs _ | Parraysets _ | Pisint | Pisout | Pbigarrayref _
  | Pbigarrayset _ | Pbigarraydim _ | Pstring_load_16 _ | Pstring_load_32 _
  | Pstring_load_64 _ | Pbytes_load_16 _ | Pbytes_load_32 _ | Pbytes_load_64 _
  | Pbytes_set_16 _ | Pbytes_set_32 _ | Pbytes_set_64 _ | Pbigstring_load_16 _
  | Pbigstring_load_32 _ | Pbigstring_load_64 _ | Pbigstring_set_16 _
  | Pbigstring_set_32 _ | Pbigstring_set_64 _ | Pctconst _ | Pbswap16
  | Pint_as_pointer | Patomic_load | Popaque | Pdls_get | Ppoll -> []
