let count n =
  let r = ref 0 in
  for i = 1 to n do
    r := !r + i
  done;
  !r
