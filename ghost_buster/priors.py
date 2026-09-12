"""The priors view: what this team has decided about each kind of finding,
and how often the decision held.

The case file records decisions (`ghost-triage --casefile`) and the
surgeon's outcomes; the ledger records what each finding did over time.
Read together they answer the question a scanner cannot: not "what is
here" but "what has this team said about things like this, and did the
world agree".

    ghost-buster PATH --priors           the view, per detector
    ghost-buster PATH --priors --json    the same, as data

A decision HELD when the world did what the decision expected:

| decision   | held when                                            | did not hold when |
|------------|------------------------------------------------------|-------------------|
| fix        | the finding is gone and has not returned             | still present, or it came back |
| suppress   | nobody re-decided it                                 | a later decision on the same finding said otherwise |
| document   | nobody re-decided it                                 | a later decision on the same finding said otherwise |

A case that names no finding (recorded before 1.2.0) or whose finding the
ledger has never seen is UNKNOWN, never counted as held. The view is
evidence, not a verdict: a fix that has not landed yet is "open", which is
a fact about time, not about the decision.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .casefile import Casefile
from .ledger import Ledger

HELD = "held"
OPEN = "open"            # a fix not yet reflected in the tree
RETURNED = "returned"    # fixed, then came back
REVISITED = "revisited"  # a later decision on the same finding said otherwise
UNKNOWN = "unknown"      # no finding id, or the ledger has never seen it

@dataclass
class DetectorPriors:
    detector: str
    outcomes: Dict[str, int] = field(default_factory=dict)    # real/false/healed/exposed/broke/declined
    verdicts: Dict[str, int] = field(default_factory=dict)    # held/open/returned/revisited/unknown
    notes: List[str] = field(default_factory=list)            # the most recent reasons, newest first

    @property
    def decided(self) -> int:
        return self.outcomes.get("real", 0) + self.outcomes.get("false", 0)

    @property
    def false_rate(self) -> Optional[float]:
        return self.outcomes.get("false", 0) / self.decided if self.decided else None

    @property
    def hold_rate(self) -> Optional[float]:
        judged = sum(n for k, n in self.verdicts.items() if k != UNKNOWN)
        return self.verdicts.get(HELD, 0) / judged if judged else None

    def to_dict(self) -> dict:
        return {"detector": self.detector, "outcomes": dict(self.outcomes), "verdicts": dict(self.verdicts),
                "decided": self.decided, "false_rate": self.false_rate, "hold_rate": self.hold_rate,
                "notes": list(self.notes)}


def _verdict(case, later_cases, ledger: Optional[Ledger]) -> str:  # ghost_buster: name-disagreement -- `later_cases` is `later` at every call site
    """Did this decision hold? See the module docstring."""
    if not case.finding_id or not case.decision:
        return UNKNOWN
    if any(c.decision and c.decision != case.decision for c in later_cases):
        return REVISITED
    if case.decision in ("suppress", "document"):     # holds until somebody says otherwise
        return HELD
    # a fix: ask the ledger what the finding did afterwards
    hist = (getattr(ledger, "findings", None) or {}).get(case.finding_id) if ledger is not None else None
    if hist is None:
        return UNKNOWN
    if hist.returns and hist.last_seen > case.when:
        return RETURNED
    if hist.last_seen > case.when and not hist.absent_last_run:
        return OPEN
    return HELD if hist.absent_last_run else OPEN


def build(casefile: Casefile, ledger: Optional[Ledger]) -> List[DetectorPriors]:
    by_detector: Dict[str, DetectorPriors] = {}
    by_finding: Dict[str, list] = defaultdict(list)
    for c in casefile.cases:
        if c.finding_id:
            by_finding[c.finding_id].append(c)
    for c in sorted(casefile.cases, key=lambda c: c.when):
        row = by_detector.setdefault(c.detector, DetectorPriors(c.detector))
        row.outcomes[c.outcome] = row.outcomes.get(c.outcome, 0) + 1
        if c.outcome in ("real", "false"):
            later = [o for o in by_finding.get(c.finding_id, []) if o.when > c.when] if c.finding_id else []
            v = _verdict(c, later, ledger)  # ghost_buster: name-disagreement -- `later` is `later_cases` in the signature
            row.verdicts[v] = row.verdicts.get(v, 0) + 1
        if c.note:
            row.notes.insert(0, c.note)
    for row in by_detector.values():
        del row.notes[3:]
    return sorted(by_detector.values(), key=lambda r: (-r.decided, r.detector))


def render(rows: List[DetectorPriors], casefile_path, ledger_path) -> str:
    out = [f"PRIORS  {casefile_path}" + (f"  with {ledger_path}" if ledger_path else "  (no ledger: fixes cannot be judged)")]
    if not rows:
        out.append("  no decisions recorded yet: ghost-triage FINDINGS --casefile records them")
        return "\n".join(out)
    for r in rows:
        fr = "" if r.false_rate is None else f", {r.false_rate:.0%} false"
        hr = "" if r.hold_rate is None else f", {r.hold_rate:.0%} held"
        out.append(f"  {r.detector}: {r.decided} decision(s){fr}{hr}")
        verdicts = ", ".join(f"{n} {k}" for k, n in sorted(r.verdicts.items(), key=lambda kv: -kv[1]))
        ops = ", ".join(f"{n} {k}" for k, n in sorted(r.outcomes.items()) if k not in ("real", "false"))
        if verdicts:
            out.append(f"    decisions: {verdicts}")
        if ops:
            out.append(f"    operations: {ops}")
        for note in r.notes:
            out.append(f"    - {note[:110]}")
    return "\n".join(out)


def to_json(rows: List[DetectorPriors]) -> str:
    return json.dumps([r.to_dict() for r in rows], indent=2)
