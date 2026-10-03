(* Cmm -> three-address code + CFG (schema §2.1, BUILD_SPEC Phase 2).

   Every [Cop] becomes exactly one instruction whose operands are atomic
   (variable, temp, constant or symbol). Non-atomic arguments are lowered
   first into fresh temps, RIGHT TO LEFT: this is the native backend's own
   order (Selectgen.emit_parts_list) and the order of schema §2.9; see
   DECISIONS.md D2.2. Operand lists keep source order.

   Lowering is driven by a context:
   - [Tail]: the value is the function result; ends in [RET].
   - [Value]: the value is needed as an atomic operand.
   - [Effect]: the value is discarded.
   A control construct (if / switch / catch / try) in [Value] context merges
   its arms through a join variable: each arm defines it (directly, or by a
   COPY), then JUMPs to a join block. Join variables have one definition per
   arm and are listed in [join_vars]; like mutable variables they are never
   aliased, so reaching definitions sees every arm (D2.3). In [Tail] context
   each arm returns.

   Code after a diverging expression (raise, exit) is not lowered; its Cops
   are counted in [dead_cops] so the one-instruction-per-Cop invariant stays
   checkable. *)

open Cmm
module E = Entities

type operand =
  | Var of string
  | Const of string            (* CONST_INT | CONST_NATINT | CONST_FLOAT *)
  | Sym of string

type instr = {
  iid : int;
  op : string;
  ty : machtype_component option;
  dst : string option;
  args : operand list;
  side_effect : bool;
  terminator : bool;
  synthetic : bool;   (* join COPY / fall-through JUMP added by the lowering *)
  counts : string list;
}

type block = {
  bid : int;
  mutable instrs : instr list;            (* reversed while building *)
  mutable succ : int list;                (* normal successors *)
  mutable exn_succ : int list;            (* innermost Ctrywith handler *)
}

type func = {
  name : string;
  dbg : Debuginfo.t;
  params : (string * machtype_component) list;
  mutable_vars : string list;             (* Clet_mut *)
  join_vars : string list;                (* one definition per arm *)
  handler_params : string list;
  blocks : block list;                    (* in id order *)
  var_types : (string, machtype_component) Hashtbl.t;
  n_cops : int;
  dead_cops : int;
}

type ctx = Tail | Value | Effect
type res = Diverged | Val of operand | Done

type state = {
  mutable blocks : block list;            (* reversed *)
  mutable n_blocks : int;
  mutable cur : block option;             (* None: control has left *)
  mutable n_instrs : int;
  mutable n_tmps : int;
  types : (string, machtype_component) Hashtbl.t;
  aliases : (string, operand) Hashtbl.t;  (* immutable Clet of an atom *)
  mutables : (string, unit) Hashtbl.t;    (* redefinable: mutable + join *)
  mutable mutable_order : string list;    (* reversed *)
  mutable join_order : string list;       (* reversed *)
  mutable handler_params : string list;   (* reversed *)
  mutable traps : int list;               (* Ctrywith handler blocks, innermost first *)
  exits : (int, string list * int) Hashtbl.t;
  mutable n_cops : int;
  mutable dead_cops : int;
}

let var_name vp = Util.ident_key (Backend_var.With_provenance.var vp)

let new_block st =
  let b = { bid = st.n_blocks; instrs = []; succ = []; exn_succ = [] } in
  st.n_blocks <- st.n_blocks + 1;
  st.blocks <- b :: st.blocks;
  b

let tmp st = st.n_tmps <- st.n_tmps + 1; "t" ^ string_of_int st.n_tmps

let set_type st x t = if not (Hashtbl.mem st.types x) then Hashtbl.replace st.types x t

let type_of_var st x = Option.value ~default:Val (Hashtbl.find_opt st.types x)

let operand_type st = function
  | Var x -> type_of_var st x
  | Const k when k = E.c_const_float -> Float
  | Const _ | Sym _ -> Int

let mark_mutable st x =
  if not (Hashtbl.mem st.mutables x) then begin
    Hashtbl.replace st.mutables x ();
    st.mutable_order <- x :: st.mutable_order
  end

let mark_join st x =
  if not (Hashtbl.mem st.mutables x) then begin
    Hashtbl.replace st.mutables x ();
    st.join_order <- x :: st.join_order
  end

(* Immediate sub-expressions. Not [Cmm.map_shallow]: in 5.5.1 it skips the
   scrutinee of [Cswitch] (DECISIONS.md D2.9). *)
