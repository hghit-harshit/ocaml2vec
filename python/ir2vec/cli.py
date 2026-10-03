"""`ir2vec` command line. Pipeline order: select -> stats -> freeze-config -> triples.

  ir2vec select         [--corpus DIR] [--cap 0.15]
  ir2vec stats          [--corpus DIR] [--out FILE]
  ir2vec freeze-config  [--corpus DIR] [--stats FILE] [--threshold N] [--out FILE]
  ir2vec triples        --level lambda|cmm [--corpus DIR] [--config FILE] [--out-dir DIR]
  ir2vec check plateau  [--corpus DIR] [--out-dir DIR]
  ir2vec train          --level lambda|cmm --model complex|transe [--dim 128] [--epochs N]
  ir2vec figures        {seeds|heatmap|distinctness|neighbours|analogy|functions|probe|all}
                        [--model complex|transe|both] [--vocab-lambda F --vocab-cmm F]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import config as cfgmod
from . import inventory, metrics, stats, triples
from . import select as selmod
from .corpus import Corpus, default_dir

REPORT_DIR = inventory.REPO / "report"


def _corpus(args, raw: bool = False) -> Corpus:
    c = Corpus(Path(args.corpus), raw=raw)
    if not c.manifest.exists():
        sys.exit(f"{c.manifest}: no corpus manifest (run corpus/build_corpus.sh)")
    if not raw and not c.selection_path.exists():
        sys.exit(f"{c.selection_path}: no corpus selection (run `ir2vec select`)")
    return c


def cmd_select(args) -> int:
    corpus = _corpus(args, raw=True)
    sel = selmod.select(corpus, cap=args.cap)
    selmod.write(sel, corpus.selection_path)
    print(f"cap {sel['cap']:.0%}: at most {sel['max_units_per_package']} units per package; "
          f"{sel['selected_units']} of {sel['raw_units']} units selected, "
          f"{len(sel['exemptions'])} coverage exemptions")
    for p, v in sel["packages"].items():
        if len(v["selected"]) < v["units"]:
            print(f"  capped {p}: {len(v['selected'])} / {v['units']} units "
                  f"({v['share']:.1%} of the corpus)")
    for e in sel["exemptions"]:
        print(f"  exempt {e['package']}/{e['unit']}: {', '.join(e['entities'])}")
    print(f"wrote {corpus.selection_path}")
    return 0


def _stdlib_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    if "IR2VEC_STDLIB" in os.environ:
        return Path(os.environ["IR2VEC_STDLIB"])
    out = subprocess.run(["opam", "exec", "--switch=ir2vec", "--", "ocamlfind", "ocamlc", "-where"],
                         check=True, capture_output=True, text=True)
    return Path(out.stdout.strip())


def cmd_stats(args) -> int:
    corpus, inv = _corpus(args), inventory.load()
    s = stats.compute(corpus, inv)
    out = Path(args.out or corpus.root / "stats.json")
    out.write_text(json.dumps(s, indent=1) + "\n")
    print(f"corpus {s['corpus_sha256'][:12]}  packages {len(s['packages'])}")
    for level in inventory.LEVELS:
        lv = s[level]
        print(f"{level:7s} units {lv['n_units']:6d}  functions {lv['n_functions']:7d}  "
              f"triples {lv['n_triples']:9d}  entities seen {lv['distinct_entities']:3d} / "
              f"inventory {lv['inventory_entities']} (schema {lv['schema_entities']})  "
              f"never seen {len(lv['never_seen'])}  unknown {sum(lv['unknown'].values())}")
    print(f"externs: {len(s['externs']['combined'])} distinct native names, "
          f"{sum(1 for n in s['externs']['packages'].values() if n >= cfgmod.MIN_PACKAGES)} "
          f"used by >= {cfgmod.MIN_PACKAGES} packages")
    print(f"wrote {out}")
    return 0


def cmd_freeze(args) -> int:
    corpus, inv = _corpus(args), inventory.load()
    stats_path = Path(args.stats or corpus.root / "stats.json")
    s = json.loads(stats_path.read_text())
    sha = corpus.sha256()
    if s["corpus_sha256"] != sha or s["inventory_sha256"] != inv.sha256:
        sys.exit(f"{stats_path} is stale (corpus or inventory changed): rerun `ir2vec stats`")
    sel = corpus.selection()
    sel_params = {k: sel[k] for k in ("version", "cap", "max_units_per_package",
                                       "selected_units", "raw_units")}
    try:
        cfg = cfgmod.freeze(inv, s, sha, cfgmod.stdlib_externals(_stdlib_dir(args.stdlib_dir)),
                            selection=sel_params, threshold=args.threshold)
    except cfgmod.FreezeError as e:
        sys.exit(f"freeze-config: {e}")
    out = Path(args.out)
    cfg.save(out)
    print(f"whitelist (shared by both levels): {len(cfg.pinned_resolved)} pinned + "
          f"{len(cfg.extern_whitelist) - len(cfg.pinned_resolved)} by #packages "
          f"(>= {cfg.extern_min_packages}); pins absent from the corpus: "
          f"{cfg.pinned_zero or 'none'}")
    for level in inventory.LEVELS:
        cv = cfg.coverage[level]
        print(f"{level}: inventory {cv['inventory']}, trained entities {cv['trained_entities']} "
              f"(vocabulary {cv['trained_vocabulary']} after merges), merged away "
              f"{cv['merged_away']}, fallback-mapped {cv['fallback_mapped']}, "
              f"impossible {cv['impossible']}")
        print(f"  merges: {sorted(cfg.merges[level]) or 'none'}")
        print(f"  fallbacks: {cfg.fallback_map[level] or 'none'}")
        print(f"  low-confidence (< {cfg.threshold} triples): {cfg.low_confidence[level]}")
    print(f"wrote {out} (config {cfg.config_sha256[:12]})")
    return 0


def cmd_triples(args) -> int:
    corpus, inv = _corpus(args), inventory.load()
    cfg = cfgmod.VocabConfig.load(Path(args.config))
    if cfg.inventory_sha256 != inv.sha256:
        sys.exit("vocab config was frozen against a different entity inventory")
    sha = corpus.sha256()
    if cfg.corpus_sha256 != sha:
        print("WARNING: vocab config was frozen on a different corpus; it is NOT "
              "recomputed (rerun `ir2vec freeze-config` explicitly to refreeze)",
              file=sys.stderr)
    level, lv = args.level, inv.level(args.level)
    merge = cfg.merge_map(level)
    vocab, relations = set(cfg.trained[level]), set(lv.relations)
    summary = triples.TripleSummary(level)
    out_dir = Path(args.out_dir or corpus.root / "triples")

    def gen():
        for _pkg, unit in corpus.units(level):
            summary.n_units += 1
            for t in triples.unit_triples(level, unit, merge, cfg.count_synthetic):
                summary.add(t, vocab, relations)
                yield t

    triples.write_tsv(out_dir / f"{level}.tsv", gen())
    body = summary.to_json() | {"config_sha256": cfg.config_sha256, "corpus_sha256": sha,
                                "vocabulary": sorted(vocab),
                                "never_seen": sorted(vocab - set(summary.entity_triples))}
    (out_dir / f"{level}.summary.json").write_text(json.dumps(body, indent=1) + "\n")
    print(f"{level}: {summary.n_triples} triples from {summary.n_units} units, "
          f"{len(summary.entity_triples)} / {len(vocab)} entities seen, "
          f"relations {dict(sorted(summary.relations.items()))}")
    impossible = {e: n for e, n in summary.entity_triples.items() if e in cfg.impossible[level]}
    if impossible:
        print(f"ERROR impossible entities (hook or lowering bug): {impossible}", file=sys.stderr)
        return 2
    if summary.unknown:
        print(f"UNKNOWN entities ({sum(summary.unknown.values())}): "
              f"{dict(summary.unknown.most_common(20))}", file=sys.stderr)
        return 1
    return 0


def cmd_entities(args) -> int:
    corpus, inv = _corpus(args), inventory.load()
    cfg = cfgmod.VocabConfig.load(Path(args.config))
    s = json.loads((corpus.root / "stats.json").read_text())
    if s["corpus_sha256"] != cfg.corpus_sha256:
        sys.exit("stats.json and the vocab config describe different corpora")
    rows = metrics.entity_report(inv, cfg, s)
    out = Path(args.out_dir) / "entities.tsv"
    out.parent.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0])
    out.write_text("".join("\t".join(str(r[c]) for c in cols) + "\n"
                           for r in [dict(zip(cols, cols)), *rows]))
    for level in inventory.LEVELS:
        n, d = metrics.distinct_triples(corpus.root / "triples" / f"{level}.tsv")
        st = {}
        for r in rows:
            if r["level"] == level:
                k = r["status"].split(" ")[0].split("->")[0]
                st[k] = st.get(k, 0) + 1
        print(f"{level}: {n} triples, {d} distinct; entities by status {dict(sorted(st.items()))}")
    print(f"wrote {out}")
    return 0


def cmd_distinctness(args) -> int:
    inv = inventory.load()
    rows, lines = [], []
    for path in args.vocab:
        meta, names, vecs = metrics.load_vocab(Path(path))
        level = meta["level"]
        d = metrics.distinctness(level, inv, names, vecs)
        r = metrics.rare_report(level, meta, names, vecs)
        tag = f"{level}.{meta['model']} a={meta.get('sampling_alpha', 1.0)}"
        rows.append((tag, d, r))
    groups = sorted({g for _, d, _ in rows for g in d if not g.startswith("_")})
    lines.append("| vocabulary | " + " | ".join(groups) + " | low-conf. movement / rest"
                 " | low-conf. cohesion |")
    lines.append("|---" * (len(groups) + 3) + "|")
    for tag, d, r in rows:
        cells = [(f"{d[g]['score']:.3f}" + (" FLAG" if d[g]["flag"] else "")) if g in d else "-"
                 for g in groups]
        mv = (f"{r['movement_low']:.2f} / {r['movement_rest']:.2f}"
              if r["movement_low"] is not None else "-")
        coh = f"{r['low_cohesion_ratio']:.3f}" if r["low_cohesion_ratio"] is not None else "-"
        lines.append(f"| {tag} | " + " | ".join(cells) + f" | {mv} | {coh} |")
    for tag, _d, r in rows:
        lines.append(f"\n{tag}: rare families (movement; nearest neighbours; "
                     f"# low-confidence among them)")
        for e, f in r["families"].items():
            mv = f"{f['movement']:.2f}" if f["movement"] is not None else "-"
            nb = ", ".join(f"{n} {c:.2f}" for n, c in f["neighbours"])
            lines.append(f"  {e}: movement {mv}; {nb}; {f['low_confidence_neighbours']}/5")
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"wrote {args.out}")
    return 0


def cmd_alignment(args) -> int:
    corpus = _corpus(args)
    totals, rows = metrics.alignment_report(corpus)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cols = ["package", "unit", "side", "category", "function", "loc"]
    (out / "alignment.tsv").write_text("".join("\t".join(r[c] for c in cols) + "\n"
                                              for r in [dict(zip(cols, cols)), *rows]))
    (out / "alignment.json").write_text(json.dumps(totals, indent=1) + "\n")
    print(json.dumps(totals, indent=1))
    print(f"wrote {out / 'alignment.tsv'} ({len(rows)} unmatched functions)")
    return 0


def cmd_encode_check(args) -> int:
    corpus = _corpus(args)
    cfg = cfgmod.VocabConfig.load(Path(args.config))
    st = metrics.encode_check(corpus, Path(args.vocab_lambda), Path(args.vocab_cmm), cfg)
    out = Path(args.out_dir) / f"encode_check.{Path(args.vocab_lambda).stem.split('.')[-1]}.json"
    out.write_text(json.dumps(st, indent=1) + "\n")
    print(json.dumps(st, indent=1))
    print(f"wrote {out}")
    bad = st["impossible"] or st["non_finite"] or any(
        r["unknown"] for r in st["lookup"].values())
    return 1 if bad else 0


def cmd_plateau(args) -> int:
    corpus, inv = _corpus(args), inventory.load()
    rows = metrics.plateau(corpus, inv)
    csv_path, png_path = metrics.write_plateau(rows, Path(args.out_dir))
    last = rows[-1] if rows else {}
    print(f"{len(rows)} packages; final lambda {last.get('lambda_entities')} / "
          f"{len(inv.lambda_.entities)}, cmm {last.get('cmm_entities')} / {len(inv.cmm.entities)}")
    print(f"wrote {csv_path} and {png_path}")
    return 0


VOCAB_DIR = inventory.REPO / "vocab"


def cmd_train(args) -> int:
    from . import train as tr
    inv = inventory.load()
    cfg = cfgmod.VocabConfig.load(Path(args.config))
    if cfg.inventory_sha256 != inv.sha256:
        sys.exit("vocab config was frozen against a different entity inventory")
    level = args.level
    tsv = Path(args.triples_dir or Path(args.corpus) / "triples") / f"{level}.tsv"
    summary = json.loads(tsv.with_suffix(".summary.json").read_text())
    if summary["config_sha256"] != cfg.config_sha256:
        sys.exit(f"{tsv}: generated with a different vocab config; rerun `ir2vec triples`")
    data = tr.load_triples(tsv, list(cfg.trained[level]), list(inv.level(level).relations))
    tcfg = tr.TrainConfig(model=args.model, dim=args.dim, epochs=args.epochs,
                          threads=args.threads, seed=args.seed, sampling_alpha=args.alpha)
    print(f"{level}/{args.model}: {len(data.triples)} triples, {data.n_entities} entities, "
          f"{len(data.relations)} relations, dim {tcfg.dim}")
    res = tr.train(data, tcfg)
    prov = {"config_sha256": cfg.config_sha256, "corpus_sha256": cfg.corpus_sha256,
            "inventory_sha256": cfg.inventory_sha256,
            "low_confidence": cfg.low_confidence[level],
            "fallback_map": cfg.fallback_map[level], "impossible": cfg.impossible[level]}
    ent, rel = tr.save(res, data, level, Path(args.out_dir), prov)
    m = res.metrics
    print(f"alpha {tcfg.sampling_alpha}, {res.epochs_run} epochs: valid MRR {m['valid']['mrr']:.4f} "
          f"hits@1 {m['valid']['hits@1']:.4f} hits@10 {m['valid']['hits@10']:.4f} "
          f"(n={m['valid']['n']}); novel MRR {m['valid_novel']['mrr']:.4f} "
          f"hits@10 {m['valid_novel']['hits@10']:.4f} (n={m['valid_novel']['n']})")
    report = tr.neighbour_report(data.entities, res.entity_vectors, level)
    print(report)
    rdir = Path(args.report_dir)
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / f"nn_{level}_{args.model}.txt").write_text(report + "\n")
    print(f"wrote {ent} and {rel}")
    return 0


def cmd_encode(args) -> int:
    from .encode.cells import encode_cells, unknown_total
    cfg = cfgmod.VocabConfig.load(Path(args.config))
    lam = json.loads(Path(args.lambda_unit).read_text()) if args.lambda_unit else None
    cmm = json.loads(Path(args.cmm_unit).read_text()) if args.cmm_unit else None
    res = encode_cells(lam, cmm, Path(args.vocab_lambda), Path(args.vocab_cmm), cfg)
    text = json.dumps(res, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
    n_unknown = unknown_total(res)
    if n_unknown:
        print(f"{n_unknown} unknown entity lookups: {res['lookup']}", file=sys.stderr)
        return 1
    return 0


def cmd_embed(args) -> int:
    from . import embed as em
    from .encode.vocab import ImpossibleEntity
    cfg = cfgmod.VocabConfig.load(Path(args.config))
    opts = em.EmbedOptions(packages=args.package or [], install_deps=args.install_deps,
                           keep_temp=args.keep_temp)
    try:
        res = em.embed(Path(args.path), Path(args.vocab_lambda), Path(args.vocab_cmm), cfg, opts)
    except em.EmbedError as e:
        print(f"embed: {e}", file=sys.stderr)
        return 2
    except ImpossibleEntity as e:
        print(f"embed: {e}", file=sys.stderr)
        return 3
    if args.format == "npy":
        if not args.out:
            sys.exit("--format npy needs -o DIR")
        em.write_npy(res, Path(args.out))
    else:
        text = json.dumps(res, indent=1) + "\n"
        if args.out:
            Path(args.out).write_text(text)
        else:
            sys.stdout.write(text)
    a, d = res["alignment"], res["metadata"]["dims"]
    print(f"embedded {len(res['units'])} units: {a['matched']}/{a['lambda_functions']} Lambda "
          f"functions aligned (unmatched named {a['unmatched_named']}, anonymous "
          f"{a['unmatched_anonymous']}, module_init {a['unmatched_module_init']}; "
          f"Cmm-only {a['cmm_only']}); final dim {d['final']} = {d}", file=sys.stderr)
    n_unknown = em.unknown_total(res)
    if n_unknown:
        print(f"{n_unknown} unknown entity lookups: {res['lookup']}", file=sys.stderr)
        if not args.allow_unknown:
            return 1
    return 0


def cmd_figures(args) -> int:
    from . import figures
    models = list(figures.MODELS) if args.model == "both" else [args.model]
    corpus = None
    if args.which in ("functions", "probe", "all"):
        corpus = Corpus(Path(args.corpus))
    for path in figures.run(args.which, models, Path(args.out_dir), corpus,
                            args.vocab_lambda, args.vocab_cmm):
        print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ir2vec")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_corpus(sp):
        sp.add_argument("--corpus", default=str(default_dir()))
        return sp

    se = with_corpus(sub.add_parser("select", help="per-package cap (writes selection.json)"))
    se.add_argument("--cap", type=float, default=selmod.DEFAULT_CAP)
    se.set_defaults(func=cmd_select)

    s = with_corpus(sub.add_parser("stats", help="corpus frequencies per level"))
    s.add_argument("--out")
    s.set_defaults(func=cmd_stats)

    f = with_corpus(sub.add_parser("freeze-config", help="write config/vocab_config.json"))
    f.add_argument("--stats")
    f.add_argument("--threshold", type=int, default=cfgmod.DEFAULT_THRESHOLD)
    f.add_argument("--out", default=str(cfgmod.DEFAULT_PATH))
    f.add_argument("--stdlib-dir")
    f.set_defaults(func=cmd_freeze)

    t = with_corpus(sub.add_parser("triples", help="generate training triples"))
    t.add_argument("--level", required=True, choices=inventory.LEVELS)
    t.add_argument("--config", default=str(cfgmod.DEFAULT_PATH))
    t.add_argument("--out-dir")
    t.set_defaults(func=cmd_triples)

    c = sub.add_parser("check", help="corpus checks")
    csub = c.add_subparsers(dest="check", required=True)
    pl = with_corpus(csub.add_parser("plateau", help="entity count vs packages"))
    pl.add_argument("--out-dir", default=str(REPORT_DIR))
    pl.set_defaults(func=cmd_plateau)
    di = csub.add_parser("distinctness", help="sibling-group distinctness (schema §4)")
    di.add_argument("--vocab", nargs="+", required=True)
    di.add_argument("--out")
    di.set_defaults(func=cmd_distinctness)
    al = with_corpus(csub.add_parser("alignment", help="Lambda<->Cmm match rate over the corpus"))
    al.add_argument("--out-dir", default=str(REPORT_DIR))
    al.set_defaults(func=cmd_alignment)
    ek = with_corpus(csub.add_parser("encode", help="encode the whole corpus (inference check)"))
    ek.add_argument("--vocab-lambda", default=str(VOCAB_DIR / "lambda.complex.json"))
    ek.add_argument("--vocab-cmm", default=str(VOCAB_DIR / "cmm.complex.json"))
    ek.add_argument("--config", default=str(cfgmod.DEFAULT_PATH))
    ek.add_argument("--out-dir", default=str(REPORT_DIR))
    ek.set_defaults(func=cmd_encode_check)
    en = with_corpus(csub.add_parser("entities", help="per-entity triple counts and status"))
    en.add_argument("--config", default=str(cfgmod.DEFAULT_PATH))
    en.add_argument("--out-dir", default=str(REPORT_DIR))
    en.set_defaults(func=cmd_entities)

    tr = with_corpus(sub.add_parser("train", help="train a KG embedding (seed vocabulary)"))
    tr.add_argument("--level", required=True, choices=inventory.LEVELS)
    tr.add_argument("--model", required=True, choices=("complex", "transe"))
    tr.add_argument("--dim", type=int, default=128)
    tr.add_argument("--epochs", type=int, default=60)
    tr.add_argument("--alpha", type=float, default=0.75, help="sampling exponent (D5.1)")
    tr.add_argument("--threads", type=int, default=4)
    tr.add_argument("--seed", type=int, default=20260925)
    tr.add_argument("--config", default=str(cfgmod.DEFAULT_PATH))
    tr.add_argument("--triples-dir")
    tr.add_argument("--out-dir", default=str(VOCAB_DIR))
    tr.add_argument("--report-dir", default=str(REPORT_DIR))
    tr.set_defaults(func=cmd_train)

    ec = sub.add_parser("encode", help="encode one unit's JSON at all four cells")
    ec.add_argument("--lambda-unit")
    ec.add_argument("--cmm-unit")
    ec.add_argument("--vocab-lambda", default=str(VOCAB_DIR / "lambda.complex.json"))
    ec.add_argument("--vocab-cmm", default=str(VOCAB_DIR / "cmm.complex.json"))
    ec.add_argument("--config", default=str(cfgmod.DEFAULT_PATH))
    ec.add_argument("-o", "--out")
    ec.set_defaults(func=cmd_encode)

    em_ = sub.add_parser("embed", help="embed a new program (.ml file or dune project)")
    em_.add_argument("path")
    em_.add_argument("--package", action="append", help="ocamlfind package (single .ml)")
    em_.add_argument("--install-deps", action="store_true",
                     help="opam install --deps-only a dune project first")
    em_.add_argument("--vocab-lambda", default=str(VOCAB_DIR / "lambda.complex.json"))
    em_.add_argument("--vocab-cmm", default=str(VOCAB_DIR / "cmm.complex.json"))
    em_.add_argument("--config", default=str(cfgmod.DEFAULT_PATH))
    em_.add_argument("--format", choices=("json", "npy"), default="json")
    em_.add_argument("-o", "--out")
    em_.add_argument("--allow-unknown", action="store_true")
    em_.add_argument("--keep-temp", action="store_true")
    em_.set_defaults(func=cmd_embed)

    fg = with_corpus(sub.add_parser("figures", help="Phase 8 figures (report/figures/)"))
    from .figures import FIGURES, MODELS
    fg.add_argument("which", choices=(*FIGURES, "all"))
    fg.add_argument("--model", choices=(*MODELS, "both"), default="both")
    fg.add_argument("--vocab-lambda")
    fg.add_argument("--vocab-cmm")
    fg.add_argument("--out-dir", default=str(REPORT_DIR / "figures"))
    fg.set_defaults(func=cmd_figures)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
