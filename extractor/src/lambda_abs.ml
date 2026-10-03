(* Lambda -> abstracted node records (schema §1, BUILD_SPEC Phase 1).

   Every non-leaf node gets a per-function id in pre-order (children left to
   right). Every Lfunction becomes its own function record. One owner per node
   (DECISIONS.md D1.3): the enclosing function holds the Lfunction node
   ("stub", "func": nested fid), whose body position points into the nested
   record ("child" + "func"). The nested record repeats the node as its id 0
   ("root", "owner": parent fid) so its body has a parent there; consumers skip
   nodes whose owner is another record. Top-level code is "module_init". *)

open Lambda
module E = Entities
module J = Json_out

type def =
  | No_def
  | Let_def of int           (* head node of a let-bound definition *)
  | Mut_defs of Ident.t      (* resolved at output: all Lmutlet/Lassign of x *)

type operand =
  | Leaf of string * def
  | Child of int              (* node in the same record *)
  | Xchild of string * int    (* node [id] in record [fid] (stub body) *)

type role = Value | Control

type node = {
  id : int;
  op : string;
  ty : E.lty option;
  positions : (role * operand) list;
  stub_of : string option;   (* fid of the nested function, for stubs *)
  owner : string option;     (* roots: the record that owns this node *)
  callee_of : int option;    (* head of an Lapply callee (non-position) *)
}

type fkind = Named | Anonymous | Module_init

type func = {
  fid : string;
  name : string;
  kind : fkind;
  ident : Ident.t option;
  loc : scoped_location option;
  params : (Ident.t * value_kind) list;
  self : Ident.t option;                 (* letrec identifier, for CALL_SELF *)
  mutable next_id : int;
  nodes : (int, node) Hashtbl.t;
  cases : (int, operand list) Hashtbl.t;
  counts : (string, int) Hashtbl.t;
  let_defs : int Ident.Tbl.t;
  mut_defs : int list Ident.Tbl.t;       (* reversed *)
}

type state = {
  self_module : Ident.t;
  mutable funcs : func list;             (* reversed discovery order *)
  mutable n_anon : int;
  kinds : value_kind Ident.Tbl.t;        (* binding kinds, unit-wide *)
  local_funs : unit Ident.Tbl.t;         (* idents let/letrec-bound to a function *)
  by_fid : (string, func) Hashtbl.t;
}

let stamp = Util.stamp

let new_func st ~fid ~name ~kind ?ident ?loc ?self ~params () =
  let f = { fid; name; kind; ident; loc; params; self; next_id = 0;
            nodes = Hashtbl.create 32; cases = Hashtbl.create 4;
            counts = Hashtbl.create 8; let_defs = Ident.Tbl.create 8;
            mut_defs = Ident.Tbl.create 4 } in
  st.funcs <- f :: st.funcs;
  Hashtbl.replace st.by_fid fid f;
  f

let fresh f = let id = f.next_id in f.next_id <- id + 1; id

let count f k = Util.bump f.counts k

let add_mut_def f x id =
  let prev = Option.value ~default:[] (Ident.Tbl.find_opt f.mut_defs x) in
  Ident.Tbl.replace f.mut_defs x (id :: prev)

(* Left-to-right map: node ids must follow source order. *)
let rec map_lr g = function
  | [] -> []
  | x :: xs -> let y = g x in y :: map_lr g xs

let node_type l =
  match Lambda_ent.node_type l with
  | Fixed t | Instance t -> Some t
  | NoType -> None

(* Callee kind, schema §1.7. *)
let rec root_global = function
  | Lprim (Pfield _, [e], _) -> root_global e
  | Lprim (Pgetglobal id, [], _) -> Some id
  | Levent (e, _) | Lifused (_, e) -> root_global e
  | _ -> None

let rec callee_kind st f = function
  | Levent (e, _) | Lifused (_, e) -> callee_kind st f e
  | Lvar x when (match f.self with Some s -> Ident.same s x | None -> false) ->
      E.call_self
  | Lvar x when Ident.Tbl.mem st.local_funs x -> E.call_local
  | e ->
      match root_global e with
      | None -> E.call_dynamic
      | Some id ->
          match Lambda_ent.global_class ~self:st.self_module id with
          | Self -> E.call_local
          | Stdlib -> E.call_stdlib
          | Other -> E.call_module

let rec walk st f ~tail ?binder l : operand =
  match l with
  | Lvar x ->
      let kind =
        match Ident.Tbl.find_opt st.kinds x with
        | Some k -> Lambda_ent.var_kind k
        | None -> E.var_gen
      in
      let def =
        match Ident.Tbl.find_opt f.let_defs x with
        | Some n -> Let_def n
        | None -> No_def
      in
      Leaf (kind, def)
  | Lmutvar x -> Leaf (E.mutvar, Mut_defs x)
  | Lconst c -> Leaf (Lambda_ent.const_kind c, No_def)
  | Levent (e, _) | Lifused (_, e) -> walk st f ~tail ?binder e
  | _ -> Child (node st f ~tail ?binder l)

