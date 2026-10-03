let rec read_lines acc =
  match In_channel.input_line stdin with
  | Some l -> read_lines (l :: acc)
  | None -> List.rev acc

let () =
  let tbl = Wordcount.count (read_lines []) in
  let s = Wordcount.stats tbl in
  Printf.printf "%d words, %d distinct, mean length %.2f\n" s.words s.distinct s.mean_length;
  List.iter (fun (w, n) -> Printf.printf "%6d %s\n" n w) (Wordcount.top 10 tbl)
