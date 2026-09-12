"""schema.py -- the one finding shape every detector (mechanical or
semantic) produces, and every downstream consumer (baseline diffing,
ghost_writer) reads.

WHY ONE SHARED SCHEMA
-----------------------
This is the design decision that keeps ghost_buster from becoming two
unrelated tools wearing one name. Layer 1 (mechanical, this module's
sibling `mechanical.py`) and Layer 2 (semantic, `semantic.py`, backed by
a real Claude API call) produce wildly different KINDS of findings --
but every one of them is still "here is a specific claim, here is the
evidence, here is how sure we are, here is what it would take to check
again." That shape is Finding, below.

STATUS VOCABULARY -- reused deliberately, not reinvented
-----------------------------------------------------------
This is the exact execution-status discipline proven out over dozens of
findings against HERALD earlier: never claim more confidence than was
actually earned. A mechanical detector's output is CONFIRMED the moment
it runs -- it's deterministic code touching real files, there's nothing
to doubt. A semantic (LLM-backed) detector's output is NEVER CONFIRMED
on its own; it starts at REASONED (a plausible claim, unverified) and
only becomes CONFIRMED once a human (or a second, independent check)
verifies it. This distinction is load-bearing, not decorative: it's what
stops ghost_buster from inheriting the exact "hallucinated, unreviewed,
non-deterministic AI output" failure mode it exists to catch elsewhere.

WHY ATTRIBUTES EXIST
----------------------
`summary` and `detail` are written for a human. `attributes` is the same
finding's facts written for a machine: the gitleaks fingerprint behind a
committed_secret, the content hash behind a duplicate_file, the pytest
node id behind a test_status. correlate.py joins findings from different
detectors on these keys.

Without them, cross-detector correlation means regex-parsing prose that
exists to be readable, and every wording change silently breaks a
correlation. Attributes are deliberately NOT part of the finding id --
adding a key to an existing detector must not renumber a committed
baseline -- and they are free-form `str -> str` per detector rather than a
fixed schema, because what identifies a duplicate file has nothing in
common with what identifies a flaky test.

SEVERITY IS SEPARATE FROM STATUS
-----------------------------------
Severity (how bad, if true) and status (how sure we are it's true) are
orthogonal. A CONFIRMED dead-code finding can be INFORMATIONAL (an
unused private helper, harmless). A REASONED semantic finding can be
CRITICAL (two implementations of the same governor, one silently unused)
even before anyone's confirmed it. Collapsing these into one axis is how
a report ends up either crying wolf constantly or burying the one
finding that matters -- exactly the "noise drowns signal" failure this
tool is designed not to repeat.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Any, Dict, List, Optional


class Severity(str, Enum):
    CRITICAL = "critical"          # actively misleading or dangerous if acted on
    MAJOR = "major"                # real maintainability/correctness risk
    MINOR = "minor"                # real but low-consequence
    INFORMATIONAL = "informational"  # worth knowing, not worth prioritizing


class Status(str, Enum):
    """How sure ghost_buster is that this finding is real. See module
    docstring -- this is intentionally the same discipline as the HULK
    campaign's status vocabulary, narrowed to what ghost_buster actually
    needs."""

    CONFIRMED = "confirmed"                  # deterministic detector; not in doubt
    REASONED = "reasoned"                    # semantic/LLM claim; not yet verified
    CONFIRMED_BY_REVIEW = "confirmed_by_review"  # a REASONED finding a human verified
    REJECTED = "rejected"                    # a human looked and said no
    SUPPRESSED = "suppressed"                # known, accepted, tracked -- not re-surfaced


class Category(str, Enum):
    """Maps directly onto the researched taxonomy. Kept as an enum (not
    a free string) so the detector registry and the baseline file can't
    silently drift into inconsistent category names across detectors."""

    DUPLICATION = "duplication"
    DEAD_CODE = "dead_code"
    COMPLEXITY = "complexity"
    STALE_FLAG = "stale_flag"
    PARALLEL_IMPLEMENTATION = "parallel_implementation"
    DOC_DRIFT = "doc_drift"
    ARCHITECTURE = "architecture"
    VACUOUS_CHECK = "vacuous_check"    # a test that passes with the thing it names broken
    UNMERGED_BRANCH = "unmerged_branch"  # commits git's own graph says aren't on the base branch
    MERGE_CONFLICT_MARKER = "merge_conflict_marker"  # an unresolved <<<<<<< / ======= / >>>>>>> triplet
    TEST_STATUS = "test_status"  # a test that failed, flaked, is blocked, or is skipped without cause
    COMMITTED_SECRET = "committed_secret"  # a live-looking credential gitleaks found in git history
    HISTORY = "history"  # what the ledger knows and a single run cannot: regressions, rot, blind spots
    # A name that describes where the code came from rather than what it
    # does: domain vocabulary surviving below a domain seam, or a
    # placeholder that outlived the afternoon it was written in.
    NAMING = "naming"
    OTHER = "other"


class Layer(str, Enum):
    MECHANICAL = "mechanical"
    SEMANTIC = "semantic"


def _stable_id(*parts: str) -> str:
    """A finding's ID is a content hash of what identifies it (detector
    name + file + the specific thing found) -- NOT a counter. A counter
    renumbers every run depending on what order detectors happen to
    execute in, which breaks baseline diffing (finding #47 today is not
    finding #47 tomorrow just because an earlier detector found one more
    thing). A content-hash ID is the same across runs for the same
    underlying finding, and changes only when the finding itself changes
    -- which is exactly the property baseline diffing needs."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"ghost-{digest[:12]}"