and node st f ~tail ?binder l : int =
  let id = fresh f in
  let op = Lambda_ent.node_opcode ~self:st.self_module l in
  let value e = (Value, walk st f ~tail:false e) in
  let control ~tail e = (Control, walk st f ~tail e) in
  let stub_of = ref None in
  let positions =
    match l with
    | Lapply ap ->
        count f (callee_kind st f ap.ap_func);
        count f (if tail then E.tail else E.nontail);
        (* The callee is walked and its nodes belong to this function, but it
           is not a position: no Arg/Child triple comes from the Lapply. Its
           head is tagged [callee_of] so the choice can be ablated (D1.4). *)
        (match walk st f ~tail:false ap.ap_func with
         | Child n ->
             let h = Hashtbl.find f.nodes n in
             Hashtbl.replace f.nodes n { h with callee_of = Some id }
         | Leaf _ | Xchild _ -> ());
        map_lr value ap.ap_args
    | Lfunction lf ->
        let fid, body = new_function st ~parent:f.fid ?binder lf in
        stub_of := Some fid;
        [ (Control,
           match body with
           | Child n -> Xchild (fid, n)
           | Leaf (k, _) -> Leaf (k, No_def)
           | Xchild _ -> assert false) ]
    | Llet (_, k, x, def, body) ->
        let d = (Value, walk st f ~tail:false ~binder:(x, false) def) in
        Ident.Tbl.replace st.kinds x k;
        (match d with
         | _, Child n -> Ident.Tbl.replace f.let_defs x n
         | _, (Leaf _ | Xchild _) -> ());
        let b = control ~tail body in
        [d; b]
    | Lmutlet (k, x, def, body) ->
        add_mut_def f x id;
        let d = value def in
        Ident.Tbl.replace st.kinds x k;
        let b = control ~tail body in
        [d; b]
    | Lletrec (bindings, body) ->
        List.iter (fun (b : rec_binding) -> Ident.Tbl.replace st.local_funs b.id ()) bindings;
        let defs =
          map_lr
            (fun (b : rec_binding) ->
               (Value, Child (node st f ~tail:false ~binder:(b.id, true)
                                (Lfunction b.def))))
            bindings
        in
        defs @ [control ~tail body]
    | Lprim (p, args, _) ->
        List.iter (count f) (Lambda_ent.prim_counts p);
        map_lr value args
    | Lswitch (scrut, sw, _) ->
        let s = value scrut in
        let arms =
          map_lr (fun (_, e) -> walk st f ~tail e) sw.sw_consts
          @ map_lr (fun (_, e) -> walk st f ~tail e) sw.sw_blocks
          @ map_lr (walk st f ~tail) (Option.to_list sw.sw_failaction)
        in
        Hashtbl.replace f.cases id arms;
        count f (E.arms (List.length arms));
        [s]
    | Lstringswitch (scrut, cases, default, _) ->
        let s = value scrut in
        let arms =
          map_lr (fun (_, e) -> walk st f ~tail e) cases
          @ map_lr (walk st f ~tail) (Option.to_list default)
        in
        Hashtbl.replace f.cases id arms;
        count f (E.arms (List.length arms));
        [s]
    | Lstaticraise (_, args) -> map_lr value args
    | Lstaticcatch (body, (_, params), handler) ->
        let b = control ~tail body in
        List.iter (fun (x, k) -> Ident.Tbl.replace st.kinds x k) params;
        let h = control ~tail handler in
        [b; h]
    | Ltrywith (body, _, handler) ->
        let b = control ~tail:false body in
        let h = control ~tail handler in
        [b; h]
    | Lifthenelse (c, t, e) ->
        let c = value c in
        let t = control ~tail t in
        let e = control ~tail e in
        [c; t; e]
    | Lsequence (a, b) ->
        let a = control ~tail:false a in
        let b = control ~tail b in
        [a; b]
    | Lwhile (c, b) ->
        let c = value c in
        let b = control ~tail:false b in
        [c; b]
    | Lfor (x, lo, hi, _, body) ->
        let lo = value lo in
        let hi = value hi in
        (* The IR carries no value_kind for the index, but the language
           guarantees an int (D1.14). *)
        Ident.Tbl.replace st.kinds x Pintval;
        let b = control ~tail:false body in
        [lo; hi; b]
    | Lassign (x, e) ->
        add_mut_def f x id;
        [value e]
    | Lsend (_, met, obj, args, _) ->
        (* schema order: obj, method, args *)
        let o = value obj in
        let m = value met in
        o :: m :: map_lr value args
    | Lvar _ | Lmutvar _ | Lconst _ | Levent _ | Lifused _ ->
        invalid_arg "Lambda_abs.node: leaf or transparent node"
  in
  Hashtbl.replace f.nodes id
    { id; op; ty = node_type l; positions; stub_of = !stub_of; owner = None;
      callee_of = None };
  id

(* A new function record; returns its fid and the operand of its body.
   [binder] is the identifier of a directly enclosing Llet (false) /
   Lletrec (true) binding; [parent] owns the Lfunction node. *)