let children : expression -> expression list = function
  | Cconst_int _ | Cconst_natint _ | Cconst_float _ | Cconst_symbol _ | Cvar _
  | Cvar_mut _ | Creturn_addr -> []
  | Clet (_, a, b) | Clet_mut (_, _, a, b) | Csequence (a, b) -> [a; b]
  | Cphantom_let (_, _, a) | Cassign (_, a) -> [a]
  | Ctuple es | Cop (_, es, _) | Cexit (_, es) -> es
  | Cifthenelse (c, _, t, _, f, _) -> [c; t; f]
  | Cswitch (e, _, cases, _) -> e :: Array.to_list (Array.map fst cases)
  | Ccatch (_, handlers, body) -> body :: List.map (fun (_, _, h, _) -> h) handlers
  | Ctrywith (a, _, b, _) -> [a; b]

let rec count_cops e =
  List.fold_left (fun n c -> n + count_cops c)
    (match e with Cop _ -> 1 | _ -> 0) (children e)

let dead st e = st.dead_cops <- st.dead_cops + count_cops e

let emit st ?dst ?(succ = []) ?(side_effect = false) ?(terminator = false)
    ?(synthetic = false) ?(counts = []) ~op ~ty args =
  let b =
    match st.cur with
    | Some b -> b
    | None -> invalid_arg "Cmm_lower.emit: unreachable code"
  in
  (match st.traps with
   | h :: _ when not (List.mem h b.exn_succ) -> b.exn_succ <- b.exn_succ @ [h]
   | _ -> ());
  let i = { iid = st.n_instrs; op; ty; dst; args; side_effect; terminator;
            synthetic; counts } in
  st.n_instrs <- st.n_instrs + 1;
  b.instrs <- i :: b.instrs;
  (match dst with Some d -> set_type st d (Option.value ~default:Val ty) | None -> ());
  if terminator then begin b.succ <- succ; st.cur <- None end

let ret st op =
  emit st ~terminator:true ~op:E.ret ~ty:None [op];
  Diverged

let resolve st v =
  let x = Util.ident_key v in
  match Hashtbl.find_opt st.aliases x with Some op -> op | None -> Var x

(* Bind immutable [x] to an already-computed operand: an alias, unless the
   operand is a variable that can be redefined later (mutable or join
   variable), in which case [x] takes a snapshot. *)
let bind st x op =
  match op with
  | Var y when Hashtbl.mem st.mutables y ->
      emit st ~dst:x ~op:E.copy ~ty:(Some (type_of_var st y)) [op]
  | Var _ | Const _ | Sym _ -> Hashtbl.replace st.aliases x op