def _portable_path(path: str) -> str:
    """The part of a path that identifies a file inside its project.

    The ID hashed the ABSOLUTE path, which made every committed baseline
    inert. Measured across this ecosystem: 17 of 18 `.ghost_baseline.json`
    files had been generated against temporary clones under a scratchpad
    directory, so not one of their 1,287 entries could match the same
    finding scanned at its real location. Every run reported 100% of
    findings as new, which is the same as having no baseline while looking
    like a repo that had been triaged.

    A baseline is committed to a repository and read back on other machines,
    in CI, and from clones at other paths. Anything in the ID that varies
    with where the checkout happens to sit is a defect in the ID.

    So: cut at the project root when one is recognisable (a VCS or packaging
    marker), else fall back to the last two segments, which is stable enough
    to distinguish files and short enough not to carry a home directory.
    """
    from pathlib import PurePath

    pure = PurePath(path)
    # A path that is already relative is already portable: it was cut at
    # the project root when the finding was made and stored that way. The
    # first version of this function recomputed from the stored path and,
    # because the marker walk needs the file to exist, a baseline read on
    # another machine fell through to the two-segment fallback and matched
    # nothing (measured 2026-09-08: 137 of 137 entries inert).
    if not pure.is_absolute():
        return pure.as_posix()
    parts = pure.parts
    for marker in (".git", "pyproject.toml", "setup.py", "setup.cfg"):
        root = _project_root(path, marker)
        if root is not None:
            try:
                return pure.relative_to(root).as_posix()
            except ValueError:
                pass
    return PurePath(*parts[-2:]).as_posix() if len(parts) >= 2 else path


def _project_root(path: str, marker: str):
    """Nearest ancestor directory containing `marker`, or None."""
    from pathlib import Path

    current = Path(path).parent
    for candidate in (current, *current.parents):
        if (candidate / marker).exists():
            return candidate
    return None


