(* Inventory checks (DECISIONS.md D0.15, D0.18):
   1. entity totals are 148 (Lambda) and 77 (Cmm); count features 95 / 83
      (87 + the 8-dim signature block, D1.12);
   2. the exhaustive Lambda and Cmm mappers produce exactly the inventory's
      opcodes.
      One sample value per constructor is mapped; that the samples cover every
      constructor listed in lambda.mli is checked through their runtime
      representation (immediate index or block tag). *)

open Lambda
module E = Ir2vec.Entities
module Inv = Ir2vec.Inventory
module Ent = Ir2vec.Lambda_ent

let failures = ref 0

let check name cond detail =
  if cond then Printf.printf "ok   %s\n" name
  else (incr failures; Printf.printf "FAIL %s: %s\n" name (detail ()))

let set l = List.sort_uniq compare l

let diff a b =
  let a = set a and b = set b in
  Printf.sprintf "only in mapping: [%s]; only in inventory: [%s]"
    (String.concat " " (List.filter (fun x -> not (List.mem x b)) a))
    (String.concat " " (List.filter (fun x -> not (List.mem x a)) b))

(* Distinct constructors among [samples], by runtime representation. *)
let n_ctors samples =
  List.length
    (set (List.map (fun v ->
         let r = Obj.repr v in
         if Obj.is_int r then `Const (Obj.obj r : int) else `Block (Obj.tag r))
         samples))

let self = Ident.create_persistent "Unit"
let x = Ident.create_local "x"
let desc = Primitive.simple ~name:"caml_x" ~arity:1 ~alloc:false
let bk = Pbigarray_unknown and bl = Pbigarray_unknown_layout

let primitives : primitive list =
  [ Pbytes_to_string; Pbytes_of_string; Pignore;
    Pgetglobal self; Pgetglobal (Ident.create_persistent "Stdlib__List");
    Pgetglobal (Ident.create_persistent "Other");
    Psetglobal self; Pmakeblock (0, Immutable, None); Pmakelazyblock Lazy_tag;
    Pfield (0, Pointer, Mutable); Pfield_computed; Psetfield (0, Pointer, Assignment);
    Psetfield_computed (Pointer, Assignment); Pfloatfield 0;
    Psetfloatfield (0, Assignment); Pduprecord (Types.Record_regular, 1);
    Prunstack; Pperform; Presume; Preperform; Pccall desc; Praise Raise_regular;
    Psequand; Psequor; Pnot; Pnegint; Paddint; Psubint; Pmulint; Pdivint Safe;
    Pmodint Safe; Pandint; Porint; Pxorint; Plslint; Plsrint; Pasrint;
    Pintcomp Ceq; Pcompare_ints; Pcompare_floats; Pcompare_bints Pint32;
    Poffsetint 1; Poffsetref 1; Pintoffloat; Pfloatofint; Pnegfloat; Pabsfloat;
    Paddfloat; Psubfloat; Pmulfloat; Pdivfloat; Pfloatcomp CFeq; Pstringlength;
    Pstringrefu; Pstringrefs; Pbyteslength; Pbytesrefu; Pbytessetu; Pbytesrefs;
    Pbytessets; Pmakearray (Pgenarray, Mutable); Pduparray (Pgenarray, Mutable);
    Parraylength Pgenarray; Parrayrefu Pgenarray; Parraysetu Pgenarray;
    Parrayrefs Pgenarray; Parraysets Pgenarray; Pisint; Pisout; Pbintofint Pint32;
    Pintofbint Pint32; Pcvtbint (Pint32, Pint64); Pnegbint Pint32; Paddbint Pint32;
    Psubbint Pint32; Pmulbint Pint32; Pdivbint { size = Pint32; is_safe = Safe };
    Pmodbint { size = Pint32; is_safe = Safe }; Pandbint Pint32; Porbint Pint32;
    Pxorbint Pint32; Plslbint Pint32; Plsrbint Pint32; Pasrbint Pint32;
    Pbintcomp (Pint32, Ceq); Pbigarrayref (false, 1, bk, bl);
    Pbigarrayset (false, 1, bk, bl); Pbigarraydim 1; Pstring_load_16 false;
    Pstring_load_32 false; Pstring_load_64 false; Pbytes_load_16 false;
    Pbytes_load_32 false; Pbytes_load_64 false; Pbytes_set_16 false;
    Pbytes_set_32 false; Pbytes_set_64 false; Pbigstring_load_16 false;
    Pbigstring_load_32 false; Pbigstring_load_64 false; Pbigstring_set_16 false;
    Pbigstring_set_32 false; Pbigstring_set_64 false; Pctconst Word_size; Pbswap16;
    Pbbswap Pint32; Pint_as_pointer; Patomic_load; Popaque; Pdls_get; Ppoll ]