let rec lower st ctx ?dst e : res =
  let atom op =
    match ctx with Value -> Val op | Effect -> Done | Tail -> ret st op
  in
  match e with
  | Cconst_int _ -> atom (Const E.c_const_int)
  | Cconst_natint _ -> atom (Const E.c_const_natint)
  | Cconst_float _ -> atom (Const E.c_const_float)
  | Cconst_symbol (s, _) -> atom (Sym s)
  | Cvar v | Cvar_mut v -> atom (resolve st v)
  | Clet (vp, def, body) ->
      let x = var_name vp in
      (match def with
       | Cvar v | Cvar_mut v -> bind st x (resolve st v)
       | Cconst_int _ | Cconst_natint _ | Cconst_float _ | Cconst_symbol _ ->
           (match lower st Value def with
            | Val op -> bind st x op
            | Diverged | Done -> assert false)
       | _ ->
           (match lower st Value ~dst:x def with
            | Val (Var y) when y = x -> ()
            | Val op -> bind st x op
            | Diverged | Done -> ()));
      continue st ctx ?dst body
  | Clet_mut (vp, mt, def, body) ->
      let x = var_name vp in
      let t = Option.value ~default:Val (Cmm_ent.single mt) in
      Hashtbl.replace st.types x t;
      mark_mutable st x;
      (match lower st Value def with
       | Val op -> emit st ~dst:x ~op:E.copy ~ty:(Some t) [op]
       | Diverged | Done -> ());
      continue st ctx ?dst body
  | Cphantom_let (_, _, body) -> lower st ctx ?dst body
  | Cassign (v, value) ->
      let x = Util.ident_key v in
      (match lower st Value value with
       | Val op ->
           emit st ~dst:x ~op:E.assign ~ty:(Some (type_of_var st x)) [op];
           (* the value of an assignment is unit, i.e. the constant 1 *)
           atom (Const E.c_const_int)
       | Diverged -> Diverged
       | Done -> assert false)
  | Ctuple [] when ctx = Effect -> Done
  | Ctuple es ->
      (match lower_args st es with
       | None -> Diverged
       | Some ops ->
           let d = match ctx with Effect -> None | Value | Tail -> Some (dest st dst) in
           emit st ?dst:d ~op:E.tuple ~ty:None ops;
           result st ctx d)
  | Creturn_addr ->
      let d = match ctx with Effect -> None | Value | Tail -> Some (dest st dst) in
      (* confirmed on 5.5.1: Selectgen types Creturn_addr as typ_int (D2.14) *)
      emit st ?dst:d ~op:E.return_addr ~ty:(Some Int) [];
      result st ctx d
  | Cop (op, args, _) ->
      (match lower_args st args with
       | None -> st.dead_cops <- st.dead_cops + 1; Diverged
       | Some ops ->
           let ty =
             match Cmm_ent.op_type op with
             | Fixed m -> Some m
             | Result mt -> Cmm_ent.single mt
             | Of_arg0 -> (match ops with a :: _ -> Some (operand_type st a) | [] -> None)
             | NoType -> None
           in
           let name = Cmm_ent.opcode op in
           let side_effect = Cmm_ent.side_effect op in
           let counts = Cmm_ent.op_counts op in
           if Cmm_ent.is_terminator op then begin
             emit st ~side_effect ~terminator:true ~counts ~op:name ~ty ops;
             Diverged
           end else begin
             let d = match ctx with Effect -> None | Value | Tail -> Some (dest st dst) in
             emit st ?dst:d ~side_effect ~counts ~op:name ~ty ops;
             result st ctx d
           end)
  | Csequence (a, b) ->
      (match lower st Effect a with
       | Done -> lower st ctx ?dst b
       | Diverged -> dead st b; Diverged
       | Val _ -> assert false)
  | Cifthenelse (c, _, t, _, f, _) ->
      (match lower st Value c with
       | Val op ->
           let bt = new_block st in
           let bf = new_block st in
           emit st ~terminator:true ~succ:[bt.bid; bf.bid] ~op:E.br ~ty:None [op];
           arms st ctx ?dst [ Some bt, (fun d -> lower st ctx ?dst:d t);
                              Some bf, (fun d -> lower st ctx ?dst:d f) ]
       | Diverged -> dead st t; dead st f; Diverged
       | Done -> assert false)
  | Cswitch (scrut, _, cases, _) ->
      (match lower st Value scrut with
       | Val op ->
           let bs = Array.map (fun _ -> new_block st) cases in
           emit st ~terminator:true ~succ:(Array.to_list (Array.map (fun b -> b.bid) bs))
             ~counts:[E.arms (Array.length cases)] ~op:E.switch ~ty:None [op];
           arms st ctx ?dst
             (Array.to_list
                (Array.mapi (fun i (e, _) -> (Some bs.(i), fun d -> lower st ctx ?dst:d e))
                   cases))
       | Diverged -> Array.iter (fun (e, _) -> dead st e) cases; Diverged
       | Done -> assert false)
  | Ccatch (_, handlers, body) ->
      (* Handler blocks exist before the body so that exits can target them. *)
      let hs =
        List.map
          (fun (n, params, hbody, _) ->
             let b = new_block st in
             let names =
               List.map
                 (fun (vp, mt) ->
                    let x = var_name vp in
                    Hashtbl.replace st.types x (Option.value ~default:Val (Cmm_ent.single mt));
                    st.handler_params <- x :: st.handler_params;
                    x)
                 params
             in
             Hashtbl.replace st.exits n (names, b.bid);
             (Some b, fun d -> lower st ctx ?dst:d hbody))
          handlers
      in
      arms st ctx ?dst ((None, fun d -> lower st ctx ?dst:d body) :: hs)
  | Cexit (n, args) ->
      (match lower_args st args with
       | None -> Diverged
       | Some ops ->
           let params, target = Hashtbl.find st.exits n in
           (* The parameter COPYs are a parallel assignment: an operand naming
              another parameter of this handler is snapshotted first. *)
           let ops =
             List.map2
               (fun p op ->
                  match op with
                  | Var v when v <> p && List.mem v params ->
                      let t = tmp st in
                      emit st ~dst:t ~synthetic:true ~op:E.copy
                        ~ty:(Some (type_of_var st v)) [op];
                      Var t
                  | Var _ | Const _ | Sym _ -> op)
               params ops
           in
           List.iter2
             (fun p op -> emit st ~dst:p ~op:E.copy ~ty:(Some (type_of_var st p)) [op])
             params ops;
           emit st ~terminator:true ~succ:[target] ~op:E.jump ~ty:None ops;
           Diverged)
  | Ctrywith (body, vp, handler, _) ->
      (* v1: every block of the body gets an exceptional edge to the handler
         (recorded in exn_succ as instructions are emitted); the exception
         variable is defined at handler entry, like a parameter. *)
      let h = new_block st in
      let x = var_name vp in
      Hashtbl.replace st.types x Val;
      st.handler_params <- x :: st.handler_params;
      let in_body d =
        st.traps <- h.bid :: st.traps;
        let r = lower st ctx ?dst:d body in
        st.traps <- List.tl st.traps;
        r
      in
      arms st ctx ?dst [ None, in_body; Some h, (fun d -> lower st ctx ?dst:d handler) ]

