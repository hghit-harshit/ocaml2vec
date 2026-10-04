(* Two implementations of factorial, used to compare their ir2vec embeddings. *)

let rec fact_rec n =
  if n <= 1 then 1 else n * fact_rec (n - 1)

let fact_loop n =
  let acc = ref 1 in
  for i = 2 to n do
    acc := !acc * i
  done;
  !acc