@dataclass
class Evidence:
    """Where a finding points, precisely enough that a human can go
    look without re-deriving what the detector already knows.

    `file` is project-relative (see _portable_path); `absolute_file` is the
    path on the machine that made the finding, for the human report, and is
    not part of the finding's identity."""

    file: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    snippet: Optional[str] = None
    related_files: List[str] = field(default_factory=list)
    absolute_file: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Finding:
    """One ghost. Produced by exactly one detector, identified by a
    stable content-hash ID, carrying enough evidence that a human (or
    ghost_writer, downstream) never has to re-run the detector to
    understand what it found.
    """

    detector: str
    category: Category
    layer: Layer
    severity: Severity
    status: Status
    summary: str
    evidence: Evidence
    detail: str = ""
    # Machine-readable join keys, for correlate.py -- see WHY ATTRIBUTES
    # EXIST in the module docstring. Never part of the id.
    attributes: Dict[str, str] = field(default_factory=dict)
    confidence: Optional[float] = None  # 0.0-1.0, semantic layer only; None for mechanical
    first_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    disposition: Optional[str] = None  # set by the human triage step, see triage.py
    disposition_note: str = ""
    #: What identifies this finding, when the summary does not (v1.7.3).
    #:
    #: A MEASUREMENT IS NOT AN IDENTITY.
    #:
    #: The id is a content hash of detector + path + summary, and several
    #: summaries carry a number the run just measured. The defect does not
    #: change when the number does, but the id does, so a baseline cannot
    #: match the finding twice and "accept this" silently means "accept it
    #: until the next commit".
    #:
    #: Measured against 1.7.2 by an adversarial harness: adding three tests
    #: to a suite, with the documented claim untouched, gave three findings
    #: three new identities --
    #:
    #:     no_ci_configuration            "1 test file(s)" -> "2 test file(s)"
    #:     doc_count_contradicted_by_run  "collects 30"    -> "collects 33"
    #:     doc_test_count_drift           "at least 30"    -> "at least 33"
    #:
    #: Stripping digits from every summary is not the fix. Two dead-code
    #: findings for `core_0` and `core_1` in one file differ only in a
    #: digit, and collapsing those to one identity means accepting one
    #: suppresses the other -- the same failure pointing the other way, and
    #: the worse direction.
    #:
    #: So the DETECTOR says what identifies its finding, because only the
    #: detector knows which part of its own sentence is the defect and
    #: which part is this morning's arithmetic. Left None, the summary is
    #: used exactly as before.
    identity_key: Optional[str] = None
    id: str = field(init=False)

    def __post_init__(self):
        # Store the portable path, not the absolute one, so the baseline
        # carries what the id was computed from and reads back identically
        # from any checkout. The absolute path is kept for the human report.
        portable = _portable_path(self.evidence.file)
        if portable != self.evidence.file:
            self.evidence.absolute_file = self.evidence.file
            self.evidence.file = portable
        # related_files gets the same treatment as file. It used to be
        # written straight from the scan's absolute paths, which made a
        # committed baseline carry a home directory and made two findings
        # about the same file impossible to join (correlate.py needs to
        # match a leaked path against the paths of its byte-identical
        # twins, and "certs/key.pem" does not equal
        # "/home/someone/proj/certs/key.pem").
        self.evidence.related_files = [
            _portable_path(p) for p in self.evidence.related_files
        ]
        self.id = _stable_id(self.detector, portable,
                             self.summary if self.identity_key is None
                             else self.identity_key)
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be 0.0-1.0, got {self.confidence}")
        if self.layer == Layer.MECHANICAL and self.status == Status.REASONED:
            raise ValueError(
                f"{self.detector}: a mechanical-layer finding cannot have "
                "status REASONED -- mechanical detectors are deterministic; "
                "the finding is either present (CONFIRMED) or it wasn't "
                "produced at all. REASONED is reserved for the semantic layer."
            )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "detector": self.detector,
            "category": self.category.value,
            "layer": self.layer.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "summary": self.summary,
            "detail": self.detail,
            "attributes": dict(self.attributes),
            "evidence": self.evidence.as_dict(),
            "confidence": self.confidence,
            "first_seen": self.first_seen,
            "disposition": self.disposition,
            "disposition_note": self.disposition_note,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Finding":
        ev = payload["evidence"]
        finding = cls(
            detector=payload["detector"],
            category=Category(payload["category"]),
            layer=Layer(payload["layer"]),
            severity=Severity(payload["severity"]),
            status=Status(payload["status"]),
            summary=payload["summary"],
            detail=payload.get("detail", ""),
            attributes=dict(payload.get("attributes", {})),
            evidence=Evidence(
                file=ev["file"], line_start=ev.get("line_start"),
                line_end=ev.get("line_end"), snippet=ev.get("snippet"),
                related_files=ev.get("related_files", []),
            ),
            confidence=payload.get("confidence"),
            first_seen=payload.get("first_seen", datetime.now(timezone.utc).isoformat()),
            disposition=payload.get("disposition"),
            disposition_note=payload.get("disposition_note", ""),
        )
        # A RECORDED id wins over a recomputed one. __post_init__ derives the
        # id from the portable path, which is right when a finding is being
        # made -- and wrong when one is being read back, because the id in the
        # file IS the identity. Recomputing it silently re-identifies a
        # finding that was already accepted.
        #
        # It only bites a baseline written before the path in the id was made
        # portable, which stored an ABSOLUTE path. _portable_path needs the
        # file to exist to find the project root, and that path points into a
        # scratch directory that no longer does, so it falls back to the last
        # two segments and lands somewhere the current scan never produces.
        #
        # Measured 2026-09-10 on a committed baseline of 879 entries: 304 were
        # re-identified on load, and 90 findings the author had explicitly
        # accepted came back as new. A baseline that resurfaces what it was
        # told to suppress is worse than no baseline, because the author
        # already spent the decision.
        recorded = payload.get("id")
        if recorded:
            finding.id = recorded
        return finding


