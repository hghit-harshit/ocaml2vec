(* Phase 0 check: unmarshal a .lambda.bin / .cmm.bin dump and print
   per-constructor counts, one "<level> <constructor> <count>" line each,
   sorted. Lprim nodes are counted under their primitive's name. *)

let counts : (string, int) Hashtbl.t = Hashtbl.create 64

let bump k =
  Hashtbl.replace counts k (1 + Option.value ~default:0 (Hashtbl.find_opt counts k))

let lambda_ctor : Lambda.lambda -> string = function
  | Lvar _ -> "Lvar" | Lmutvar _ -> "Lmutvar" | Lconst _ -> "Lconst"
  | Lapply _ -> "Lapply" | Lfunction _ -> "Lfunction" | Llet _ -> "Llet"
  | Lmutlet _ -> "Lmutlet" | Lletrec _ -> "Lletrec"
  | Lprim (p, _, _) -> Printlambda.name_of_primitive p
  | Lswitch _ -> "Lswitch" | Lstringswitch _ -> "Lstringswitch"
  | Lstaticraise _ -> "Lstaticraise" | Lstaticcatch _ -> "Lstaticcatch"
  | Ltrywith _ -> "Ltrywith" | Lifthenelse _ -> "Lifthenelse"
  | Lsequence _ -> "Lsequence" | Lwhile _ -> "Lwhile" | Lfor _ -> "Lfor"
  | Lassign _ -> "Lassign" | Lsend _ -> "Lsend" | Levent _ -> "Levent"
  | Lifused _ -> "Lifused"

let rec count_lambda l =
  bump ("lambda " ^ lambda_ctor l);
  Lambda.iter_head_constructor count_lambda l

let cmm_op : Cmm.operation -> string = function
  | Capply _ -> "Capply" | Cextcall _ -> "Cextcall" | Cload _ -> "Cload"
  | Calloc -> "Calloc" | Cstore _ -> "Cstore" | Caddi -> "Caddi"
  | Csubi -> "Csubi" | Cmuli -> "Cmuli" | Cmulhi -> "Cmulhi" | Cdivi -> "Cdivi"
  | Cmodi -> "Cmodi" | Cand -> "Cand" | Cor -> "Cor" | Cxor -> "Cxor"
  | Clsl -> "Clsl" | Clsr -> "Clsr" | Casr -> "Casr" | Ccmpi _ -> "Ccmpi"
  | Caddv -> "Caddv" | Cadda -> "Cadda" | Ccmpa _ -> "Ccmpa" | Cnegf -> "Cnegf"
  | Cabsf -> "Cabsf" | Caddf -> "Caddf" | Csubf -> "Csubf" | Cmulf -> "Cmulf"
  | Cdivf -> "Cdivf" | Cfloatofint -> "Cfloatofint"
  | Cintoffloat -> "Cintoffloat" | Ccmpf _ -> "Ccmpf" | Craise _ -> "Craise"
  | Ccheckbound -> "Ccheckbound" | Copaque -> "Copaque" | Cdls_get -> "Cdls_get"
  | Cpoll -> "Cpoll"

let cmm_ctor : Cmm.expression -> string = function
  | Cconst_int _ -> "Cconst_int" | Cconst_natint _ -> "Cconst_natint"
  | Cconst_float _ -> "Cconst_float" | Cconst_symbol _ -> "Cconst_symbol"
  | Cvar _ -> "Cvar" | Cvar_mut _ -> "Cvar_mut" | Clet _ -> "Clet"
  | Clet_mut _ -> "Clet_mut" | Cphantom_let _ -> "Cphantom_let"
  | Cassign _ -> "Cassign" | Ctuple _ -> "Ctuple"
  | Cop (op, _, _) -> "Cop:" ^ cmm_op op
  | Csequence _ -> "Csequence" | Cifthenelse _ -> "Cifthenelse"
  | Cswitch _ -> "Cswitch" | Ccatch _ -> "Ccatch" | Cexit _ -> "Cexit"
  | Ctrywith _ -> "Ctrywith" | Creturn_addr -> "Creturn_addr"

(* Own traversal, independent of Cmm_lower's (this tool cross-checks it);
   not Cmm.map_shallow, which skips Cswitch scrutinees in 5.5.1. *)
let cmm_children : Cmm.expression -> Cmm.expression list = function
  | Cconst_int _ | Cconst_natint _ | Cconst_float _ | Cconst_symbol _ | Cvar _
  | Cvar_mut _ | Creturn_addr -> []
  | Clet (_, a, b) | Clet_mut (_, _, a, b) | Csequence (a, b) -> [a; b]
  | Cphantom_let (_, _, a) | Cassign (_, a) -> [a]
  | Ctuple es | Cop (_, es, _) | Cexit (_, es) -> es
  | Cifthenelse (c, _, t, _, f, _) -> [c; t; f]
  | Cswitch (e, _, cases, _) -> e :: Array.to_list (Array.map fst cases)
  | Ccatch (_, handlers, body) -> body :: List.map (fun (_, _, h, _) -> h) handlers
  | Ctrywith (a, _, b, _) -> [a; b]

let rec count_cmm e =
  bump ("cmm " ^ cmm_ctor e);
  List.iter count_cmm (cmm_children e)

let count_phrase : Cmm.phrase -> unit = function
  | Cfunction fd -> bump "cmm Cfunction"; count_cmm fd.fun_body
  | Cdata _ -> bump "cmm Cdata"

let () =
  let files = List.tl (Array.to_list Sys.argv) in
  if files = [] then (prerr_endline "usage: dump_counts <dump.bin>..."; exit 2);
  List.iter
    (fun f ->
       if Filename.check_suffix f ".lambda.bin" then
         count_lambda (snd (Ir2vec.Dump.read_lambda ~legacy_format_1:true f)).code
       else if Filename.check_suffix f ".cmm.bin" then
         List.iter count_phrase (snd (Ir2vec.Dump.read_cmm ~legacy_format_1:true f))
       else (prerr_endline ("not a dump: " ^ f); exit 2))
    files;
  Hashtbl.fold (fun k v acc -> (k, v) :: acc) counts []
  |> List.sort compare
  |> List.iter (fun (k, v) -> Printf.printf "%s %d\n" k v)
