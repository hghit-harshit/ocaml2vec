let rec fact n = if n <= 1 then 1 else n * fact (n - 1)
let twice f x = f (f x)
let use g = twice g 3
let succs = List.map (fun x -> x + 1) [1; 2; 3]
