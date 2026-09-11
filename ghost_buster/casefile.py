"""The surgeon's case file: what every past decision and every cut taught.

THE LOOP THAT WAS OPEN

`ghost-triage` records your decision on every finding -- fix, suppress,
document, with a note. Until now that record flowed one way, forward into
`ghost-writer`, and never back. A finding you had suppressed three times in
three repositories was presented the fourth time with exactly the confidence
it had the first. The detectors had learned nothing, because nothing told
them.

Meanwhile the exclusion lists -- `_NO_OP_WORDS`, `_EMPTY_IS_NORMAL`,
`_ORDINARY_ENGLISH`, `_SHAPE_ONLY_RULES` -- each annotated "measured false
positive; every entry was a false positive first" -- ARE learned cases. They
were learned by one person, once, and frozen in source.

This closes the loop. Dispositions become priors. Operations record their
outcomes. The next scan can say, beside a finding, what happened the last
time this kind of finding came up.

WHAT A PRIOR IS AND IS NOT

A prior is history, attached to a finding as evidence. It NEVER hides a
finding and NEVER changes a severity: a detector that stopped reporting
something because a human suppressed it three times would be a detector
that stopped reporting the fourth time it was real. The finding is shown,
the history is shown beside it, and the human decides with both in view.

What it does change is the order of attention in the report and, later,
the differential: "in this library a hollow `execute` on a plain class has
been a dead end 3 of 3 times" is a better starting point than first
principles.

SHAPE, NOT INSTANCE

A case is keyed by the KIND of finding, not the file it was in: the detector
plus the attributes it recorded (`caught=Exception`, `shape=pass`). Two
findings with the same shape are the same lesson. Attributes that name a
specific instance -- a qualified name, a copy count -- simply make that
shape rarer, and a rare shape falls back to the detector-level prior. That
is conservative in the right direction.

WHERE IT LIVES

Beside the baseline and the ledger by default, `<path>/.ghost_casefile.json`,
because that is where this toolkit keeps what it remembers. Point
`--casefile` at one shared file to let the surgeon learn across the whole
library, which is what a surgeon does.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .schema import Finding

# What a human decision teaches. `document` is a real finding somebody chose
# to explain rather than fix; it is still real.
_DISPOSITION_OUTCOME = {"fix": "real", "suppress": "false", "document": "real"}

# What an operation teaches.
HEALED = "healed"        # remedy applied, patient better, nothing exposed
EXPOSED = "exposed"      # remedy applied and it revealed more (the spread)
BROKE = "broke"          # remedy applied and something failed; reverted
DECLINED = "declined"    # remedy offered, human said no

OUTCOMES = ("real", "false", HEALED, EXPOSED, BROKE, DECLINED)


@dataclass(frozen=True)
class Case:
    detector: str
    shape: str
    outcome: str
    note: str = ""
    when: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class Prior:
    """What the case file knows about a kind of finding."""

    detector: str
    shape: Optional[str]
    counts: Dict[str, int]

    @property
    def seen(self) -> int:
        return sum(self.counts.values())

    @property
    def false_rate(self) -> Optional[float]:
        decided = self.counts.get("real", 0) + self.counts.get("false", 0)
        return self.counts.get("false", 0) / decided if decided else None

    def render(self) -> str:
        if not self.seen:
            return "no history"
        parts = [f"{n} {k}" for k, n in sorted(self.counts.items(), key=lambda kv: -kv[1])]
        scope = "this shape" if self.shape else "this detector"
        return f"history for {scope}: " + ", ".join(parts)


def shape_of(finding: Finding) -> str:
    """The kind of finding, independent of where it was found."""
    attrs = "&".join(f"{k}={v}" for k, v in sorted(finding.attributes.items()))
    return f"{finding.detector}|{attrs}" if attrs else finding.detector


class Casefile:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.cases: List[Case] = []
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.cases = [Case(**c) for c in data.get("cases", [])]

    # ----------------------------------------------------------- learning

    def record_dispositions(self, findings: Iterable[Finding]) -> int:
        """Every dispositioned finding becomes a case. Returns how many."""
        added = 0
        for f in findings:
            outcome = _DISPOSITION_OUTCOME.get(f.disposition or "")
            if outcome is None:
                continue
            self.cases.append(Case(f.detector, shape_of(f), outcome, f.disposition_note))
            added += 1
        return added

    def record_outcome(self, finding: Finding, outcome: str, note: str = "") -> None:
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}; expected one of {OUTCOMES}")
        self.cases.append(Case(finding.detector, shape_of(finding), outcome, note))

    def save(self) -> None:
        self.path.write_text(json.dumps(
            {"cases": [asdict(c) for c in self.cases]}, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------- priors

    def prior(self, detector: str, shape: Optional[str] = None) -> Prior:
        """The shape's history if it has any, else the detector's.

        A shape nobody has seen falls back to the detector: rare shapes are
        conservative, not silent."""
        if shape is not None:
            matching = [c for c in self.cases if c.shape == shape]
            if matching:
                return Prior(detector, shape, dict(Counter(c.outcome for c in matching)))
        matching = [c for c in self.cases if c.detector == detector]
        return Prior(detector, None, dict(Counter(c.outcome for c in matching)))

    def annotate(self, findings: Iterable[Finding]) -> Dict[str, Prior]:
        """finding id -> the prior that applies to it. Nothing is hidden."""
        return {f.id: self.prior(f.detector, shape_of(f)) for f in findings}

    def __len__(self) -> int:
        return len(self.cases)
