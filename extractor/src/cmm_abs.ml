(* Cmm phrases -> lowered TAC + CFG JSON (schema §2.1–§2.4, §2.7).
   Symbols are classified against the unit's own Cfunction and Cdata
   symbols: SYM_FUNC / SYM_DATA / SYM_EXTERN. *)

open Cmm
module E = Entities
module J = Json_out
module L = Cmm_lower

type symbols = { funcs : (string, unit) Hashtbl.t; data : (string, unit) Hashtbl.t }

let collect_symbols phrases =
  let s = { funcs = Hashtbl.create 16; data = Hashtbl.create 16 } in
  List.iter
    (function
      | Cfunction fd -> Hashtbl.replace s.funcs fd.fun_name ()
      | Cdata items ->
          List.iter
            (function
              | Cdefine_symbol sym -> Hashtbl.replace s.data sym ()
              | Cglobal_symbol _ | Cint8 _ | Cint16 _ | Cint32 _ | Cint _
              | Csingle _ | Cdouble _ | Csymbol_address _ | Cstring _ | Cskip _
              | Calign _ -> ())
            items)
    phrases;
  s

let sym_kind syms s =
  if Hashtbl.mem syms.funcs s then E.sym_func
  else if Hashtbl.mem syms.data s then E.sym_data
  else E.sym_extern

let json_operand syms (f : L.func) = function
  | L.Var x ->
      let t = Option.value ~default:Val (Hashtbl.find_opt f.var_types x) in
      J.Obj [ "kind", J.String (Cmm_ent.var_kind t); "var", J.String x ]
  | L.Const k -> J.Obj [ "kind", J.String k ]
  | L.Sym s -> J.Obj [ "kind", J.String (sym_kind syms s); "sym", J.String s ]

let json_instr syms f (i : L.instr) =
  J.Obj
    ([ "id", J.Int i.iid;
      "op", J.String i.op;
      "type", (match i.ty with Some t -> J.String (Cmm_ent.mty_name t) | None -> J.Null);
      "dst", (match i.dst with Some d -> J.String d | None -> J.Null);
      "operands", J.List (List.map (json_operand syms f) i.args);
      "side_effect", J.Bool i.side_effect;
      "terminator", J.Bool i.terminator ]
    @ (if i.synthetic then [ "synthetic", J.Bool true ] else []))

let ints l = J.List (List.map (fun i -> J.Int i) l)
let strings l = J.List (List.map (fun s -> J.String s) l)

let json_func syms (f : L.func) =
  let counts = Hashtbl.create 8 in
  List.iter (fun (b : L.block) ->
      List.iter (fun (i : L.instr) -> List.iter (Util.bump counts) i.counts) b.instrs)
    f.blocks;
  J.Obj
    [ "name", J.String f.name;
      "loc", Util.json_location (Debuginfo.to_location f.dbg);
      "params", J.List (List.map (fun (x, t) ->
          J.Obj [ "var", J.String x; "type", J.String (Cmm_ent.mty_name t) ]) f.params);
      "mutable_vars", strings f.mutable_vars;
      "join_vars", strings f.join_vars;
      "handler_params", strings f.handler_params;
      "blocks", J.List (List.map (fun (b : L.block) ->
          J.Obj [ "id", J.Int b.bid;
                  "instrs", J.List (List.map (json_instr syms f) b.instrs);
                  "succ", ints b.succ;
                  "exn_succ", ints b.exn_succ ]) f.blocks);
      "counts", Util.sorted_counts counts;
      "n_cops", J.Int f.n_cops;
      "dead_cops", J.Int f.dead_cops ]

let extract (h : Dump.header) (phrases : Cmm.phrase list) : J.t =
  let syms = collect_symbols phrases in
  let funcs =
    List.filter_map
      (function
        | Cfunction fd -> Some (json_func syms (L.lower_fundecl fd))
        | Cdata _ -> None)
      phrases
  in
  J.Obj
    [ "unit", J.String h.unit_name;
      "source", J.String h.source;
      "digest", J.String h.digest;
      "ocaml", J.String h.ocaml;
      "functions", J.List funcs ]
