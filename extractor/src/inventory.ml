(* Entity inventory generated from the pinned compiler's installed .mli files
   (DECISIONS.md D0.18): constructor lists are read from lambda.mli / cmm.mli
   with compiler-libs' parser, then the split/exclusion rules in [Entities]
   are applied. Output: docs/entities.<version>.json. *)

module E = Entities
module J = Json_out

let compiler_libs_dir () = Filename.concat Config.standard_library "compiler-libs"

let parse_mli path =
  let ic = open_in_bin path in
  Fun.protect ~finally:(fun () -> close_in ic) @@ fun () ->
  let lexbuf = Lexing.from_channel ic in
  Location.init lexbuf path;
  Parse.interface lexbuf

(* Constructor names of the variant type [name] declared in [sg]. *)
let variant_ctors (sg : Parsetree.signature) name =
  let found =
    List.concat_map
      (fun (item : Parsetree.signature_item) ->
         match item.psig_desc with
         | Psig_type (_, decls) ->
             List.filter_map
               (fun (d : Parsetree.type_declaration) ->
                  match d.ptype_kind with
                  | Ptype_variant cds when d.ptype_name.txt = name ->
                      Some (List.map (fun (cd : Parsetree.constructor_declaration)
                                        -> cd.pcd_name.txt) cds)
                  | _ -> None)
               decls
         | _ -> [])
      sg
  in
  match found with
  | [ctors] -> ctors
  | l -> failwith (Printf.sprintf "type %s: %d variant declarations" name (List.length l))

type ctors = {
  lambda : string list;
  primitive : string list;
  operation : string list;
  expression : string list;
  memory_chunk : string list;
}

let read_ctors ?(dir = compiler_libs_dir ()) () =
  let lam = parse_mli (Filename.concat dir "lambda.mli") in
  let cmm = parse_mli (Filename.concat dir "cmm.mli") in
  { lambda = variant_ctors lam "lambda";
    primitive = variant_ctors lam "primitive";
    operation = variant_ctors cmm "operation";
    expression = variant_ctors cmm "expression";
    memory_chunk = variant_ctors cmm "memory_chunk" }

let expand_arity ctor = List.map (fun s -> ctor ^ "_" ^ s) E.arity_suffixes

let lambda_forms c =
  List.concat_map
    (fun ctor ->
       if List.mem ctor E.lambda_leaf_ctors
       || List.mem ctor E.lambda_transparent_ctors
       || ctor = E.lambda_prim_ctor then []
       else if List.mem ctor E.arity_split_ctors then expand_arity ctor
       else [ctor])
    c.lambda

let lambda_prims c =
  List.concat_map
    (fun ctor ->
       if ctor = E.global_ctor then List.map (fun s -> ctor ^ "_" ^ s) E.global_suffixes
       else [ctor])
    c.primitive

let cmm_ops c =
  List.concat_map
    (fun ctor ->
       if List.mem ctor E.chunk_split_ctors then
         List.map (E.with_chunk ctor) c.memory_chunk
       else [ctor])
    c.operation

let lambda_entities c =
  lambda_forms c @ lambda_prims c @ E.lambda_types @ E.lambda_operand_kinds

let cmm_entities c = cmm_ops c @ E.cmm_structural @ E.cmm_types @ E.cmm_operand_kinds

let strings l = J.List (List.map (fun s -> J.String s) l)

let group name l = (name, J.Obj [ "count", J.Int (List.length l); "names", strings l ])

let families fams = J.Obj (List.map (fun (m, members) -> (m, strings members)) fams)

let reasons l = J.Obj (List.map (fun (e, why) -> (e, J.String why)) l)

let fallbacks l =
  J.Obj (List.map (fun (e, target, why) ->
      (e, J.Obj [ "target", J.String target; "reason", J.String why ])) l)

let to_json c =
  let forms = lambda_forms c and prims = lambda_prims c in
  let ops = cmm_ops c in
  let lambda_total = List.length (lambda_entities c) in
  let cmm_total = List.length (cmm_entities c) in
  J.Obj
    [ "ocaml", J.String Config.version;
      "generated_from", strings [ "compiler-libs/lambda.mli"; "compiler-libs/cmm.mli" ];
      "lambda", J.Obj
        [ "entities", J.Int lambda_total;
          group "forms" forms;
          group "primitives" prims;
          group "types" E.lambda_types;
          group "operand_kinds" E.lambda_operand_kinds;
          group "relations" E.lambda_relations;
          "merge_candidates", families E.lambda_merge_families;
          "impossible", reasons E.lambda_impossible;
          "fallback_candidates", fallbacks E.lambda_fallbacks;
          "computed_operand_kind", J.Obj
            (List.map (fun t -> (E.lty_name t, J.String (E.computed_operand_kind (Some t))))
               [E.INT; FLOAT; BINT; ADDR; GEN]
             @ [ "none", J.String (E.computed_operand_kind None) ]);
          "count_features", J.Obj
            [ "count", J.Int (List.length E.lambda_count_features + E.n_extern_buckets);
              "fixed", strings E.lambda_count_features;
              "extern_buckets", J.Int E.n_extern_buckets ] ];
      "cmm", J.Obj
        [ "entities", J.Int cmm_total;
          group "operations" ops;
          group "structural" E.cmm_structural;
          group "types" E.cmm_types;
          group "operand_kinds" E.cmm_operand_kinds;
          group "relations" E.cmm_relations;
          "merge_candidates", families E.cmm_merge_families;
          "impossible", reasons E.cmm_impossible;
          "fallback_candidates", fallbacks E.cmm_fallbacks;
          "count_features", J.Obj
            [ "count", J.Int (List.length E.cmm_count_features + E.n_extern_buckets);
              "fixed", strings E.cmm_count_features;
              "extern_buckets", J.Int E.n_extern_buckets ] ];
      "source_constructors", J.Obj
        [ "Lambda.lambda", strings c.lambda;
          "Lambda.primitive", strings c.primitive;
          "Cmm.operation", strings c.operation;
          "Cmm.expression", strings c.expression;
          "Cmm.memory_chunk", strings c.memory_chunk ] ]
