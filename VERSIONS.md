# Versions

| Component | Version | Notes |
|---|---|---|
| OCaml (pinned) | **5.5.1** | Latest stable `ocaml-base-compiler` in opam-repository on 2026-09-23. Source: tag `5.5.1`, commit `46e1c32`. Non-flambda. |
| opam switch | `ir2vec` | `ocaml-variants.5.5.1+ir2vec`, pinned (`--kind=path`) to the patched source tree |
| stock switch | `ir2vec-stock` | `ocaml-base-compiler.5.5.1`, used only for object-file comparison |
| Dump format | 2 | `compiler-patch/ir2vec-hooks.patch` revision 3: header adds `hooks` and `build` (MD5 of the compiler), D5.13. The corpus dumps are format 1 (revision 2, `-pack` units skipped, D3.13). |
| Host | WSL2, Ubuntu 26.04, x86_64 | |
| opam | 2.5.0 | Ubuntu apt package |
| dune | 3.24.2 | installed in both switches |
| ocamlfind | 1.9.9~preview | opam's solver chose this; it's the newest listed version (`1.9.9~preview` sorts after 1.9.8) |
| Python | 3.14.4 | WSL system Python; venv `~/ir2vec-venv` (D3.1) |
| numpy / matplotlib / pytest | 2.5.3 / 3.11.2 / 9.1.1 | installed in the venv |
| torch | 2.14.0+cpu | CPU wheel from download.pytorch.org (D4.6); training uses 4 threads |
