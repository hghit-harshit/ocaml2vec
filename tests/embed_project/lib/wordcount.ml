(* A small library with an opam dependency (re), used by the embed tests. *)

type stats = { words : int; distinct : int; mean_length : float }

let word = Re.compile (Re.rep1 (Re.alt [ Re.alpha; Re.char '\'' ]))

let words line = List.map String.lowercase_ascii (Re.matches word line)

let count lines =
  let tbl = Hashtbl.create 64 in
  List.iter
    (fun line ->
      List.iter
        (fun w ->
          let n = try Hashtbl.find tbl w with Not_found -> 0 in
          Hashtbl.replace tbl w (n + 1))
        (words line))
    lines;
  tbl

let top k tbl =
  let all = Hashtbl.fold (fun w n acc -> (w, n) :: acc) tbl [] in
  let sorted = List.sort (fun (a, x) (b, y) -> if x <> y then compare y x else compare a b) all in
  List.filteri (fun i _ -> i < k) sorted

let stats tbl =
  let words, chars =
    Hashtbl.fold (fun w n (ws, cs) -> (ws + n, cs + (n * String.length w))) tbl (0, 0)
  in
  let mean_length = if words = 0 then 0. else float_of_int chars /. float_of_int words in
  { words; distinct = Hashtbl.length tbl; mean_length }
