# ocaml-ir2vec

IR2Vec-style embeddings for OCaml programs, built from the native compiler's Lambda and Cmm IRs.

- Specification: `docs/BUILD_SPEC.md`
- Schema: `docs/ocaml-ir2vec-schema.md`

## Setup (WSL2 / Linux)

```sh
sudo apt-get install -y opam build-essential unzip bzip2 m4 bubblewrap pkg-config
compiler-patch/make_switch.sh --stock   # switches "ir2vec" (patched) and "ir2vec-stock"
```

## Dumping IR

```sh
IR2VEC_DUMP_DIR=/tmp/d opam exec --switch=ir2vec -- ocamlfind ocamlopt -c foo.ml
# -> /tmp/d/Foo.<md5>.lambda.bin  /tmp/d/Foo.<md5>.cmm.bin
```

Nothing is written unless `IR2VEC_DUMP_DIR` is set and non-empty.

## Tests

```sh
opam exec --switch=ir2vec -- dune test      # from the repo root
compiler-patch/check_objects.sh             # object files: patched vs stock
opam exec --switch=ir2vec -- dune promote   # accept changed goldens / entity inventory
```

## Extracting

```sh
ir2vec-extract lambda /tmp/d/Foo.<md5>.lambda.bin -o foo.lambda.json
ir2vec-extract cmm /tmp/d/Foo.<md5>.cmm.bin -o foo.cmm.json
ir2vec-extract entities -o docs/entities.5.5.1.json   # also produced by `dune test`

# manual stress test over the compiler testsuite (a few minutes)
opam exec --switch=ir2vec -- bash extractor/test/stress_testsuite.sh
```

## Corpus, vocabulary and training (Python, WSL venv `~/ir2vec-venv`)

```sh
compiler-patch/make_switch.sh --stock          # patched switch (invariant pinned) + stock switch
corpus/build_corpus.sh                         # all packages in corpus/packages.txt
ir2vec select                                  # 15% per-package cap -> $CORPUS/selection.json
ir2vec stats                                   # frequencies, per-entity triple counts
ir2vec freeze-config                           # -> config/vocab_config.json (only way to change it)
ir2vec triples --level lambda && ir2vec triples --level cmm
ir2vec check plateau && ir2vec check entities  # report/plateau.*, report/entities.tsv
ir2vec train --level lambda --model complex    # -> vocab/lambda.complex.json (+ transe, cmm)
cd python && python -m pytest                  # Python tests
```

## Embedding new programs

```sh
ir2vec embed foo.ml -o foo.json                       # single file (add --package P as needed)
ir2vec embed path/to/dune-project --install-deps      # dune project, opam deps installed first
ir2vec embed foo.ml --format npy -o out/              # functions.npy, modules.npy, index.json
ir2vec embed foo.ml --vocab-lambda vocab/lambda.transe.json --vocab-cmm vocab/cmm.transe.json
ir2vec check alignment                                # corpus-wide Lambda<->Cmm match rate
```
