"""All four encoding cells for one compilation unit (lambda_sym, lambda_fa,
cmm_sym, cmm_fa), with lookup accounting and solver statistics."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..config import VocabConfig
from . import cmm_enc, lambda_enc
from .vocab import Vocabulary, Weights


def _vec(v: np.ndarray) -> list[float]:
    return [float(x) for x in v]


def encode_cells(lambda_unit: dict | None, cmm_unit: dict | None,
                 vocab_lambda: Path, vocab_cmm: Path, cfg: VocabConfig,
                 weights: Weights | None = None) -> dict:
    w = weights or Weights.load()
    out: dict = {"weights": w.__dict__, "config_sha256": cfg.config_sha256, "cells": {},
                 "lookup": {}, "solver": {}}
    if lambda_unit is not None:
        vl = Vocabulary.load(vocab_lambda, cfg)
        for cell, fn in (("lambda_sym", lambda_enc.lambda_sym), ("lambda_fa", lambda_enc.lambda_fa)):
            fvs = fn(lambda_unit, vl, w)
            out["cells"][cell] = {fv.fid: _vec(fv.vector) for fv in fvs}
            out["solver"][cell] = {fv.fid: {"cyclic_sccs": fv.stats.cyclic_sccs,
                                            "max_residual": fv.stats.max_residual,
                                            "retries": fv.stats.retries}
                                   for fv in fvs if fv.stats.cyclic_sccs or fv.stats.retries}
        out["lookup"]["lambda"] = vl.report()
    if cmm_unit is not None:
        vc = Vocabulary.load(vocab_cmm, cfg)
        for cell, flow in (("cmm_sym", False), ("cmm_fa", True)):
            fvs = cmm_enc.encode_unit(cmm_unit, vc, w, flow=flow,
                                      count_synthetic=cfg.count_synthetic)
            out["cells"][cell] = {fv.name: _vec(fv.vector) for fv in fvs}
            out["solver"][cell] = {fv.name: {"cyclic_sccs": fv.stats.cyclic_sccs,
                                             "max_residual": fv.stats.max_residual,
                                             "retries": fv.stats.retries}
                                   for fv in fvs if fv.stats.cyclic_sccs or fv.stats.retries}
        out["lookup"]["cmm"] = vc.report()
    return out


def unknown_total(result: dict) -> int:
    return sum(sum(r["unknown"].values()) for r in result["lookup"].values())
