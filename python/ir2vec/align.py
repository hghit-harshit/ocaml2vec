"""Lambda <-> Cmm function alignment (schema §3; BUILD_SPEC Phase 6).

Per compilation unit:
  1. module_init  <-> the Cmm function `<prefix>.entry` (5.5.1 uses '.', and
     -for-pack units prefix the pack path: `camlPack.Unit.entry`; D2.12);
  2. named        <-> the Cmm function whose trailing `_<stamp>` is the
     Lambda identifier's stamp (stamps are compared *between the two levels
     of one compilation*, never against literal values; D1.6);
  3. anonymous    <-> the unmatched Cmm function with exactly the same source
     location (Cmm fun_dbg comes from the same Lambda location);
  4. fallback     <-> the unmatched Cmm function whose parameter stamps
     include all of the Lambda function's (closures add an env parameter).
Steps 3-4 also serve as fallbacks for named functions whose stamp is absent.
An ambiguous candidate set is never guessed: the function stays unmatched.
Unmatched functions are reported by category: named, anonymous, module_init
(Lambda-only), and cmm_only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_STAMPED = re.compile(r"^(?P<base>.+)_(?P<stamp>\d+)$")


def cmm_local(name: str) -> str:
    """The function's own name: symbol names never contain '.' otherwise."""
    return name.rsplit(".", 1)[-1]


def cmm_stamp(name: str) -> int | None:
    m = _STAMPED.match(cmm_local(name))
    return int(m.group("stamp")) if m else None


def cmm_param_stamps(fn: dict) -> set[int]:
    out = set()
    for p in fn["params"]:
        _, _, s = p["var"].rpartition("/")
        if s.isdigit():
            out.add(int(s))
    return out


@dataclass(frozen=True)
class Match:
    fid: str
    cmm: str
    by: str          # entry | stamp | location | params


@dataclass
class Alignment:
    unit: str
    matches: list[Match] = field(default_factory=list)
    unmatched_lambda: dict[str, list[str]] = field(
        default_factory=lambda: {"named": [], "anonymous": [], "module_init": []})
    cmm_only: list[str] = field(default_factory=list)

    @property
    def n_lambda(self) -> int:
        return len(self.matches) + sum(len(v) for v in self.unmatched_lambda.values())

    def to_json(self) -> dict:
        return {"unit": self.unit, "matched": len(self.matches),
                "by": {k: sum(m.by == k for m in self.matches)
                       for k in ("entry", "stamp", "location", "params")},
                "unmatched_lambda": self.unmatched_lambda, "cmm_only": self.cmm_only}


def cmm_parents(cmm: dict) -> dict[str, str | None]:
    """For each Cmm function, the unique *other* function whose code refers to
    its symbol (a closure's allocator, an *_inner function's wrapper), or None
    when there is no such referrer (e.g. a static closure in data) or several.
    A consumer may fold Cmm-only rows into their parents; the encoder does not
    (D7.1)."""
    refs: dict[str, set[str]] = {f["name"]: set() for f in cmm["functions"]}
    for f in cmm["functions"]:
        for b in f["blocks"]:
            for i in b["instrs"]:
                for o in i["operands"]:
                    s = o.get("sym")
                    if s in refs and s != f["name"]:
                        refs[s].add(f["name"])
    return {n: (next(iter(r)) if len(r) == 1 else None) for n, r in refs.items()}


def align(lam: dict, cmm: dict | None) -> Alignment:
    a = Alignment(lam["unit"])
    fns = list(cmm["functions"]) if cmm else []
    free = {f["name"]: f for f in fns}
    by_stamp: dict[int, list[str]] = {}
    for f in fns:
        s = cmm_stamp(f["name"])
        if s is not None:
            by_stamp.setdefault(s, []).append(f["name"])

    def take(fid: str, name: str, by: str) -> None:
        a.matches.append(Match(fid, name, by))
        del free[name]

    def by_location(rec: dict) -> str | None:
        if not rec["loc"]:
            return None
        cands = [n for n, f in free.items() if f["loc"] == rec["loc"]]
        return cands[0] if len(cands) == 1 else None

    def by_params(rec: dict) -> str | None:
        want = {p["stamp"] for p in rec["params"]}
        if not want:
            return None
        cands = [n for n, f in free.items() if want <= cmm_param_stamps(f)]
        return cands[0] if len(cands) == 1 else None

    pending = []
    for rec in lam["functions"]:
        if rec["kind"] == "module_init":
            entry = [n for n in free if cmm_local(n) == "entry"]
            if len(entry) == 1:
                take(rec["fid"], entry[0], "entry")
            else:
                a.unmatched_lambda["module_init"].append(rec["fid"])
        elif rec["kind"] == "named":
            cands = [n for n in by_stamp.get(rec["stamp"], []) if n in free]
            if len(cands) == 1:
                take(rec["fid"], cands[0], "stamp")
            else:
                pending.append(rec)
        else:
            pending.append(rec)
    # location first for everything left, then parameter stamps
    rest = []
    for rec in pending:
        n = by_location(rec)
        if n:
            take(rec["fid"], n, "location")
        else:
            rest.append(rec)
    for rec in rest:
        n = by_params(rec)
        if n:
            take(rec["fid"], n, "params")
        else:
            a.unmatched_lambda["named" if rec["kind"] == "named" else "anonymous"].append(rec["fid"])
    a.cmm_only = sorted(free)
    return a