let v = Lvar x
let loc = Debuginfo.Scoped_location.Loc_unknown

let apply n =
  Lapply { ap_func = v; ap_args = List.init n (fun _ -> v); ap_loc = loc;
           ap_tailcall = Default_tailcall; ap_inlined = Default_inline;
           ap_specialised = Default_specialise }

let func n =
  Lfunction (lfunction' ~kind:Curried
               ~params:(List.init n (fun _ -> (Ident.create_local "p", Pgenval)))
               ~return:Pgenval ~body:v ~attr:default_function_attribute ~loc)

let event = { lev_loc = loc; lev_kind = Lev_pseudo; lev_repr = None; lev_env = Env.empty }

let lambdas : lambda list =
  [ v; Lmutvar x; Lconst (Const_int 0);
    apply 1; apply 2; apply 3; apply 4; apply 5;
    func 1; func 2; func 3; func 4; func 5;
    Llet (Strict, Pgenval, x, v, v); Lmutlet (Pgenval, x, v, v); Lletrec ([], v);
    Lprim (Paddint, [v; v], loc);
    Lswitch (v, { sw_numconsts = 0; sw_consts = []; sw_numblocks = 0;
                  sw_blocks = []; sw_failaction = None }, loc);
    Lstringswitch (v, [], None, loc); Lstaticraise (0, []);
    Lstaticcatch (v, (0, []), v); Ltrywith (v, x, v); Lifthenelse (v, v, v);
    Lsequence (v, v); Lwhile (v, v); Lfor (x, v, v, Upto, v); Lassign (x, v);
    Lsend (Public, v, v, [], loc); Levent (v, event); Lifused (x, v) ]

(* Cmm: one sample per operation, every memory chunk, every machtype. *)
let chunks : Cmm.memory_chunk list =
  Cmm.[ Byte_unsigned; Byte_signed; Sixteen_unsigned; Sixteen_signed;
    Thirtytwo_unsigned; Thirtytwo_signed; Sixtyfour; Word_int; Word_val;
    Single; Double ]

let operations : Cmm.operation list =
  Cmm.[ Capply typ_val; Cextcall ("f", typ_val, [], false); Calloc ]
  @ List.map (fun c -> Cmm.Cload { memory_chunk = c; mutability = Mutable;
                                   is_atomic = false }) chunks
  @ List.map (fun c -> Cmm.Cstore (c, Assignment)) chunks
  @ Cmm.[ Caddi; Csubi; Cmuli; Cmulhi; Cdivi; Cmodi; Cand; Cor; Cxor; Clsl; Clsr;
      Casr; Ccmpi Ceq; Caddv; Cadda; Ccmpa Ceq; Cnegf; Cabsf; Caddf; Csubf;
      Cmulf; Cdivf; Cfloatofint; Cintoffloat; Ccmpf CFeq; Craise Raise_regular;
      Ccheckbound; Copaque; Cdls_get; Cpoll ]

let machtypes : Cmm.machtype_component list = Cmm.[ Val; Addr; Int; Float ]

let node_name l =
  match Ent.node_opcode ~self l with
  | name -> Some name
  | exception Invalid_argument _ -> None

