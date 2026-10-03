"""Phase 4: trainer on the golden triples (tiny, fast)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import torch

from ir2vec import inventory, train as tr

GOLDEN = inventory.REPO / "tests" / "golden"


def golden_data(level: str) -> tr.TripleData:
    tsv = GOLDEN / f"fact.{level}.triples.tsv"
    ents = sorted({e for line in tsv.read_text().splitlines()
                   for e in (line.split("\t")[0], line.split("\t")[2])})
    rels = list(inventory.load().level(level).relations)
    return tr.load_triples(tsv, ents, rels)


def small(model: str, **kw) -> tr.TrainConfig:
    base = dict(dim=16, epochs=6, steps_per_epoch=3, batch_size=8,
                valid_fraction=0.2, threads=1)
    return tr.TrainConfig(model=model, **(base | kw))


@pytest.mark.parametrize("model", tr.MODELS)
@pytest.mark.parametrize("level", ["lambda", "cmm"])
def test_trains_and_saves(tmp_path: Path, model, level):
    data = golden_data(level)
    res = tr.train(data, small(model), log=lambda *_: None)
    assert res.entity_vectors.shape == (data.n_entities, 16)
    assert np.isfinite(res.entity_vectors).all()
    assert {"valid", "valid_novel"} <= set(res.metrics)
    ent, rel = tr.save(res, data, level, tmp_path, {"config_sha256": "x"})
    d = json.loads(ent.read_text())
    assert set(d["entities"]) == set(data.entities)
    assert all(len(v) == 16 for v in d["entities"].values())
    assert d["metadata"]["model"] == model and d["metadata"]["triples_sha256"] == data.sha256
    assert set(json.loads(rel.read_text())["relations"]) == set(data.relations)


def test_complex_vector_is_real_then_imag():
    data = golden_data("lambda")
    torch.manual_seed(0)
    m = tr.ComplEx(data.n_entities, len(data.relations), 8)
    v = m.entity_vectors()
    assert v.shape == (data.n_entities, 8)
    assert torch.equal(v[:, :4], m.ent_re.detach()) and torch.equal(v[:, 4:], m.ent_im.detach())


def test_complex_head_and_tail_scores_agree():
    torch.manual_seed(0)
    m = tr.ComplEx(7, 3, 8)
    h, r, t = torch.tensor([1, 4]), torch.tensor([0, 2]), torch.tensor([3, 6])
    s = m.score(h, r, t)
    assert torch.allclose(m.score_all_tails(h, r).gather(1, t[:, None]).squeeze(1), s)
    assert torch.allclose(m.score_all_heads(r, t).gather(1, h[:, None]).squeeze(1), s)


def test_training_is_byte_deterministic(tmp_path: Path):
    data = golden_data("cmm")
    paths = []
    for run in ("a", "b"):
        res = tr.train(data, small("complex"), log=lambda *_: None)
        ent, _ = tr.save(res, data, "cmm", tmp_path / run, {})
        paths.append(ent)
    strip = lambda p: {k: v for k, v in json.loads(p.read_text()).items()}  # noqa: E731
    a, b = strip(paths[0]), strip(paths[1])
    for d in (a, b):                     # wall-clock timings are not part of the model
        for row in d["metadata"]["history"]:
            row.pop("seconds")
    assert a == b


def test_filtered_rank_ignores_other_true_answers():
    scores = torch.tensor([[0.9, 0.8, 0.1, 0.8]])
    known = torch.tensor([[True, True, False, False]])   # 0 and 1 are both true
    # target 1: entity 0 scores higher but is a true answer -> filtered out;
    # entity 3 ties -> counts half
    assert tr._ranks(scores, torch.tensor([1]), known).item() == 1.5


def test_unknown_entity_in_triples_is_an_error(tmp_path: Path):
    p = tmp_path / "t.tsv"
    p.write_text("Caddi\tType\tINT\nNOPE\tType\tINT\n")
    with pytest.raises(ValueError, match="NOPE"):
        tr.load_triples(p, ["Caddi", "INT"], ["Type"])


def test_neighbour_report_mentions_expected_pairs():
    data = golden_data("cmm")
    res = tr.train(data, small("transe"), log=lambda *_: None)
    rep = tr.neighbour_report(data.entities, res.entity_vectors, "cmm")
    assert "Caddi" in rep and "expected clusters" in rep


def test_sampling_weights_alpha():
    counts = np.array([1, 10, 10_000])
    w1 = tr.sampling_weights(counts, 1.0).numpy()
    w75 = tr.sampling_weights(counts, 0.75).numpy()
    assert np.allclose(w1, counts / counts.sum())           # alpha = 1: occurrence sampling
    assert (np.diff(w75) > 0).all()                          # order preserved
    assert w75[0] / w75[2] > w1[0] / w1[2]                   # dynamic range compressed


def test_movement_is_recorded(tmp_path: Path):
    data = golden_data("lambda")
    res = tr.train(data, small("complex"), log=lambda *_: None)
    assert res.movement.shape == (data.n_entities,) and (res.movement > 0).all()
    ent, _ = tr.save(res, data, "lambda", tmp_path, {})
    meta = json.loads(ent.read_text())["metadata"]
    assert meta["sampling_alpha"] == 0.75 and set(meta["movement"]) == set(data.entities)


def test_loss_plateau_stops_early():
    data = golden_data("cmm")
    cfg = small("transe", epochs=50, plateau_patience=1, plateau_tol=0.99)
    res = tr.train(data, cfg, log=lambda *_: None)
    assert res.epochs_run == 2