class FindingSet:
    """A run's worth of findings, with the JSON round-trip ghost_writer
    and the baseline mechanism both depend on."""

    def __init__(self, findings: Optional[List[Finding]] = None):
        self.findings: List[Finding] = list(findings or [])

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def by_status(self, status: Status) -> List[Finding]:
        return [f for f in self.findings if f.status == status]

    def by_severity(self, severity: Severity) -> List[Finding]:
        return [f for f in self.findings if f.severity == severity]

    def to_json(self) -> str:
        return json.dumps([f.as_dict() for f in self.findings], indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "FindingSet":
        payload = json.loads(text)
        return cls([Finding.from_dict(p) for p in payload])

    def __len__(self) -> int:
        return len(self.findings)

    def __iter__(self):
        return iter(self.findings)


#: The statuses a deterministic decision may rest on. A REASONED finding is
#: a model's claim that no detector verified, and CONFIRMED_BY_REVIEW is one
#: a human did; the first is interpretation, the second is evidence.
AUTHORITATIVE = frozenset({Status.CONFIRMED, Status.CONFIRMED_BY_REVIEW, Status.SUPPRESSED})


#: Detectors whose findings are computed FROM other findings rather than
#: from the tree: a correlation joins two findings, a ledger finding is a
#: fact about a finding's history, a trajectory finding is a fact about a
#: series of runs. Registered here rather than inferred, so adding one is a
#: decision somebody makes on purpose.
#: Kept here rather than imported from the three modules that produce
#: them, because schema.py is what they all import and a cycle would be a
#: worse answer than a list. Tests/test_primary_and_derived.py compares
#: this set against the live registries on every run, so it cannot go
#: stale quietly -- the first draft of it was wrong in both directions.
DERIVED_DETECTORS = frozenset({
    # correlate.py's connectors: a statement about two findings
    "secret_in_duplicated_file", "doc_count_contradicted_by_run",
    "conflict_marker_breaks_tests", "secret_in_multiple_repositories",
    # ledger.py and trajectory.py: a statement about a finding's history
    # or about a series of runs
    "ledger", "trajectory",
})


def is_derived(finding: Finding) -> bool:
    return finding.detector in DERIVED_DETECTORS


def primary(findings: Iterable[Finding]) -> List[Finding]:
    """The findings a measurement of the TREE may rest on.

    WHY THE DISTINCTION IS LOAD-BEARING

    A correlation is a true statement, and it is a statement about two
    findings rather than about a line of code. Counting it beside its own
    inputs counts the same defect twice, and the trajectory series is
    findings per file: add a connector and density rises with no change to
    the code at all, which the series would read as deterioration.

    So the tree's measurements are counted separately from the statements
    made about them. Both are reported; only the first is a denominator.
    """
    return [f for f in findings if not is_derived(f)]


def derived(findings: Iterable[Finding]) -> List[Finding]:
    return [f for f in findings if is_derived(f)]


def authoritative(findings: Iterable[Finding]) -> List[Finding]:
    """The findings a gate, a baseline or the ledger may read.

    WHY THIS EXISTS BEFORE IT IS NEEDED

    The semantic layer is a library with no caller and no flag, so nothing
    REASONED reaches a decision today. That is an absence, not a boundary:
    every consumer downstream filters by detector name or by nothing at
    all, and `FindingHistory` has no status field, so a model's claim
    folded into the ledger would be indistinguishable from a measurement
    afterwards. The day the layer is wired, the boundary has to already be
    code rather than a sentence in a docstring, because by then the wiring
    is the interesting part and this is the part nobody re-reads.

    correlate.py has enforced the same rule for its own inputs since it
    shipped; this is that rule, named once, for the rest of the pipeline.
    """
    return [f for f in findings if f.status in AUTHORITATIVE]


def disambiguate_ids(findings: List[Finding]) -> int:
    """Give every finding its own id, and say how many needed help.

    THE DEFECT THIS CLOSES

    A finding's id hashes three things: detector, project-relative path and
    summary. Two findings that agree on all three therefore share an id,
    and two distinct defects CAN agree on all three -- two same-named
    methods of the same length in one file, two stale counts in one
    document, two secrets four lines apart in one test fixture. Measured on
    a 38-repository library: 3,292 findings, 8 colliding pairs, one of them
    two separate committed secrets. A collision is not cosmetic. The
    baseline keys on the id, so accepting one of the pair suppresses the
    other; the ledger keys on it, so two findings are remembered as one;
    the case file records a decision against one id, so a human judgement
    about one defect silently disposes of another nobody read.

    WHY NOT PUT THE LINE IN THE ID

    Because the id must survive code motion. A finding that moves down a
    file when an import is added is the same finding, and an id that
    changed on every edit would report the whole file as new findings and
    orphan every baseline entry. That property is measured and tested
    (Tests/test_ghost_buster.py, Tests/test_branches.py) and is worth more
    than the collision costs.

    WHAT THIS DOES INSTEAD

    Every member of a colliding group takes a suffix derived from its OWN
    place: `ghost-<hash>-<6 hex of where it is>`. Findings that do not
    collide are untouched, which is all of them in the ordinary case.

    WHY THE SUFFIX IS NOT AN ORDINAL

    1.3.0 numbered them 1, 2, 3 by position, and an external reviewer put
    the obvious question: insert a fourth occurrence above the others and
    every id below it shifts, so a finding's identity depended on how many
    siblings preceded it. That is the churn the whole scheme exists to
    avoid, moved rather than removed.

    A suffix computed from the finding's own line range and detail depends
    on nothing but itself. Insert a sibling, fix a sibling, reorder the
    scan: the other members keep their ids. The remaining sensitivity is
    the honest one -- a colliding finding that MOVES changes identity,
    because where it is was the only thing distinguishing it from its
    twin in the first place.

    The cost, stated plainly: a colliding finding already in a baseline is
    renumbered once by this change, because the 1.3.0 ordinal ids are not
    reproducible. Eight pairs in a 38-repository library; re-accept them.
    """
    by_id: Dict[str, List[Finding]] = {}
    for f in findings:
        by_id.setdefault(f.id, []).append(f)
    renamed = 0
    for base, group in by_id.items():
        if len(group) < 2:
            continue
        # Identical findings (same place, same detail) are one finding
        # reported twice, not two findings; they keep the shared id.
        def place(f: Finding):
            return (f.evidence.file, f.evidence.line_start or 0,
                    f.evidence.line_end or 0, f.detail)
        distinct = {place(f) for f in group}
        if len(distinct) < 2:
            continue
        for f in group:
            where = "|".join(str(part) for part in place(f))
            f.id = f"{base}-{hashlib.sha256(where.encode('utf-8')).hexdigest()[:6]}"
            renamed += 1
    return renamed
