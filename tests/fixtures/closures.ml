let make_adder k = fun x -> x + k

let compose f g = fun x -> f (g x)

let sum_with f l = List.fold_left (fun acc x -> acc + f x) 0 l

let total = sum_with (make_adder 10) [1; 2; 3]
