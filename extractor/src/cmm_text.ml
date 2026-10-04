(* Human-readable Cmm, for inspection only (never read back, never an
   entity source):
   - [tree]: the dumped Cmm.phrase list as an S-expression, with every
     constructor spelled out (Cop Ccmpi(Cle) ...), unlike -dcmm's "<=";
   - [tac]: the lowered three-address code + CFG of Cmm_lower, i.e. exactly
     what Cmm_abs serialises, with full opcodes and constant literals.
   Variables are named as in the JSON ("name/stamp"). As in [Cmm_ent],
   warnings 4 and 8 are errors so a compiler change cannot print wrongly. *)
[@@@ocaml.warning "+4+8"]
[@@@ocaml.warnerror "+4+8"]

open Cmm
module L = Cmm_lower

let comp_name : machtype_component -> string = function
  | Val -> "Val" | Addr -> "Addr" | Int -> "Int" | Float -> "Float"

let machtype (m : machtype) =
  if Array.length m = 0 then "Void"
  else String.concat "," (Array.to_list (Array.map comp_name m))

let header (h : Dump.header) =
  Printf.sprintf "; unit %s  source %s  ocaml %s\n" h.unit_name h.source h.ocaml

(* ---- tree ---- *)

type sexp = A of string | S of sexp list

let rec flat = function
  | A s -> s
  | S l -> "(" ^ String.concat " " (List.map flat l) ^ ")"

let width = 100

(* Flat if it fits; otherwise the leading atoms stay on the head line and the
   remaining children go one per line, indented by two. *)
let rec pp buf ind t =
  let f = flat t in
  match t with
  | A _ -> Buffer.add_string buf f
  | S _ when ind + String.length f <= width -> Buffer.add_string buf f
  | S l ->
      let rec heads acc = function
        | A s :: rest -> heads (s :: acc) rest
        | (S _ :: _ | []) as rest -> (List.rev acc, rest)
      in
      let hs, rest = heads [] l in
      Buffer.add_string buf ("(" ^ String.concat " " hs);
      List.iter
        (fun c ->
           Buffer.add_char buf '\n';
           Buffer.add_string buf (String.make (ind + 2) ' ');
           pp buf (ind + 2) c)
        rest;
      Buffer.add_char buf ')'

let var v = A (Util.ident_key v)
let var_p vp = var (Backend_var.With_provenance.var vp)

let phantom : phantom_defining_expr option -> sexp = function
  | None -> A "None"
  | Some (Cphantom_const_int n) -> S [A "Cphantom_const_int"; A (Targetint.to_string n)]
  | Some (Cphantom_const_symbol s) -> S [A "Cphantom_const_symbol"; A s]
  | Some (Cphantom_var v) -> S [A "Cphantom_var"; var v]
  | Some (Cphantom_offset_var { var = v; offset_in_words }) ->
      S [A "Cphantom_offset_var"; var v; A (string_of_int offset_in_words)]
  | Some (Cphantom_read_field { var = v; field }) ->
      S [A "Cphantom_read_field"; var v; A (string_of_int field)]
  | Some (Cphantom_read_symbol_field { sym; field }) ->
      S [A "Cphantom_read_symbol_field"; A sym; A (string_of_int field)]
  | Some (Cphantom_block { tag; fields }) ->
      S (A "Cphantom_block" :: A (string_of_int tag) :: List.map var fields)

let rec expr : expression -> sexp = function
  | Cconst_int (n, _) -> S [A "Cconst_int"; A (string_of_int n)]
  | Cconst_natint (n, _) -> S [A "Cconst_natint"; A (Nativeint.to_string n ^ "n")]
  | Cconst_float (f, _) -> S [A "Cconst_float"; A (L.float_lit f)]
  | Cconst_symbol (s, _) -> S [A "Cconst_symbol"; A s]
  | Cvar v -> S [A "Cvar"; var v]
  | Cvar_mut v -> S [A "Cvar_mut"; var v]
  | Clet (vp, def, body) -> S [A "Clet"; var_p vp; expr def; expr body]
  | Clet_mut (vp, mt, def, body) ->
      S [A "Clet_mut"; var_p vp; A (machtype mt); expr def; expr body]
  | Cphantom_let (vp, def, body) -> S [A "Cphantom_let"; var_p vp; phantom def; expr body]
  | Cassign (v, e) -> S [A "Cassign"; var v; expr e]
  | Ctuple es -> S (A "Ctuple" :: List.map expr es)
  | Cop (op, es, _) -> S (A "Cop" :: A (Cmm_ent.opcode_full op) :: List.map expr es)
  | Csequence (a, b) -> S [A "Csequence"; expr a; expr b]
  | Cifthenelse (c, _, t, _, f, _) -> S [A "Cifthenelse"; expr c; expr t; expr f]
  | Cswitch (e, index, cases, _) ->
      S (A "Cswitch" :: expr e
         :: S (A "index" :: Array.to_list (Array.map (fun i -> A (string_of_int i)) index))
         :: Array.to_list
              (Array.mapi (fun i (c, _) -> S [A ("case" ^ string_of_int i); expr c]) cases))
  | Ccatch (rf, handlers, body) ->
      S (A "Ccatch"
         :: A (match rf with Recursive -> "Recursive" | Nonrecursive -> "Nonrecursive")
         :: expr body
         :: List.map
              (fun (n, params, h, _) ->
                 S [A "handler"; A (string_of_int n);
                    S (List.map (fun (vp, mt) -> S [var_p vp; A (machtype mt)]) params);
                    expr h])
              handlers)
  | Cexit (n, es) -> S (A "Cexit" :: A (string_of_int n) :: List.map expr es)
  | Ctrywith (body, vp, h, _) -> S [A "Ctrywith"; expr body; var_p vp; expr h]
  | Creturn_addr -> A "Creturn_addr"