let () =
  let ctors = Inv.read_ctors () in
  let le = Inv.lambda_entities ctors and ce = Inv.cmm_entities ctors in
  check "lambda entities = 148" (List.length le = 148)
    (fun () -> string_of_int (List.length le));
  check "cmm entities = 77" (List.length ce = 77)
    (fun () -> string_of_int (List.length ce));
  check "entity names unique per level"
    (List.length (set le) = List.length le && List.length (set ce) = List.length ce)
    (fun () -> "duplicate entity name");
  let n_lcf = List.length E.lambda_count_features + E.n_extern_buckets in
  let n_ccf = List.length E.cmm_count_features + E.n_extern_buckets in
  check "lambda count features = 95" (n_lcf = 95) (fun () -> string_of_int n_lcf);
  check "cmm count features = 83" (n_ccf = 83) (fun () -> string_of_int n_ccf);

  (* primitives: samples cover lambda.mli, mapping = inventory *)
  let np = List.length ctors.primitive in
  check "primitive samples cover every constructor"
    (n_ctors primitives = np)
    (fun () -> Printf.sprintf "%d samples, %d constructors" (n_ctors primitives) np);
  let mapped = List.map (Ent.prim_opcode ~self) primitives in
  let inv = Inv.lambda_prims ctors in
  check "primitive mapping = inventory" (set mapped = set inv)
    (fun () -> diff mapped inv);

  (* lambda forms *)
  let nl = List.length ctors.lambda in
  check "lambda samples cover every constructor" (n_ctors lambdas = nl)
    (fun () -> Printf.sprintf "%d samples, %d constructors" (n_ctors lambdas) nl);
  let forms =
    List.filter_map
      (fun l -> match l with Lprim _ -> None | _ -> node_name l)
      lambdas
  in
  let inv_forms = Inv.lambda_forms ctors in
  check "form mapping = inventory" (set forms = set inv_forms)
    (fun () -> diff forms inv_forms);
  let non_nodes = List.filter (fun l -> node_name l = None) lambdas in
  check "exactly the 5 leaf/transparent constructors are non-nodes"
    (List.length non_nodes = 5)
    (fun () -> string_of_int (List.length non_nodes));

  (* Cmm operations / chunks / machtypes *)
  let no = List.length ctors.operation in
  check "operation samples cover every constructor" (n_ctors operations = no)
    (fun () -> Printf.sprintf "%d samples, %d constructors" (n_ctors operations) no);
  let nc = List.length ctors.memory_chunk in
  check "chunk samples cover every constructor" (n_ctors chunks = nc)
    (fun () -> Printf.sprintf "%d samples, %d constructors" (n_ctors chunks) nc);
  check "chunk names = cmm.mli"
    (set (List.map Ir2vec.Cmm_ent.chunk_ctor chunks) = set ctors.memory_chunk)
    (fun () -> diff (List.map Ir2vec.Cmm_ent.chunk_ctor chunks) ctors.memory_chunk);
  let ops = List.map Ir2vec.Cmm_ent.opcode operations in
  check "operation mapping = inventory" (set ops = set (Inv.cmm_ops ctors))
    (fun () -> diff ops (Inv.cmm_ops ctors));
  check "machtype names = inventory types"
    (n_ctors machtypes = 4
     && set (List.map Ir2vec.Cmm_ent.mty_name machtypes) = set E.cmm_types)
    (fun () -> "machtype mismatch");
  check "machtype operand kinds are Cmm operand kinds"
    (List.for_all (fun m -> List.mem (Ir2vec.Cmm_ent.var_kind m) E.cmm_operand_kinds)
       machtypes)
    (fun () -> "var_kind outside inventory");

  check "merge families are subsets of the inventory"
    (List.for_all (fun (_, ms) -> List.for_all (fun m -> List.mem m le) ms)
       E.lambda_merge_families
     && List.for_all (fun (_, ms) -> List.for_all (fun m -> List.mem m ce) ms)
       E.cmm_merge_families)
    (fun () -> "family member not in inventory");

  (* D4.1/D4.2: impossibility claims hold only on this compiler configuration *)
  check "pinned path is native, non-flambda, non-TSan"
    (not Config.flambda && not Config.tsan) (fun () -> "flambda or tsan enabled");
  let names l = List.map fst l in
  let fb_ok le fbs =
    List.for_all (fun (e, t, _) -> List.mem e le && List.mem t le && e <> t) fbs in
  check "impossible entities are inventory entities"
    (List.for_all (fun e -> List.mem e le) (names E.lambda_impossible)
     && List.for_all (fun e -> List.mem e ce) (names E.cmm_impossible))
    (fun () -> "impossible entity not in inventory");
  check "fallback entities and targets are inventory entities"
    (fb_ok le E.lambda_fallbacks && fb_ok ce E.cmm_fallbacks)
    (fun () -> "fallback outside inventory");

  (* every sample has a total Type function *)
  List.iter (fun p -> ignore (Ent.prim_type p : Ent.type_emission)) primitives;
  check "prim_type total on samples" true (fun () -> "");

  if !failures > 0 then exit 1
