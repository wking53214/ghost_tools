"""What a digest chain over the records can prove, and what it cannot.

THE HONEST CLAIM

The baseline, the case file and the ledger are three files in the
repository, and any of them can be edited by anyone who can edit the
repository. That is not a defect: the baseline is a suppression policy the
user is supposed to change, and the case file is where a human writes down
a decision. But it means a later reader cannot tell whether the record
they are holding is the record the tool wrote.

This module narrows that gap by exactly one step, and no further.

Each run records, inside the ledger:

  * a digest of the baseline and of the case file AS THEY WERE READ, so a
    later edit to either is visible as a disagreement with the run that
    used them, and
  * a digest of the previous run record, so the run history is a chain:
    altering or removing an old run breaks every link after it.

WHAT THAT PROVES

That the records are internally consistent with each other, and that a
silent edit to a past run, a past baseline or a past decision is
detectable by re-reading the chain. `verify()` reports the first break.

WHAT IT DOES NOT PROVE

Anything at all against someone who can write the ledger. There are no
signatures and no key, so an editor who changes a record can recompute the
chain from that point forward and the result verifies. A hash chain
detects accident and casual edit; it does not withstand an adversary with
write access, and nothing in this file should be read as claiming it does.

Getting the stronger property means signing the chain head with a key the
repository does not hold, which is a decision about key custody rather
than a line of code, and it is not made here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

#: What a missing file hashes to, so "no baseline" is a state the chain
#: records rather than a gap it cannot describe.
ABSENT = "absent"


def digest(data: object) -> str:
    """A stable digest of a JSON-shaped value. Keys are sorted, so a record
    that is rewritten by a different json writer still matches."""
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def digest_file(path: Optional[Path]) -> str:
    """The digest of a record on disk, by its content rather than its
    bytes: a reformatted baseline is the same baseline."""
    if path is None or not Path(path).is_file():
        return ABSENT
    try:
        return digest(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        # Unreadable or not JSON. That is a fact about the record, and
        # hashing the raw bytes keeps it in the chain instead of dropping it.
        try:
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
        except OSError:
            return ABSENT


def link(previous: str, run: dict) -> str:
    """This run's place in the chain: its own content, bound to the link
    before it. Removing a run in the middle breaks every link after."""
    body = {k: v for k, v in run.items() if k != "link"}
    return digest({"previous": previous, "run": body})


@dataclass(frozen=True)
class Break:
    """Where the chain stops agreeing with itself."""
    run_index: int
    run_id: str
    what: str

    def render(self) -> str:
        return f"run {self.run_index} ({self.run_id}): {self.what}"


def verify(runs: List[dict]) -> List[Break]:
    """Every link, recomputed. An empty list means the chain is intact for
    the runs that carry one; runs written before this existed have no link
    and are reported as unchained rather than as broken, because they are
    not evidence of tampering, only of age."""
    breaks: List[Break] = []
    previous = ""
    for i, run in enumerate(runs):
        recorded = run.get("link")
        if not recorded:
            breaks.append(Break(i, str(run.get("run_id", "")), "no link recorded (written before 1.5.0)"))
            previous = link(previous, run)
            continue
        expected = link(previous, run)
        if recorded != expected:
            breaks.append(Break(i, str(run.get("run_id", "")),
                                f"link {recorded} does not match {expected} recomputed from this run "
                                "and the one before it"))
        previous = recorded
    return breaks


def render(breaks: List[Break], total: int) -> str:
    if not total:
        return "ghost_buster: chain: no runs to verify"
    unchained = [b for b in breaks if "no link recorded" in b.what]
    broken = [b for b in breaks if b not in unchained]
    if not breaks:
        return f"ghost_buster: chain: {total} run(s), every link verified"
    lines = [f"ghost_buster: chain: {total} run(s), {len(broken)} broken link(s), "
             f"{len(unchained)} run(s) written before the chain existed"]
    for b in broken[:5]:
        lines.append("  " + b.render())
    if broken:
        lines.append("  a broken link means the record was edited after it was written. "
                     "It does not say by whom, and an editor who recomputes the chain "
                     "leaves none: this detects edits, not adversaries.")
    return "\n".join(lines)
