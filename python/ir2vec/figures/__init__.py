"""Phase 8 figures (BUILD_SPEC §8): `ir2vec figures <which>`.

Every figure is written to report/figures/ as PNG + SVG + .tsv. The
canonical environment is the ir2vec venv (matplotlib and numpy versions are
stamped into report/figures/MANIFEST.tsv); SVGs are byte-identical on
regeneration within one environment.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

FIGURES = ("seeds", "heatmap", "distinctness", "neighbours", "analogy", "functions", "probe")
MODELS = ("complex", "transe")


def _model_of(path: Path) -> str:
    import json
    return json.loads(Path(path).read_text())["metadata"]["model"]


def run(which: str, models: list[str], out_dir: Path, corpus=None,
        vocab_lambda: Path | None = None, vocab_cmm: Path | None = None) -> list[Path]:
    import matplotlib
    import numpy as np

    from ..config import VocabConfig
    from . import analogy, bars, common as C, functions, heatmap, neighbours, probe, seeds
    cfg = VocabConfig.load()
    todo = FIGURES if which == "all" else (which,)
    if vocab_lambda or vocab_cmm:
        if not (vocab_lambda and vocab_cmm):
            raise SystemExit("--vocab-lambda and --vocab-cmm go together")
        m = _model_of(vocab_lambda)
        if _model_of(vocab_cmm) != m:
            raise SystemExit("--vocab-lambda and --vocab-cmm are different models")
        paths = {m: {"lambda": Path(vocab_lambda), "cmm": Path(vocab_cmm)}}
    else:
        paths = {m: {lvl: C.vocab_path(lvl, m) for lvl in ("lambda", "cmm")} for m in models}
    lvs = [C.load_level(lvl, paths[m][lvl], cfg) for m in paths for lvl in ("lambda", "cmm")]
    out: list[Path] = []
    for fig in todo:
        if fig == "seeds":
            for lv in lvs:
                out += seeds.draw_all(lv, out_dir)
        elif fig == "heatmap":
            out += [heatmap.draw(lv, out_dir) for lv in lvs]
        elif fig == "neighbours":
            out += [neighbours.draw(lv, out_dir) for lv in lvs]
        elif fig == "distinctness":
            out += [bars.draw_models(out_dir), bars.draw_alpha(out_dir)]
        elif fig == "analogy":
            out.append(analogy.draw(lvs, out_dir)[0])
        elif fig in ("functions", "probe"):
            if corpus is None:
                raise SystemExit(f"figures {fig}: needs --corpus")
            results = {}
            for m in paths:
                d = functions.load_or_build(corpus, m, cfg, paths[m])
                if fig == "functions":
                    out.append(functions.draw(d, out_dir))
                else:
                    import json
                    results[m] = (json.loads(str(d["meta"])), probe.run(d))
            if fig == "probe":
                out.append(probe.draw(results, out_dir))
    _manifest(out_dir, matplotlib.__version__, np.__version__)
    return out


def _manifest(out_dir: Path, mpl: str, npv: str) -> None:
    rows = [f"# matplotlib {mpl} · numpy {npv}", "file\tsha256"]
    for p in sorted(out_dir.glob("*")):
        if p.suffix in (".png", ".svg", ".tsv", ".json") and p.is_file() and p.name != "MANIFEST.tsv":
            rows.append(f"{p.name}\t{hashlib.sha256(p.read_bytes()).hexdigest()}")
    (out_dir / "MANIFEST.tsv").write_text("\n".join(rows) + "\n")
