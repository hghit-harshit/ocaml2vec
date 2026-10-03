(* Helpers shared by the Lambda and Cmm extractors. *)

module J = Json_out

(* Ident stamps: 5.5.1 exposes no accessor, but [Ident.unique_name] is
   [name ^ "_" ^ stamp] (D1.6). *)
let stamp id =
  let u = Ident.unique_name id in
  let i = String.rindex u '_' in
  int_of_string (String.sub u (i + 1) (String.length u - i - 1))

(* "name/stamp", the naming used for fids and Cmm variables alike. *)
let ident_key id = Printf.sprintf "%s/%d" (Ident.name id) (stamp id)

let json_location (loc : Location.t) : J.t =
  if loc = Location.none then J.Null
  else
    let s = loc.loc_start and e = loc.loc_end in
    J.Obj [ "file", J.String s.pos_fname;
            "l1", J.Int s.pos_lnum; "c1", J.Int (s.pos_cnum - s.pos_bol);
            "l2", J.Int e.pos_lnum; "c2", J.Int (e.pos_cnum - e.pos_bol) ]

let sorted_counts (tbl : (string, int) Hashtbl.t) : J.t =
  J.Obj (List.map (fun k -> (k, J.Int (Hashtbl.find tbl k)))
           (List.sort compare (Hashtbl.fold (fun k _ acc -> k :: acc) tbl [])))

let bump tbl k =
  Hashtbl.replace tbl k (1 + Option.value ~default:0 (Hashtbl.find_opt tbl k))
