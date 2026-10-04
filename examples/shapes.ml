(* A longer example for show_cmm.sh: each section exercises different Cmm. *)

(* Variants + float arithmetic: boxed floats, Caddf/Cmulf, Cswitch on tags *)
type shape =
  | Circle of float
  | Rect of float * float
  | Square of float

let area = function
  | Circle r -> 3.14159 *. r *. r
  | Rect (w, h) -> w *. h
  | Square s -> s *. s

(* Lists + closures: a fold with an anonymous function *)
let total_area shapes =
  List.fold_left (fun acc s -> acc +. area s) 0.0 shapes

(* Float comparison: Ccmpf *)
let biggest shapes =
  let rec go best = function
    | [] -> best
    | s :: rest -> if area s > area best then go s rest else go best rest
  in
  match shapes with
  | [] -> None
  | s :: rest -> Some (go s rest)

(* Records with a mutable field: Cload / Cstore *)
type counter = { name : string; mutable count : int }

let bump c = c.count <- c.count + 1

(* Arrays + loops: bounds checks (Ccheckbound), loads and stores *)
let bubble_sort (a : int array) =
  let n = Array.length a in
  for i = 0 to n - 2 do
    for j = 0 to n - 2 - i do
      if a.(j) > a.(j + 1) then begin
        let t = a.(j) in
        a.(j) <- a.(j + 1);
        a.(j + 1) <- t
      end
    done
  done

(* Exceptions: Craise and Ctrywith *)
exception Not_positive of int

let checked_sqrt x =
  if x < 0 then raise (Not_positive x) else sqrt (float_of_int x)

let safe_sqrt x =
  try checked_sqrt x with Not_positive _ -> 0.0

(* Strings: external calls into the runtime (Cextcall) *)
let describe s =
  match s with
  | Circle _ -> "circle of area " ^ string_of_float (area s)
  | Rect _ -> "rectangle of area " ^ string_of_float (area s)
  | Square _ -> "square of area " ^ string_of_float (area s)
