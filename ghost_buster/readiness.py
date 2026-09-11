"""Whether the patient is a candidate for the serum.

THE RULE THIS ENCODES

Enhancement applied to an unhealthy codebase amplifies what is there,
including the rot. Make an untested module faster and you have made it
faster at being wrong. Extract a package from a drifted copy and you have
canonised the drift. Erskine did not hand out the serum; he selected.

So candidacy is gated on health, health is measured, and the gate fails
CLOSED: a criterion the scan could not assess counts against the patient,
not for it. A surgeon does not enhance a patient they could not image.
That is the whole design, and it is why "run with --tests" is an answer
this module gives rather than a limitation it apologises for.

WHAT IS MEASURED

Every criterion is read off findings the scan already produced and the
record of which checks ran. Nothing here re-derives anything.

    parses completely            no unassessable_file
    tests run and pass           tests RAN, no MAJOR test_status
    no committed secrets         secrets RAN, no committed_secret
    not a drifted copy           no MAJOR drifted_copy
    no swallowed-everything      no MAJOR swallowed_exception
    no hollow contracts          no dead_end_call

WHAT IS NOT MEASURED, AND SAID SO

"Someone depends on it." Whether anything outside this repository imports
it is a cross-repository fact, and a single-repo scan cannot know it. It
is left out rather than guessed, and the full-dose serum -- extraction into
a package other repos consume -- is gated on it separately, by a human,
with the library in view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .ledger import RAN
from .schema import Finding, Severity

# Criteria, in the order a surgeon would check them: can I see the patient,
# is anything bleeding, then the structural conditions.
PARSES = "parses completely"
TESTS = "tests run and pass"
SECRETS = "no committed secrets"
COPIES = "not a drifted copy"
SWALLOWED = "no swallowed-everything handlers"
HOLLOW = "no hollow contracts"


@dataclass(frozen=True)
class Criterion:
    name: str
    met: Optional[bool]          # None: the scan could not assess this
    evidence: str

    @property
    def unknown(self) -> bool:
        return self.met is None


@dataclass(frozen=True)
class Readiness:
    criteria: Tuple[Criterion, ...]

    @property
    def candidate(self) -> bool:
        """All criteria met. Unknown is not met: the gate fails closed."""
        return all(c.met is True for c in self.criteria)

    @property
    def failing(self) -> List[Criterion]:
        return [c for c in self.criteria if c.met is False]

    @property
    def unknown(self) -> List[Criterion]:
        return [c for c in self.criteria if c.met is None]

    def render(self) -> str:
        lines = ["serum candidacy: " + ("CANDIDATE" if self.candidate else "not a candidate")]
        for c in self.criteria:
            mark = {True: "met    ", False: "FAILING", None: "unknown"}[c.met]
            lines.append(f"  {mark}  {c.name:34s} {c.evidence}")
        if self.unknown:
            lines.append("  unknown counts against the patient: a surgeon does not enhance "
                         "what they could not examine.")
        return "\n".join(lines)


def _count(findings: Iterable[Finding], detector: str,
           severity: Optional[Severity] = None) -> int:
    return sum(1 for f in findings
               if f.detector == detector and (severity is None or f.severity is severity))


def assess(findings: Iterable[Finding], checks: Dict[str, str]) -> Readiness:
    """Read candidacy off what the scan already found and what it ran."""
    findings = list(findings)
    criteria: List[Criterion] = []

    n = _count(findings, "unassessable_file")
    criteria.append(Criterion(PARSES, n == 0,
                              "every file parsed" if n == 0 else f"{n} file(s) could not be assessed"))

    if checks.get("tests") == RAN:
        n = _count(findings, "test_status", Severity.MAJOR)
        criteria.append(Criterion(TESTS, n == 0,
                                  "suite ran clean" if n == 0 else f"{n} failing or flaky test(s)"))
    else:
        criteria.append(Criterion(TESTS, None, f"tests {checks.get('tests', 'not run')}; run with --tests"))

    if checks.get("secrets") == RAN:
        n = _count(findings, "committed_secret")
        criteria.append(Criterion(SECRETS, n == 0,
                                  "none found" if n == 0 else f"{n} committed secret(s)"))
    else:
        criteria.append(Criterion(SECRETS, None, f"secrets {checks.get('secrets', 'not run')}; run with --secrets"))

    n = _count(findings, "drifted_copy", Severity.MAJOR)
    criteria.append(Criterion(COPIES, n == 0,
                              "no copies disagree" if n == 0 else f"{n} group(s) of copies disagree"))

    n = _count(findings, "swallowed_exception", Severity.MAJOR)
    criteria.append(Criterion(SWALLOWED, n == 0,
                              "none" if n == 0 else f"{n} handler(s) catch everything and do nothing"))

    n = _count(findings, "dead_end_call")
    criteria.append(Criterion(HOLLOW, n == 0,
                              "none" if n == 0 else f"{n} called body(ies) that do nothing"))

    return Readiness(tuple(criteria))