let data_item : data_item -> sexp = function
  | Cdefine_symbol s -> S [A "Cdefine_symbol"; A s]
  | Cglobal_symbol s -> S [A "Cglobal_symbol"; A s]
  | Cint8 n -> S [A "Cint8"; A (string_of_int n)]
  | Cint16 n -> S [A "Cint16"; A (string_of_int n)]
  | Cint32 n -> S [A "Cint32"; A (Nativeint.to_string n)]
  | Cint n -> S [A "Cint"; A (Nativeint.to_string n)]
  | Csingle f -> S [A "Csingle"; A (L.float_lit f)]
  | Cdouble f -> S [A "Cdouble"; A (L.float_lit f)]
  | Csymbol_address s -> S [A "Csymbol_address"; A s]
  | Cstring s -> S [A "Cstring"; A ("\"" ^ String.escaped s ^ "\"")]
  | Cskip n -> S [A "Cskip"; A (string_of_int n)]
  | Calign n -> S [A "Calign"; A (string_of_int n)]

let phrase : phrase -> sexp = function
  | Cfunction fd ->
      S [A "Cfunction"; A fd.fun_name;
         S (List.map (fun (vp, mt) -> S [var_p vp; A (machtype mt)]) fd.fun_args);
         expr fd.fun_body]
  | Cdata items -> S (A "Cdata" :: List.map data_item items)

let tree (h : Dump.header) (phrases : phrase list) : string =
  let buf = Buffer.create 4096 in
  Buffer.add_string buf (header h);
  List.iter (fun p -> Buffer.add_char buf '\n'; pp buf 0 (phrase p); Buffer.add_char buf '\n')
    phrases;
  Buffer.contents buf

(* ---- tac ---- *)

let operand : L.operand -> string = function
  | L.Var x -> x
  | L.Const (_, lit) -> lit
  | L.Sym s -> "&" ^ s

let blocks_list l = String.concat ", " (List.map (fun b -> "B" ^ string_of_int b) l)

let instr buf (b : L.block) (i : L.instr) =
  let body =
    (match i.dst with Some d -> d ^ " = " | None -> "")
    ^ i.display
    ^ (match i.args with [] -> "" | args -> " " ^ String.concat ", " (List.map operand args))
    ^ (if i.terminator && b.succ <> [] then " -> " ^ blocks_list b.succ else "")
  in
  let notes =
    (match i.ty with Some t -> [": " ^ comp_name t] | None -> [])
    @ (if i.synthetic then ["; synthetic"] else [])
  in
  Buffer.add_string buf
    (if notes = [] then Printf.sprintf "    %s\n" body
     else Printf.sprintf "    %-56s %s\n" body (String.concat " " notes))

let func buf (f : L.func) =
  Buffer.add_string buf
    (Printf.sprintf "\n%s (%s)\n" f.name
       (String.concat ", " (List.map (fun (x, t) -> x ^ ":" ^ comp_name t) f.params)));
  List.iter
    (fun (label, vs) ->
       if vs <> [] then
         Buffer.add_string buf (Printf.sprintf "  ; %s: %s\n" label (String.concat ", " vs)))
    ["mutable", f.mutable_vars; "join", f.join_vars; "handler params", f.handler_params];
  List.iter
    (fun (b : L.block) ->
       Buffer.add_string buf
         (Printf.sprintf "  B%d:%s\n" b.bid
            (if b.exn_succ = [] then "" else "    ; exn -> " ^ blocks_list b.exn_succ));
       List.iter (instr buf b) b.instrs)
    f.blocks

let tac (h : Dump.header) (phrases : phrase list) : string =
  let buf = Buffer.create 4096 in
  Buffer.add_string buf (header h);
  List.iter
    (function
      | Cfunction fd -> func buf (L.lower_fundecl fd)
      | Cdata _ -> ())
    phrases;
  Buffer.contents buf