and new_function st ~parent ?binder lf =
  let params = lf.params in
  List.iter (fun (x, k) -> Ident.Tbl.replace st.kinds x k) params;
  let f =
    match binder with
    | Some (x, is_rec) ->
        Ident.Tbl.replace st.local_funs x ();
        new_func st ~fid:(Util.ident_key x)
          ~name:(Ident.name x) ~kind:Named ~ident:x ~loc:lf.loc
          ?self:(if is_rec then Some x else None) ~params ()
    | None ->
        let n = st.n_anon in
        st.n_anon <- n + 1;
        new_func st ~fid:(Printf.sprintf "anon/%d" n) ~name:"" ~kind:Anonymous
          ~loc:lf.loc ~params ()
  in
  let l = Lfunction lf in
  count f (E.arity_feature (List.length params));
  count f (E.return_feature (Lambda_ent.ty_of_value_kind lf.return));
  let id = fresh f in
  let body = walk st f ~tail:true lf.body in
  Hashtbl.replace f.nodes id
    { id; op = Lambda_ent.node_opcode ~self:st.self_module l; ty = node_type l;
      positions = [(Control, body)]; stub_of = None; owner = Some parent;
      callee_of = None };
  (f.fid, body)

(* ---- JSON output ---- *)

let json_loc : scoped_location option -> J.t = function
  | None -> J.Null
  | Some l -> Util.json_location (Debuginfo.Scoped_location.to_location l)

(* "kind" on a child: the operand kind it stands for at inference. *)
let child_kind (g : func) n = E.computed_operand_kind (Hashtbl.find g.nodes n).ty

let json_operand st f = function
  | Child n -> [ "child", J.Int n; "kind", J.String (child_kind f n) ]
  | Xchild (fid, n) ->
      [ "child", J.Int n; "func", J.String fid;
        "kind", J.String (child_kind (Hashtbl.find st.by_fid fid) n) ]
  | Leaf (kind, def) ->
      let def =
        match def with
        | No_def -> J.Null
        | Let_def n -> J.List [J.Int n]
        | Mut_defs x ->
            (match Ident.Tbl.find_opt f.mut_defs x with
             | None | Some [] -> J.Null
             | Some ids -> J.List (List.map (fun i -> J.Int i) (List.sort compare ids)))
      in
      [ "leaf", J.String kind; "def", def ]

let json_node st f n =
  let positions =
    List.mapi
      (fun i (role, o) ->
         J.Obj ([ "i", J.Int i;
                  "role", J.String (match role with Value -> "value" | Control -> "control") ]
                @ json_operand st f o))
      n.positions
  in
  J.Obj ([ "id", J.Int n.id; "op", J.String n.op;
           "type", (match n.ty with Some t -> J.String (E.lty_name t) | None -> J.Null);
           "positions", J.List positions ]
         @ (match n.stub_of with Some fid -> [ "func", J.String fid ] | None -> [])
         @ (match n.owner with Some o -> [ "owner", J.String o ] | None -> [])
         @ (match n.callee_of with Some a -> [ "callee_of", J.Int a ] | None -> []))

let json_func st f =
  let sorted_keys tbl = List.sort compare (Hashtbl.fold (fun k _ acc -> k :: acc) tbl []) in
  let nodes = List.map (fun id -> json_node st f (Hashtbl.find f.nodes id)) (sorted_keys f.nodes) in
  let cases =
    List.map
      (fun id ->
         (string_of_int id,
          J.List (List.map (fun o ->
              match o with
              | Child n -> J.Obj [ "child", J.Int n; "kind", J.String (child_kind f n) ]
              | Leaf (k, _) -> J.Obj [ "leaf", J.String k ]
              | Xchild _ -> assert false)
              (Hashtbl.find f.cases id))))
      (sorted_keys f.cases)
  in
  J.Obj
    [ "fid", J.String f.fid;
      "name", J.String f.name;
      "kind", J.String (match f.kind with
          | Named -> "named" | Anonymous -> "anonymous" | Module_init -> "module_init");
      "stamp", (match f.ident with Some x -> J.Int (stamp x) | None -> J.Null);
      "loc", json_loc f.loc;
      "params", J.List (List.map (fun (x, k) ->
          J.Obj [ "name", J.String (Ident.name x); "stamp", J.Int (stamp x);
                  "type", J.String (E.lty_name (Lambda_ent.ty_of_value_kind k)) ])
          f.params);
      "nodes", J.List nodes;
      "cases", J.Obj cases;
      "counts", Util.sorted_counts f.counts ]

let extract (h : Dump.header) (p : Lambda.program) : J.t =
  let st = { self_module = p.module_ident; funcs = []; n_anon = 0;
             kinds = Ident.Tbl.create 64; local_funs = Ident.Tbl.create 16;
             by_fid = Hashtbl.create 16 } in
  let init = new_func st ~fid:"module_init" ~name:h.unit_name ~kind:Module_init
      ~params:[] () in
  ignore (walk st init ~tail:true p.code : operand);
  J.Obj
    [ "unit", J.String h.unit_name;
      "source", J.String h.source;
      "digest", J.String h.digest;
      "ocaml", J.String h.ocaml;
      "functions", J.List (List.rev_map (json_func st) st.funcs) ]
