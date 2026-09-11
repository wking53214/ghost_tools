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
    no committed secrets         secrets RAN, no CRITICAL committed_secret; a MAJOR
                                 one is a shape-only candidate, reported beside the
                                 verdict and retired by a "false" decision in the
                                 case file, never a failure on its own
    not a drifted copy           no MAJOR drifted_copy
    no swallowed-everything      no MAJOR swallowed_exception
    no hollow contracts          no dead_end_call

WHAT THE RE-EXAMINATION CANNOT SEE, AND SAID SO

A criterion can be read off evidence that predates an intervention. The
re-examination after a cut runs the registered detectors; it does not run
the test suite and does not run the secrets scan, because those execute
the target's code and cost minutes, and a comment-only remedy verified by
syntax-tree identity is not a reason to spend them again. Those criteria
are therefore CARRIED: the verdict stands, and the report says the
evidence is the workup's rather than a second look's. A reader deciding
whether to act on an after-block should know which half of it was
re-established. Before this, "suite ran clean" after a cut read exactly
like "suite ran clean" before one.

WHAT IS NOT MEASURED, AND SAID SO

"Someone depends on it." Whether anything outside this repository imports
it is a cross-repository fact, and a single-repo scan cannot know it. It
is left out rather than guessed, and the full-dose serum -- extraction into
a package other repos consume -- is gated on it separately, by a human,
with the library in view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .ledger import RAN
from .schema import Finding, Severity, authoritative

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
    carried: bool = False        # established before an intervention, not after it

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
            note = "  [carried from the workup, not re-established]" if c.carried else ""
            lines.append(f"  {mark}  {c.name:34s} {c.evidence}{note}")
        if self.unknown:
            lines.append("  unknown counts against the patient: a surgeon does not enhance "
                         "what they could not examine.")
        if self.carried:
            lines.append("  carried means the evidence predates the cut: the re-examination "
                         "does not run these layers, so the verdict is the workup's, not a "
                         "second look's.")
        return "\n".join(lines)

    @property
    def carried(self) -> List[Criterion]:
        return [c for c in self.criteria if c.carried]


def _name_tests(findings: List[Finding], limit: int = 4) -> str:
    """The test ids behind a count. A number sends the reader back to the
    report; a name sends them to the test. The first patient reported
    "2 failing or flaky test(s)" and nothing on the page said which."""
    names = []
    for f in findings:
        nodeid = (f.attributes or {}).get("nodeid") or f.summary
        if nodeid not in names:
            names.append(nodeid)
    shown = ", ".join(names[:limit])
    return shown + (f" (+{len(names) - limit} more)" if len(names) > limit else "")


def _count(findings: Iterable[Finding], detector: str,
           severity: Optional[Severity] = None) -> int:
    return sum(1 for f in findings
               if f.detector == detector and (severity is None or f.severity is severity))


def assess(findings: Iterable[Finding], checks: Dict[str, str],
           retired: Optional[Set[str]] = None,
           carried: Iterable[str] = ()) -> Readiness:
    """Read candidacy off what the scan already found and what it ran.

    `retired` is the set of finding ids the case file holds a "false"
    decision for: a secrets candidate somebody read and found to be a
    fixture, a word, a transcript. It changes what the evidence says, not
    the verdict; only an established credential (CRITICAL) fails the gate.
    """
    # A criterion is a deterministic verdict, so it reads deterministic
    # findings. Today nothing else can reach here; the filter is what makes
    # that a property of this gate rather than of the semantic layer's
    # wiring. See schema.authoritative.
    findings = authoritative(findings)
    retired = retired or set()
    carried = set(carried)
    criteria: List[Criterion] = []

    n = _count(findings, "unassessable_file")
    criteria.append(Criterion(PARSES, n == 0,
                              "every file parsed" if n == 0 else f"{n} file(s) could not be assessed"))

    if checks.get("tests") == RAN:
        bad = [f for f in findings if f.detector == "test_status" and f.severity is Severity.MAJOR]
        n = len(bad)
        criteria.append(Criterion(TESTS, n == 0,
                                  "suite ran clean" if n == 0
                                  else f"{n} failing or flaky test(s): {_name_tests(bad)}"))
    else:
        criteria.append(Criterion(TESTS, None, f"tests {checks.get('tests', 'not run')}; run with --tests"))

    if checks.get("secrets") == RAN:
        established = _count(findings, "committed_secret", Severity.CRITICAL)
        candidates = [f for f in findings
                      if f.detector == "committed_secret" and f.severity is not Severity.CRITICAL]
        unread = [f for f in candidates if f.id not in retired]
        if established:
            evidence = f"{established} credential(s) established"
        elif not candidates:
            evidence = "none found"
        else:
            evidence = (f"none established; {len(unread)} candidate(s) to read"
                        + (f", {len(candidates) - len(unread)} retired as false in the case file"
                           if len(unread) < len(candidates) else ""))
        criteria.append(Criterion(SECRETS, established == 0, evidence))
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

    return Readiness(tuple(
        c if c.name not in carried else Criterion(c.name, c.met, c.evidence, carried=True)
        for c in criteria))
