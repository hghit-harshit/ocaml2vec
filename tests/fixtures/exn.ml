exception Not_positive of int

let check n = if n <= 0 then raise (Not_positive n) else n

let safe_div a b = try a / b with Division_by_zero -> 0

let classify n =
  match check n with
  | v -> v * 2
  | exception Not_positive m -> -m
