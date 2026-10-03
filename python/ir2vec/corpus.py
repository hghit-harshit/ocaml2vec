"""The extracted corpus: $IR2VEC_CORPUS_DIR/json/<pkg>/<Unit>.<md5>.<level>.json.

Package order is the manifest's (= corpus/packages.txt order); units within a
package are sorted by file name, so every traversal is deterministic. Unless
`raw`, only the units in $CORPUS/selection.json (the per-package cap, D4.4)
are visible, and training commands refuse to run without it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


def default_dir() -> Path:
    return Path(os.environ.get("IR2VEC_CORPUS_DIR", Path.home() / "ir2vec-corpus"))


@dataclass
class Corpus:
    root: Path
    raw: bool = False
    _selected: dict[str, set[str]] | None = field(default=None, init=False, repr=False)

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.tsv"

    @property
    def selection_path(self) -> Path:
        return self.root / "selection.json"

    def selection(self) -> dict:
        if not self.selection_path.exists():
            raise FileNotFoundError(
                f"{self.selection_path}: no corpus selection; run `ir2vec select` first")
        return json.loads(self.selection_path.read_text())

    def _selected_stems(self, package: str) -> set[str] | None:
        if self.raw:
            return None
        if self._selected is None:
            self._selected = {p: set(v["selected"])
                              for p, v in self.selection()["packages"].items()}
        return self._selected.get(package, set())

    def packages(self) -> list[str]:
        """Successfully built packages, in manifest order."""
        with self.manifest.open(newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        return [r["package"] for r in rows if r["status"] == "ok"]

    def stems(self, package: str) -> list[str]:
        """All units of a package (both levels must be present)."""
        d = self.root / "json" / package
        lam = {p.name[: -len(".lambda.json")] for p in d.glob("*.lambda.json")}
        cmm = {p.name[: -len(".cmm.json")] for p in d.glob("*.cmm.json")}
        if lam != cmm:
            raise ValueError(f"{package}: units without both levels: {sorted(lam ^ cmm)[:5]}")
        return sorted(lam)

    def unit_files(self, level: str, package: str) -> list[Path]:
        files = sorted((self.root / "json" / package).glob(f"*.{level}.json"))
        keep = self._selected_stems(package)
        if keep is None:
            return files
        return [f for f in files if f.name[: -len(f".{level}.json")] in keep]

    def units_of(self, level: str, package: str) -> Iterator[dict]:
        for path in self.unit_files(level, package):
            yield json.loads(path.read_text())

    def units(self, level: str) -> Iterator[tuple[str, dict]]:
        for pkg in self.packages():
            for unit in self.units_of(level, pkg):
                yield pkg, unit

    def sha256(self) -> str:
        """Hash of every visible file (both levels), in traversal order."""
        h = hashlib.sha256()
        for pkg in self.packages():
            for level in ("lambda", "cmm"):
                for path in self.unit_files(level, pkg):
                    h.update(f"{pkg}/{path.name}\0".encode())
                    h.update(hashlib.sha256(path.read_bytes()).digest())
        return h.hexdigest()


@dataclass(frozen=True)
class FileCorpus:
    """A corpus given as explicit unit files (tests, single programs)."""
    files: dict[str, list[Path]]   # package -> unit JSON files (any level)

    def packages(self) -> list[str]:
        return list(self.files)

    def units_of(self, level: str, package: str) -> Iterator[dict]:
        for path in sorted(p for p in self.files[package] if p.name.endswith(f".{level}.json")):
            yield json.loads(path.read_text())

    def units(self, level: str) -> Iterator[tuple[str, dict]]:
        for pkg in self.files:
            for unit in self.units_of(level, pkg):
                yield pkg, unit

    def sha256(self) -> str:
        h = hashlib.sha256()
        for pkg, paths in self.files.items():
            for path in sorted(paths):
                h.update(f"{pkg}/{path.name}\0".encode())
                h.update(hashlib.sha256(path.read_bytes()).digest())
        return h.hexdigest()
