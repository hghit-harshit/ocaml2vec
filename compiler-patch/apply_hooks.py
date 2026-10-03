"""Apply the ir2vec hooks to a pristine OCaml 5.5.1 source tree.

Used only to regenerate ir2vec-hooks.patch (the patch is the artifact that
make_switch.sh applies). Usage: python3 apply_hooks.py <ocaml-src-dir>
"""
import pathlib
import sys

root = pathlib.Path(sys.argv[1])


def edit(rel: str, old: str, new: str) -> None:
    p = root / rel
    s = p.read_text()
    assert s.count(old) == 1, (rel, old)
    p.write_text(s.replace(old, new))


HELPER = r'''(* ir2vec: dump IR values for offline analysis. A no-op unless
   IR2VEC_DUMP_DIR is set to a non-empty path; never affects code generation.
   File: $IR2VEC_DUMP_DIR/<unit>.<source-md5>.<kind>.bin =
   a text header (key=value lines, ended by an empty line), then Marshal.
   The header names the hook revision and the MD5 of the compiler executable
   that wrote the dump, so a reader can reject dumps from any other build. *)
let ir2vec_format_version = 2
let ir2vec_hooks_revision = 3
let ir2vec_build = lazy (Digest.to_hex (Digest.file Sys.executable_name))

let rec ir2vec_mkdir_p dir =
  if not (Sys.file_exists dir) then begin
    ir2vec_mkdir_p (Filename.dirname dir);
    try Sys.mkdir dir 0o755 with Sys_error _ when Sys.is_directory dir -> ()
  end

let ir2vec_dump ~kind (v : 'a) =
  match Sys.getenv_opt "IR2VEC_DUMP_DIR" with
  | None | Some "" -> ()
  | Some _ when !Clflags.make_package ->
      (* A -pack unit is synthesized from its members: no source, no dump. *)
      Printf.eprintf "ir2vec: %s: -pack unit, not dumped\n%!"
        (Compilenv.current_unit_name ())
  | Some dir ->
      let unit_name = Compilenv.current_unit_name () in
      let source = !Location.input_name in
      let digest = Digest.to_hex (Digest.file source) in
      let base = String.concat "." [unit_name; digest; kind; "bin"] in
      ir2vec_mkdir_p dir;
      let tmp = Filename.temp_file ~temp_dir:dir base ".tmp" in
      let oc = open_out_bin tmp in
      Misc.try_finally
        ~always:(fun () -> close_out oc)
        ~exceptionally:(fun () -> Misc.remove_file tmp)
        (fun () ->
           Printf.fprintf oc
             "IR2VEC-DUMP\nformat=%d\nhooks=%d\nbuild=%s\nkind=%s\nocaml=%s\n\
              unit=%s\nsource=%s\ndigest=%s\n\n"
             ir2vec_format_version ir2vec_hooks_revision
             (Lazy.force ir2vec_build) kind Config.version unit_name
             (String.escaped source) digest;
           Marshal.to_channel oc v []);
      Sys.rename tmp (Filename.concat dir base)

let ir2vec_dump_lambda (p : Lambda.program) = ir2vec_dump ~kind:"lambda" p

let ir2vec_dump_cmm (ps : Cmm.phrase list) = ir2vec_dump ~kind:"cmm" ps

'''

edit("asmcomp/asmgen.ml",
     "type error =\n  | Assembler_error of string",
     HELPER + "type error =\n  | Assembler_error of string")

edit("asmcomp/asmgen.ml",
     '  ++ Profile.record "cmm" Cmmgen.compunit\n',
     '  ++ Profile.record "cmm" Cmmgen.compunit\n'
     '  ++ (fun ps -> if Option.is_none toplevel then ir2vec_dump_cmm ps; ps)\n')

edit("asmcomp/asmgen.mli",
     "val compile_implementation_linear :",
     "(** ir2vec: marshal the simplified Lambda program to $IR2VEC_DUMP_DIR.\n"
     "    No-op when the variable is unset or empty. *)\n"
     "val ir2vec_dump_lambda : Lambda.program -> unit\n\n"
     "val compile_implementation_linear :")

edit("driver/optcompile.ml",
     "       { program with Lambda.code }\n       |> print_if",
     "       { program with Lambda.code }\n"
     "       |> (fun p -> Asmgen.ir2vec_dump_lambda p; p)\n"
     "       |> print_if")
print("ok")