and continue st ctx ?dst body =
  if st.cur = None then (dead st body; Diverged) else lower st ctx ?dst body

and dest st = function Some x -> x | None -> tmp st

and result st ctx d =
  match ctx, d with
  | Value, Some d -> Val (Var d)
  | Tail, Some d -> ret st (Var d)
  | Effect, _ -> Done
  | (Value | Tail), None -> assert false

(* Right-to-left; returns operands in source order, or None if one diverges. *)
and lower_args st args =
  let rec go acc = function
    | [] -> Some acc
    | e :: rest ->
        match lower st Value e with
        | Val op -> go (op :: acc) rest
        | Diverged -> List.iter (dead st) rest; None
        | Done -> assert false
  in
  go [] (List.rev args)

(* Lower the arms of a control construct and merge them (see header). An arm
   with block [None] continues in the current block. *)
and arms st ctx ?dst (arms : (block option * (string option -> res)) list) =
  let j = match ctx with Value -> Some (dest st dst) | Tail | Effect -> None in
  let join = ref None in
  let goto_join () =
    let jb = match !join with
      | Some b -> b
      | None -> let b = new_block st in join := Some b; b
    in
    emit st ~terminator:true ~synthetic:true ~succ:[jb.bid] ~op:E.jump ~ty:None []
  in
  List.iter
    (fun (blk, run) ->
       (match blk with Some b -> st.cur <- Some b | None -> ());
       match run j, j with
       | Diverged, _ -> ()
       | Done, _ -> goto_join ()
       | Val op, Some j ->
           if op <> Var j then
             emit st ~dst:j ~synthetic:true ~op:E.copy ~ty:(Some (operand_type st op)) [op];
           mark_join st j;
           goto_join ()
       | Val _, None -> assert false)
    arms;
  match !join, j with
  | None, _ -> st.cur <- None; Diverged
  | Some b, Some j -> st.cur <- Some b; Val (Var j)
  | Some b, None -> st.cur <- Some b; Done

let lower_fundecl (fd : fundecl) : func =
  let st = { blocks = []; n_blocks = 0; cur = None; n_instrs = 0; n_tmps = 0;
             types = Hashtbl.create 32; aliases = Hashtbl.create 16;
             mutables = Hashtbl.create 8; mutable_order = []; join_order = [];
             handler_params = [];
             traps = []; exits = Hashtbl.create 8; n_cops = 0; dead_cops = 0 } in
  let params =
    List.map
      (fun (vp, mt) ->
         let x = var_name vp and t = Option.value ~default:Val (Cmm_ent.single mt) in
         Hashtbl.replace st.types x t;
         (x, t))
      fd.fun_args
  in
  (* n_cops counts every Cop in the body independently of the lowering, so
     that "lowered + dead = n_cops" is a real check. *)
  st.n_cops <- count_cops fd.fun_body;
  st.cur <- Some (new_block st);
  ignore (lower st Tail fd.fun_body : res);
  let blocks = List.rev_map (fun b -> { b with instrs = List.rev b.instrs }) st.blocks in
  { name = fd.fun_name; dbg = fd.fun_dbg; params;
    mutable_vars = List.rev st.mutable_order;
    join_vars = List.rev st.join_order;
    handler_params = List.rev st.handler_params;
    blocks; var_types = st.types; n_cops = st.n_cops; dead_cops = st.dead_cops }
