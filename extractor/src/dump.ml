(* Reader for the dumps written by the ir2vec compiler hooks
   (compiler-patch/ir2vec-hooks.patch): a text header of key=value lines
   ended by an empty line, followed by a Marshal'ed IR value. *)

type header = {
  format : int;
  hooks : int option;         (* format >= 2 *)
  build : string option;      (* format >= 2: MD5 of the compiler executable *)
  kind : string;              (* "lambda" | "cmm" *)
  ocaml : string;
  unit_name : string;
  source : string;
  digest : string;
}

exception Bad_dump of string * string  (* path, reason *)

let supported_format = 2
let expected_hooks = 3

(* The build a dump must come from: the ocamlopt this extractor was built with
   (generated into Build_id at build time, D5.13). *)
let expected_build = lazy Build_id.ocamlopt_md5

let read_header path ic =
  let bad reason = raise (Bad_dump (path, reason)) in
  if input_line ic <> "IR2VEC-DUMP" then bad "missing IR2VEC-DUMP magic";
  let rec fields acc =
    match input_line ic with
    | "" -> acc
    | line ->
        (match String.index_opt line '=' with
         | None -> bad ("malformed header line: " ^ line)
         | Some i ->
             let k = String.sub line 0 i in
             let v = String.sub line (i + 1) (String.length line - i - 1) in
             fields ((k, v) :: acc))
  in
  let kv = fields [] in
  let get k =
    match List.assoc_opt k kv with Some v -> v | None -> bad ("no field " ^ k)
  in
  let int k =
    match int_of_string_opt (get k) with Some n -> n | None -> bad ("non-integer " ^ k)
  in
  let format = int "format" in
  { format;
    hooks = (if format >= 2 then Some (int "hooks") else None);
    build = (if format >= 2 then Some (get "build") else None);
    kind = get "kind"; ocaml = get "ocaml"; unit_name = get "unit";
    source = Scanf.unescaped (get "source"); digest = get "digest" }

(* Unmarshalling is only type-safe with the exact compiler that marshalled,
   so format, hook revision, build, version and kind are all checked before
   [Marshal.from_channel]. [legacy_format_1] admits format-1 dumps (no build
   field), which predate D5.13; it is only for re-extracting that corpus. *)
let read (type a) ?(legacy_format_1 = false) ~kind path : header * a =
  let ic = open_in_bin path in
  Fun.protect ~finally:(fun () -> close_in ic) @@ fun () ->
  let h = read_header path ic in
  let bad reason = raise (Bad_dump (path, reason)) in
  (match h.format, h.hooks, h.build with
   | 1, _, _ when legacy_format_1 -> ()
   | 1, _, _ -> bad "format 1 (no build field): pass --legacy-format-1 to read it"
   | f, Some hk, Some b when f = supported_format ->
       if hk <> expected_hooks then
         bad (Printf.sprintf "hooks revision %d, expected %d" hk expected_hooks);
       if b <> Lazy.force expected_build then
         bad (Printf.sprintf "dumped by compiler build %s, but this extractor \
                              was built with %s" b (Lazy.force expected_build))
   | f, _, _ -> bad (Printf.sprintf "format %d, expected %d" f supported_format));
  if h.ocaml <> Config.version then
    bad (Printf.sprintf "dumped by OCaml %s, reader is %s" h.ocaml Config.version);
  if h.kind <> kind then bad (Printf.sprintf "kind %s, expected %s" h.kind kind);
  (h, (Marshal.from_channel ic : a))

let read_lambda ?legacy_format_1 path : header * Lambda.program =
  read ?legacy_format_1 ~kind:"lambda" path

let read_cmm ?legacy_format_1 path : header * Cmm.phrase list =
  read ?legacy_format_1 ~kind:"cmm" path
