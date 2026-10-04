(* ir2vec-extract: IR dumps -> abstracted JSON.

   ir2vec-extract lambda <Unit.<md5>.lambda.bin> [-o out.json]
   ir2vec-extract cmm <Unit.<md5>.cmm.bin> [-o out.json]
   ir2vec-extract cmm-tree <Unit.<md5>.cmm.bin> [-o out.txt]  (Cmm as dumped, text)
   ir2vec-extract cmm-tac <Unit.<md5>.cmm.bin> [-o out.txt]   (lowered TAC, text)
   ir2vec-extract entities [-o out.json]   (inventory from the installed .mli)
   --legacy-format-1 admits dumps written before the build field (D5.13). *)

let usage () =
  prerr_endline
    "usage: ir2vec-extract lambda <dump.lambda.bin> [-o out.json]\n\
    \       ir2vec-extract cmm <dump.cmm.bin> [-o out.json]\n\
    \       ir2vec-extract cmm-tree <dump.cmm.bin> [-o out.txt]\n\
    \       ir2vec-extract cmm-tac <dump.cmm.bin> [-o out.txt]\n\
    \       ir2vec-extract entities [-o out.json]";
  exit 2

let output out json =
  match out with
  | None -> print_string (Ir2vec.Json_out.to_string json)
  | Some path -> Ir2vec.Json_out.to_file path json

let output_text out s =
  match out with
  | None -> print_string s
  | Some path -> Out_channel.with_open_bin path (fun oc -> output_string oc s)

let () =
  let args = List.tl (Array.to_list Sys.argv) in
  let rec split_out acc = function
    | "-o" :: path :: rest -> (List.rev_append acc rest, Some path)
    | x :: rest -> split_out (x :: acc) rest
    | [] -> (List.rev acc, None)
  in
  let args, out = split_out [] args in
  let legacy_format_1 = List.mem "--legacy-format-1" args in
  let args = List.filter (fun a -> a <> "--legacy-format-1") args in
  try
    match args with
    | [ "lambda"; dump ] ->
        let h, p = Ir2vec.Dump.read_lambda ~legacy_format_1 dump in
        output out (Ir2vec.Lambda_abs.extract h p)
    | [ "cmm"; dump ] ->
        let h, p = Ir2vec.Dump.read_cmm ~legacy_format_1 dump in
        output out (Ir2vec.Cmm_abs.extract h p)
    | [ "cmm-tree"; dump ] ->
        let h, p = Ir2vec.Dump.read_cmm ~legacy_format_1 dump in
        output_text out (Ir2vec.Cmm_text.tree h p)
    | [ "cmm-tac"; dump ] ->
        let h, p = Ir2vec.Dump.read_cmm ~legacy_format_1 dump in
        output_text out (Ir2vec.Cmm_text.tac h p)
    | [ "entities" ] ->
        output out (Ir2vec.Inventory.to_json (Ir2vec.Inventory.read_ctors ()))
    | _ -> usage ()
  with Ir2vec.Dump.Bad_dump (path, reason) ->
    Printf.eprintf "ir2vec-extract: %s: %s\n" path reason;
    exit 1
