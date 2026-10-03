"""`ir2vec embed`: vectors for a new program (BUILD_SPEC Phase 6).

Input: one .ml file (compiled with `ocamlfind ocamlopt -c`, optional
-package flags) or a dune project directory (`dune build` on a fresh copy;
optionally `opam install --deps-only` first). Compilation runs in the ir2vec
switch with IR2VEC_DUMP_DIR set and the dune cache disabled; every dump is
extracted, the two levels are aligned (align.py) and encoded with the frozen
config and the chosen vocabularies.

Per function and per module (unit):
  final = concat(L2(lambda_sym), L2(cmm_fa), log1p(counts_lambda),
                 log1p(counts_cmm), log1p(node_counts))
counts_lambda / counts_cmm: the inventory's fixed count features, then the
frozen extern whitelist (shared by both levels), then EXT_OTHER.
node_counts: lambda_nodes, cmm_instructions (non-synthetic), cmm_blocks,
cmm_counted (live, D2.15). Unaligned functions keep zeros in the missing
level's blocks and are reported by category.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import inventory
from .align import align, cmm_parents
from .config import VocabConfig
from .encode import cmm_enc, lambda_enc
from .encode.vocab import Vocabulary, Weights
from .triples import owned_nodes

SWITCH = "ir2vec"
NODE_COUNTS = ("lambda_nodes", "cmm_instructions", "cmm_blocks", "cmm_counted")


class EmbedError(RuntimeError):
    pass


@dataclass
class EmbedOptions:
    packages: list[str] = field(default_factory=list)
    install_deps: bool = False
    keep_temp: bool = False


def _run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise EmbedError(f"{' '.join(cmd)} failed ({p.returncode}):\n{p.stderr[-4000:]}")


def _opam(*args: str) -> list[str]:
    return ["opam", "exec", f"--switch={SWITCH}", "--", *args]


def extractor() -> Path:
    _run(_opam("dune", "build", "--root", str(inventory.REPO),
               "extractor/bin/ir2vec_extract.exe"), inventory.REPO)
    return inventory.REPO / "_build" / "default" / "extractor" / "bin" / "ir2vec_extract.exe"


def compile_to_dumps(src: Path, work: Path, opts: EmbedOptions) -> Path:
    dumps = work / "dumps"
    env = dict(os.environ, IR2VEC_DUMP_DIR=str(dumps), DUNE_CACHE="disabled")
    if src.is_file():
        if src.suffix != ".ml":
            raise EmbedError(f"{src}: expected a .ml file or a dune project directory")
        d = work / "src"
        d.mkdir()
        files = [src.name]
        shutil.copy2(src, d / src.name)
        mli = src.with_suffix(".mli")
        if mli.exists():
            shutil.copy2(mli, d / mli.name)
            files.insert(0, mli.name)
        pkg = ["-package", ",".join(opts.packages)] if opts.packages else []
        _run(_opam("ocamlfind", "ocamlopt", "-c", *pkg, *files), d, env)
    elif (src / "dune-project").exists():
        d = work / "project"
        shutil.copytree(src, d, ignore=shutil.ignore_patterns("_build", "_opam", ".git"))
        if opts.install_deps:
            if not list(d.glob("*.opam")):
                raise EmbedError(f"{src}: --install-deps needs a *.opam file")
            _run(["opam", "install", f"--switch={SWITCH}", "--deps-only", "-y", "."], d,
                 {k: v for k, v in env.items() if k != "IR2VEC_DUMP_DIR"})
        _run(_opam("dune", "build", "--root", "."), d, env)
    else:
        raise EmbedError(f"{src}: expected a .ml file or a directory with a dune-project")
    if not dumps.exists() or not any(dumps.glob("*.bin")):
        raise EmbedError("compilation produced no dumps: is the ir2vec switch's compiler patched? "
                         "(corpus/build_corpus.sh's canary checks this)")
    return dumps


def extract_units(dumps: Path, work: Path) -> list[tuple[dict, dict]]:
    exe = extractor()
    out = work / "json"
    out.mkdir()
    stems = sorted({p.name[: -len(".lambda.bin")] for p in dumps.glob("*.lambda.bin")})
    units = []
    for stem in stems:
        pair = []
        for level in ("lambda", "cmm"):
            dump, js = dumps / f"{stem}.{level}.bin", out / f"{stem}.{level}.json"
            if not dump.exists():
                raise EmbedError(f"{stem}: no {level} dump")
            _run([str(exe), level, str(dump), "-o", str(js)], work)
            pair.append(json.loads(js.read_text()))
        units.append((pair[0], pair[1]))
    return units


# ------------------------------------------------------------- vectors ---

def l2(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def count_names(inv_level, whitelist: list[str]) -> list[str]:
    return list(inv_level.count_features) + [f"EXT:{n}" for n in whitelist] + ["EXT_OTHER"]


def count_vector(counts: dict, names: list[str]) -> np.ndarray:
    idx = {n: i for i, n in enumerate(names)}
    v = np.zeros(len(names))
    for k, n in counts.items():
        if k.startswith("EXT:"):
            v[idx.get(k, idx["EXT_OTHER"])] += n
        elif k in idx:
            v[idx[k]] += n
        else:
            raise EmbedError(f"count feature {k!r} is not in the inventory")
    return v


def node_counts(lam_rec: dict | None, cmm_fn: dict | None, counted: int) -> np.ndarray:
    ln = sum(1 for _ in owned_nodes(lam_rec)) if lam_rec else 0
    ci = sum(1 for b in cmm_fn["blocks"] for i in b["instrs"]
             if not (i.get("synthetic") and i["op"] == "COPY")) if cmm_fn else 0
    cb = len(cmm_fn["blocks"]) if cmm_fn else 0
    return np.array([ln, ci, cb, counted if cmm_fn else 0], dtype=float)


def final_vector(lsym, cfa, cl, cc, nc) -> np.ndarray:
    return np.concatenate([l2(lsym), l2(cfa), np.log1p(cl), np.log1p(cc), np.log1p(nc)])


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _f(v: np.ndarray) -> list[float]:
    return [float(x) for x in v]


def embed_units(units: list[tuple[dict, dict]], vocab_lambda: Path, vocab_cmm: Path,
                cfg: VocabConfig, weights: Weights | None = None) -> dict:
    inv = inventory.load()
    w = weights or Weights.load()
    vl, vc = Vocabulary.load(vocab_lambda, cfg), Vocabulary.load(vocab_cmm, cfg)
    lnames = count_names(inv.lambda_, cfg.extern_whitelist)
    cnames = count_names(inv.cmm, cfg.extern_whitelist)
    dims = {"lambda_sym": vl.dim, "cmm_fa": vc.dim, "counts_lambda": len(lnames),
            "counts_cmm": len(cnames), "node_counts": len(NODE_COUNTS)}
    assert dims["counts_lambda"] == inv.lambda_.n_count_features
    assert dims["counts_cmm"] == inv.cmm.n_count_features
    dims["final"] = sum(dims.values())
    zl, zc = np.zeros(vl.dim), np.zeros(vc.dim)
    out_units, totals = [], {"lambda_functions": 0, "matched": 0, "cmm_functions": 0,
                             "unmatched_named": 0, "unmatched_anonymous": 0,
                             "unmatched_module_init": 0, "cmm_only": 0}
    for lam, cmm in units:
        al = align(lam, cmm)
        lsym = {f.fid: f for f in lambda_enc.lambda_sym(lam, vl, w)}
        lfa = {f.fid: f for f in lambda_enc.lambda_fa(lam, vl, w)}
        csym = {f.name: f for f in cmm_enc.cmm_sym(cmm, vc, w, cfg.count_synthetic)}
        cfa = {f.name: f for f in cmm_enc.cmm_fa(cmm, vc, w, cfg.count_synthetic)}
        lrec = {r["fid"]: r for r in lam["functions"]}
        cfun = {f["name"]: f for f in cmm["functions"]}
        parents = cmm_parents(cmm)
        fid_of = {m.cmm: m.fid for m in al.matches}
        rows = []

        def row(fid, cname, category, by):
            r, f = lrec.get(fid), cfun.get(cname)
            ls = lsym[fid].vector if fid else zl
            la = lfa[fid].vector if fid else zl
            cs = csym[cname].vector if cname else zc
            ca = cfa[cname].vector if cname else zc
            cl = count_vector(r["counts"], lnames) if r else np.zeros(len(lnames))
            cc = count_vector(f["counts"], cnames) if f else np.zeros(len(cnames))
            nc = node_counts(r, f, cfa[cname].n_counted if cname else 0)
            fin = final_vector(ls, ca, cl, cc, nc)
            assert len(fin) == dims["final"]
            rows.append({
                "lambda_fid": fid, "lambda_name": r["name"] if r else None,
                "lambda_kind": r["kind"] if r else None, "cmm_name": cname,
                "aligned": bool(fid and cname), "aligned_by": by, "category": category,
                # Cmm-only rows: the referring Cmm function and its Lambda fid, or
                # null when there is no unique referrer (D7.1)
                "parent_cmm": parents.get(cname) if category == "cmm_only" else None,
                "parent_fid": (fid_of.get(parents.get(cname))
                               if category == "cmm_only" else None),
                "loc": (r["loc"] if r else None) or (f["loc"] if f else None),
                "lambda_sym": _f(ls), "lambda_fa": _f(la), "cmm_sym": _f(cs), "cmm_fa": _f(ca),
                "counts_lambda": _f(cl), "counts_cmm": _f(cc), "node_counts": _f(nc),
                "final": _f(fin)})
            return ls, la, cs, ca, cl, cc, nc

        acc = [np.zeros(n) for n in (vl.dim, vl.dim, vc.dim, vc.dim, len(lnames),
                                     len(cnames), len(NODE_COUNTS))]
        parts = [row(m.fid, m.cmm, "aligned", m.by) for m in al.matches]
        for cat, fids in al.unmatched_lambda.items():
            parts += [row(fid, None, f"lambda_only:{cat}", None) for fid in fids]
        parts += [row(None, n, "cmm_only", None) for n in al.cmm_only]
        for p in parts:
            for a, x in zip(acc, p):
                a += x
        ls, la, cs, ca, cl, cc, nc = acc
        out_units.append({
            "unit": lam["unit"], "source": lam["source"], "functions": rows,
            "alignment": al.to_json(),
            "module": {"lambda_sym": _f(ls), "lambda_fa": _f(la), "cmm_sym": _f(cs),
                       "cmm_fa": _f(ca), "counts_lambda": _f(cl), "counts_cmm": _f(cc),
                       "node_counts": _f(nc), "final": _f(final_vector(ls, ca, cl, cc, nc))}})
        totals["lambda_functions"] += al.n_lambda
        totals["matched"] += len(al.matches)
        totals["cmm_functions"] += len(cmm["functions"])
        for cat, fids in al.unmatched_lambda.items():
            totals[f"unmatched_{cat}"] += len(fids)
        totals["cmm_only"] += len(al.cmm_only)
    totals["match_rate"] = (totals["matched"] / totals["lambda_functions"]
                            if totals["lambda_functions"] else None)
    return {
        "metadata": {
            "ocaml": inv.ocaml, "config_sha256": cfg.config_sha256, "weights": w.__dict__,
            "vocabularies": {"lambda": {"path": str(vocab_lambda), "sha256": _sha(vocab_lambda),
                                        "model": vl.metadata.get("model"),
                                        "sampling_alpha": vl.metadata.get("sampling_alpha")},
                             "cmm": {"path": str(vocab_cmm), "sha256": _sha(vocab_cmm),
                                     "model": vc.metadata.get("model"),
                                     "sampling_alpha": vc.metadata.get("sampling_alpha")}},
            "dims": dims,
            "final_layout": ["L2(lambda_sym)", "L2(cmm_fa)", "log1p(counts_lambda)",
                             "log1p(counts_cmm)", "log1p(node_counts)"],
            "count_features": {"lambda": lnames, "cmm": cnames},
            "node_counts": list(NODE_COUNTS)},
        "alignment": totals,
        "lookup": {"lambda": vl.report(), "cmm": vc.report()},
        "units": out_units}


def embed(src: Path, vocab_lambda: Path, vocab_cmm: Path, cfg: VocabConfig,
          opts: EmbedOptions | None = None) -> dict:
    opts = opts or EmbedOptions()
    work = Path(tempfile.mkdtemp(prefix="ir2vec-embed-"))
    try:
        dumps = compile_to_dumps(src.resolve(), work, opts)
        result = embed_units(extract_units(dumps, work), vocab_lambda, vocab_cmm, cfg)
        result["metadata"]["input"] = str(src)
        return result
    finally:
        if not opts.keep_temp:
            shutil.rmtree(work, ignore_errors=True)


def unknown_total(result: dict) -> int:
    return sum(sum(r["unknown"].values()) for r in result["lookup"].values())


def write_npy(result: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    funcs = [f for u in result["units"] for f in u["functions"]]
    np.save(out_dir / "functions.npy", np.asarray([f["final"] for f in funcs]))
    np.save(out_dir / "modules.npy", np.asarray([u["module"]["final"] for u in result["units"]]))
    index = {"metadata": result["metadata"], "alignment": result["alignment"],
             "lookup": result["lookup"],
             "functions": [{k: f[k] for k in ("lambda_fid", "lambda_name", "cmm_name",
                                              "aligned", "aligned_by", "category", "loc")}
                           | {"unit": u["unit"]} for u in result["units"] for f in u["functions"]],
             "modules": [u["unit"] for u in result["units"]]}
    (out_dir / "index.json").write_text(json.dumps(index, indent=1) + "\n")
