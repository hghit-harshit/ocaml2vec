(* Minimal deterministic JSON writer (no external dependency).
   Layout: a list/object is printed on one line if that fits in [width]
   columns, otherwise one element per line. Key order is preserved. *)

type t =
  | Null
  | Bool of bool
  | Int of int
  | String of string
  | List of t list
  | Obj of (string * t) list

let width = 100

let escape s =
  let b = Buffer.create (String.length s + 2) in
  Buffer.add_char b '"';
  String.iter
    (fun c ->
       match c with
       | '"' -> Buffer.add_string b "\\\""
       | '\\' -> Buffer.add_string b "\\\\"
       | '\n' -> Buffer.add_string b "\\n"
       | '\r' -> Buffer.add_string b "\\r"
       | '\t' -> Buffer.add_string b "\\t"
       | c when Char.code c < 0x20 ->
           Buffer.add_string b (Printf.sprintf "\\u%04x" (Char.code c))
       | c -> Buffer.add_char b c)
    s;
  Buffer.add_char b '"';
  Buffer.contents b

let rec compact = function
  | Null -> "null"
  | Bool b -> string_of_bool b
  | Int i -> string_of_int i
  | String s -> escape s
  | List l -> "[" ^ String.concat "," (List.map compact l) ^ "]"
  | Obj kv ->
      "{" ^ String.concat ","
        (List.map (fun (k, v) -> escape k ^ ":" ^ compact v) kv) ^ "}"

(* [col]: column where [v] starts; [indent]: indentation of its line. *)
let rec pp b ~col ~indent v =
  let c = compact v in
  if col + String.length c <= width then Buffer.add_string b c
  else
    let inner = indent + 2 in
    let items open_ close elems print_elem =
      Buffer.add_string b open_;
      List.iteri
        (fun i e ->
           if i > 0 then Buffer.add_string b ",";
           Buffer.add_char b '\n';
           Buffer.add_string b (String.make inner ' ');
           print_elem e)
        elems;
      Buffer.add_char b '\n';
      Buffer.add_string b (String.make indent ' ');
      Buffer.add_string b close
    in
    match v with
    | List l -> items "[" "]" l (pp b ~col:inner ~indent:inner)
    | Obj kv ->
        items "{" "}" kv (fun (k, v) ->
            let key = escape k ^ ": " in
            Buffer.add_string b key;
            pp b ~col:(inner + String.length key) ~indent:inner v)
    | Null | Bool _ | Int _ | String _ -> Buffer.add_string b c

let to_string v =
  let b = Buffer.create 4096 in
  pp b ~col:0 ~indent:0 v;
  Buffer.add_char b '\n';
  Buffer.contents b

let to_file path v =
  let oc = open_out_bin path in
  Fun.protect ~finally:(fun () -> close_out oc) (fun () ->
      output_string oc (to_string v))
