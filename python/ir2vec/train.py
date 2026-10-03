"""Knowledge-graph embedding training (BUILD_SPEC Phase 4).

A small PyTorch trainer: PyKEEN deduplicates labeled triples
(`_map_triples_elements_to_ids` ends in `np.unique(..., axis=0)`), and the
schema keeps duplicates because frequency is signal (D4.6).

  - ComplEx (primary): rank dim/2, logistic loss, L2 regularisation; the entity
    vector is concat(real, imag).
  - TransE (baseline): L1 distance, margin ranking loss, unit-norm entities.

Both use uniform head/tail corruption for negatives. The split is 95/5 over
triple *occurrences*. Training samples the distinct training triples with
probability proportional to count**sampling_alpha (D5.1): alpha = 1 is exactly
occurrence sampling; alpha = 0.75 (word2vec's exponent) compresses the dynamic
range so rare entities receive gradient while the frequency order is kept.
An epoch is a fixed number of steps; training stops on a loss plateau or at
the epoch cap (a safety net). Held-out filtered MRR / hits are computed once,
at the end, for the record only: with a few thousand distinct triples they
measure memorisation and are not used for selection (D5.2). Deterministic:
fixed seed, fixed thread count, deterministic algorithms.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch import nn

MODELS = ("complex", "transe")


@dataclass
class TrainConfig:
    model: str = "complex"
    dim: int = 128                 # real dimensions per entity vector
    epochs: int = 60               # safety net; normally stops on the loss plateau
    steps_per_epoch: int = 250
    batch_size: int = 4096
    negatives: int = 4
    sampling_alpha: float = 0.75   # P(triple) ~ count ** alpha (D5.1)
    lr: float = 1e-3
    margin: float = 1.0            # TransE
    reg: float = 1e-5              # ComplEx L2
    valid_fraction: float = 0.05
    plateau_patience: int = 5      # epochs without a relative loss gain > plateau_tol
    plateau_tol: float = 1e-3
    seed: int = 20260925
    threads: int = 4


# ------------------------------------------------------------------ data ---

@dataclass
class TripleData:
    entities: list[str]
    relations: list[str]
    triples: np.ndarray                                  # (n, 3) int64, occurrences
    sha256: str

    @property
    def n_entities(self) -> int:
        return len(self.entities)


def load_triples(path: Path, entities: list[str], relations: list[str]) -> TripleData:
    eid = {e: i for i, e in enumerate(entities)}
    rid = {r: i for i, r in enumerate(relations)}
    rows: list[tuple[int, int, int]] = []
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for raw in fh:
            h.update(raw)
            a, r, b = raw.decode().rstrip("\n").split("\t")
            try:
                rows.append((eid[a], rid[r], eid[b]))
            except KeyError as e:
                raise ValueError(f"{path}: {e.args[0]!r} is not in the trained vocabulary") from None
    return TripleData(entities, relations, np.asarray(rows, dtype=np.int64).reshape(-1, 3),
                      h.hexdigest())


# ---------------------------------------------------------------- models ---

class TransE(nn.Module):
    def __init__(self, n_ent: int, n_rel: int, dim: int):
        super().__init__()
        bound = 6 / math.sqrt(dim)
        self.ent = nn.Parameter(torch.empty(n_ent, dim).uniform_(-bound, bound))
        self.rel = nn.Parameter(torch.empty(n_rel, dim).uniform_(-bound, bound))
        with torch.no_grad():
            self.rel.div_(self.rel.norm(dim=1, keepdim=True))
            self.normalize()

    def normalize(self) -> None:
        with torch.no_grad():
            self.ent.div_(self.ent.norm(dim=1, keepdim=True).clamp_min(1e-12))

    def score(self, h, r, t):                    # higher is better
        return -(self.ent[h] + self.rel[r] - self.ent[t]).abs().sum(-1)

    def score_all_tails(self, h, r):             # (B, N)
        q = self.ent[h] + self.rel[r]
        return -(q[:, None, :] - self.ent[None, :, :]).abs().sum(-1)

    def score_all_heads(self, r, t):
        q = self.ent[t] - self.rel[r]
        return -(self.ent[None, :, :] - q[:, None, :]).abs().sum(-1)

    def loss(self, pos, neg, cfg: TrainConfig):
        return torch.relu(cfg.margin - pos[:, None] + neg).mean()

    def after_step(self) -> None:
        self.normalize()

    def entity_vectors(self) -> torch.Tensor:
        return self.ent.detach()

    def relation_vectors(self) -> torch.Tensor:
        return self.rel.detach()


class ComplEx(nn.Module):
    def __init__(self, n_ent: int, n_rel: int, dim: int):
        super().__init__()
        if dim % 2:
            raise ValueError("ComplEx needs an even dimension (rank = dim / 2)")
        k = dim // 2
        self.ent_re = nn.Parameter(nn.init.xavier_uniform_(torch.empty(n_ent, k)))
        self.ent_im = nn.Parameter(nn.init.xavier_uniform_(torch.empty(n_ent, k)))
        self.rel_re = nn.Parameter(nn.init.xavier_uniform_(torch.empty(n_rel, k)))
        self.rel_im = nn.Parameter(nn.init.xavier_uniform_(torch.empty(n_rel, k)))

    def _q(self, h, r):   # h * r (complex), to be dotted with conj(t)
        hr, hi, rr, ri = self.ent_re[h], self.ent_im[h], self.rel_re[r], self.rel_im[r]
        return hr * rr - hi * ri, hr * ri + hi * rr

    def score(self, h, r, t):
        qr, qi = self._q(h, r)
        return (qr * self.ent_re[t] + qi * self.ent_im[t]).sum(-1)

    def score_all_tails(self, h, r):
        qr, qi = self._q(h, r)
        return qr @ self.ent_re.T + qi @ self.ent_im.T

    def score_all_heads(self, r, t):
        # Re(<h, r, conj(t)>) as a function of h
        tr, ti, rr, ri = self.ent_re[t], self.ent_im[t], self.rel_re[r], self.rel_im[r]
        ar, ai = rr * tr + ri * ti, rr * ti - ri * tr
        return ar @ self.ent_re.T + ai @ self.ent_im.T

    def loss(self, pos, neg, cfg: TrainConfig):
        return nn.functional.softplus(-pos).mean() + nn.functional.softplus(neg).mean()

    def regulariser(self, h, r, t) -> torch.Tensor:
        return sum((p ** 2).sum(-1).mean() for p in (
            self.ent_re[h], self.ent_im[h], self.rel_re[r], self.rel_im[r],
            self.ent_re[t], self.ent_im[t]))

    def after_step(self) -> None:
        pass

    def entity_vectors(self) -> torch.Tensor:
        return torch.cat([self.ent_re, self.ent_im], dim=1).detach()

    def relation_vectors(self) -> torch.Tensor:
        return torch.cat([self.rel_re, self.rel_im], dim=1).detach()


def build_model(cfg: TrainConfig, n_ent: int, n_rel: int) -> nn.Module:
    return {"complex": ComplEx, "transe": TransE}[cfg.model](n_ent, n_rel, cfg.dim)


# ------------------------------------------------------------ evaluation ---

def _ranks(scores: torch.Tensor, target: torch.Tensor, known: torch.Tensor) -> torch.Tensor:
    """Filtered rank of [target] in each row; other true answers are ignored."""
    s_t = scores.gather(1, target[:, None])
    other = known.clone()
    other.scatter_(1, target[:, None], False)
    valid = ~other
    greater = ((scores > s_t) & valid).sum(1).float()
    equal = ((scores == s_t) & valid).sum(1).float() - 1     # excluding the target
    return 1 + greater + equal / 2


@torch.no_grad()
def evaluate(model, triples: torch.Tensor, known: torch.Tensor, batch: int = 2048) -> dict:
    """known: (N, R, N) bool of every true triple."""
    if len(triples) == 0:
        return {"n": 0, "mrr": float("nan"), "hits@1": float("nan"), "hits@10": float("nan")}
    ranks = []
    for i in range(0, len(triples), batch):
        h, r, t = triples[i:i + batch].T
        ranks.append(_ranks(model.score_all_tails(h, r), t, known[h, r, :]))
        ranks.append(_ranks(model.score_all_heads(r, t), h, known[:, r, t].T))
    rk = torch.cat(ranks)
    return {"n": int(len(triples)), "mrr": float((1 / rk).mean()),
            "hits@1": float((rk <= 1).float().mean()),
            "hits@10": float((rk <= 10).float().mean())}


# -------------------------------------------------------------- training ---

@dataclass
class TrainResult:
    cfg: TrainConfig
    entity_vectors: np.ndarray
    relation_vectors: np.ndarray
    metrics: dict
    movement: np.ndarray            # ||final - initial|| / ||initial|| per entity
    history: list[dict] = field(default_factory=list)
    best_epoch: int = 0
    epochs_run: int = 0
    n_train: int = 0
    n_valid: int = 0


def split(data: TripleData, cfg: TrainConfig) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(cfg.seed)
    perm = rng.permutation(len(data.triples))
    n_valid = int(round(cfg.valid_fraction * len(perm)))
    return data.triples[perm[n_valid:]], data.triples[perm[:n_valid]]


def sampling_weights(counts: np.ndarray, alpha: float) -> torch.Tensor:
    w = counts.astype(np.float64) ** alpha
    return torch.from_numpy(w / w.sum())


def train(data: TripleData, cfg: TrainConfig, log=print) -> TrainResult:
    torch.manual_seed(cfg.seed)
    torch.set_num_threads(cfg.threads)
    torch.use_deterministic_algorithms(True)
    n_ent, n_rel = data.n_entities, len(data.relations)
    tr_np, va_np = split(data, cfg)
    distinct, counts = np.unique(tr_np, axis=0, return_counts=True)
    distinct_t = torch.from_numpy(distinct)
    weights = sampling_weights(counts, cfg.sampling_alpha)
    known = torch.zeros(n_ent, n_rel, n_ent, dtype=torch.bool)
    all_t = torch.from_numpy(data.triples)
    known[all_t[:, 0], all_t[:, 1], all_t[:, 2]] = True
    va_distinct = (torch.from_numpy(np.unique(va_np, axis=0)) if len(va_np)
                   else torch.empty(0, 3, dtype=torch.long))
    seen = torch.zeros_like(known)
    seen[distinct_t[:, 0], distinct_t[:, 1], distinct_t[:, 2]] = True
    novel_mask = (~seen[va_distinct[:, 0], va_distinct[:, 1], va_distinct[:, 2]]
                  if len(va_distinct) else torch.zeros(0, dtype=torch.bool))

    model = build_model(cfg, n_ent, n_rel)
    initial = model.entity_vectors().clone()
    opt = torch.optim.Adam(model.parameters(), lr=cfg.lr)
    gen = torch.Generator().manual_seed(cfg.seed)
    history: list[dict] = []
    best_loss, stale, epoch = math.inf, 0, 0
    per_epoch = cfg.steps_per_epoch * cfg.batch_size
    for epoch in range(1, cfg.epochs + 1):
        t0 = time.time()
        idx = torch.multinomial(weights, per_epoch, replacement=True, generator=gen)
        total = 0.0
        for i in range(0, per_epoch, cfg.batch_size):
            h, r, t = distinct_t[idx[i:i + cfg.batch_size]].T
            k = cfg.negatives
            corrupt = torch.randint(0, n_ent, (len(h), k), generator=gen)
            head_side = torch.rand(len(h), k, generator=gen) < 0.5
            nh = torch.where(head_side, corrupt, h[:, None])
            nt = torch.where(head_side, t[:, None], corrupt)
            pos = model.score(h, r, t)
            neg = model.score(nh, r[:, None].expand_as(nh), nt)
            loss = model.loss(pos, neg, cfg)
            if cfg.model == "complex":
                loss = loss + cfg.reg * model.regulariser(h, r, t)
            opt.zero_grad()
            loss.backward()
            opt.step()
            model.after_step()
            total += float(loss.detach())
        mean = total / cfg.steps_per_epoch
        history.append({"epoch": epoch, "loss": mean, "seconds": round(time.time() - t0, 1)})
        log(f"  epoch {epoch:3d}  loss {mean:.5f}  ({history[-1]['seconds']}s)")
        if mean < best_loss * (1 - cfg.plateau_tol):
            best_loss, stale = mean, 0
        else:
            stale += 1
        if stale >= cfg.plateau_patience:
            log(f"  loss plateau: no relative gain > {cfg.plateau_tol} in "
                f"{cfg.plateau_patience} epochs")
            break
    final = model.entity_vectors()
    movement = ((final - initial).norm(dim=1) / initial.norm(dim=1).clamp_min(1e-12)).numpy()
    metrics = {"valid": evaluate(model, va_distinct, known),
               "valid_novel": evaluate(model, va_distinct[novel_mask], known),
               "train_distinct": int(len(distinct)), "final_loss": history[-1]["loss"]}
    return TrainResult(cfg, final.numpy(), model.relation_vectors().numpy(), metrics,
                       movement, history, epoch, epoch, len(tr_np), len(va_np))


# ---------------------------------------------------------------- output ---

def _vecs(names: list[str], m: np.ndarray) -> dict[str, list[float]]:
    return {n: [float(x) for x in row] for n, row in zip(names, m.astype(np.float32))}


def save(result: TrainResult, data: TripleData, level: str, out_dir: Path,
         provenance: dict) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{level}.{result.cfg.model}"
    meta = {
        "level": level, "model": result.cfg.model, "dim": result.cfg.dim,
        "rank": result.cfg.dim // 2 if result.cfg.model == "complex" else None,
        "entity_vector": "concat(real, imag)" if result.cfg.model == "complex" else "real",
        "seed": result.cfg.seed, "threads": result.cfg.threads,
        "hyperparameters": asdict(result.cfg),
        "torch": torch.__version__,
        "triples_sha256": data.sha256,
        "n_train": result.n_train, "n_valid": result.n_valid,
        "sampling_alpha": result.cfg.sampling_alpha,
        "epochs_run": result.epochs_run,
        "metrics": result.metrics, "history": result.history,
        "movement": {n: float(x) for n, x in zip(data.entities, result.movement)},
        **provenance,
    }
    ent_path, rel_path = out_dir / f"{stem}.json", out_dir / f"{stem}.relations.json"
    ent_path.write_text(json.dumps(
        {"metadata": meta, "entities": _vecs(data.entities, result.entity_vectors)}) + "\n")
    rel_path.write_text(json.dumps(
        {"metadata": {"level": level, "model": result.cfg.model,
                      "note": "relation vectors: never used for encoding"},
         "relations": _vecs(data.relations, result.relation_vectors)}) + "\n")
    return ent_path, rel_path


# ------------------------------------------------------ neighbour report ---

PROBES = {
    "lambda": ["Paddint", "Psubint", "Pmulint", "Paddfloat", "Pmulfloat", "Pintcomp",
               "Pfloatcomp", "Pmakeblock", "Pfield", "Lapply_a1", "Lfunction_a1",
               "Lifthenelse", "Pperform", "INT", "FLOAT", "VAR_INT", "CONST_INT"],
    "cmm": ["Caddi", "Csubi", "Cmuli", "Caddf", "Cmulf", "Ccmpi", "Ccmpf", "Capply",
            "Cextcall", "Cload_word_val", "Cstore_word_val", "BR", "JUMP", "RET",
            "INT", "VAL", "VAR_INT", "SYM_FUNC"],
}
EXPECTED_PAIRS = {
    "lambda": [("Paddint", "Psubint"), ("Pmulint", "Pdivint"), ("Paddfloat", "Pmulfloat"),
               ("Paddfloat", "Psubfloat"), ("Pfield", "Psetfield"), ("Lapply_a1", "Lapply_a2")],
    "cmm": [("Caddf", "Cmulf"), ("Caddi", "Csubi"), ("Caddf", "Csubf"),
            ("Cload_word_val", "Cload_word_int"), ("Ccmpi", "Ccmpa"), ("BR", "SWITCH")],
}


def neighbour_report(names: list[str], vecs: np.ndarray, level: str, k: int = 5) -> str:
    v = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)
    sim = v @ v.T
    idx = {n: i for i, n in enumerate(names)}
    lines = [f"nearest neighbours (cosine), {level}"]
    for p in PROBES[level]:
        if p not in idx:
            lines.append(f"  {p:16s} (not in vocabulary)")
            continue
        order = [j for j in np.argsort(-sim[idx[p]], kind="stable") if j != idx[p]][:k]
        lines.append(f"  {p:16s} " + ", ".join(f"{names[j]} {sim[idx[p], j]:.2f}" for j in order))
    lines.append("expected clusters: cosine, and rank of the partner among the probe's neighbours")
    for a, b in EXPECTED_PAIRS[level]:
        if a in idx and b in idx:
            order = [j for j in np.argsort(-sim[idx[a]], kind="stable") if j != idx[a]]
            lines.append(f"  {a} ~ {b}: cos {sim[idx[a], idx[b]]:.2f}, "
                         f"rank {order.index(idx[b]) + 1} / {len(names) - 1}")
        else:
            lines.append(f"  {a} ~ {b}: not both in vocabulary")
    return "\n".join(lines)
