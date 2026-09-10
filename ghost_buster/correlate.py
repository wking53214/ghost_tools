"""correlate.py -- connectors: findings that only exist when two
detectors are read together.

WHAT THIS IS FOR
------------------
Every detector in this project is deliberately independent: mechanical.py
parses files, branches.py reads the ref graph, testsuite.py runs pytest,
secrets.py scans history. None of them knows what the others found. That
independence is right -- it is what makes each one testable and each
finding traceable to exactly one cause -- but it leaves a class of problem
that no single detector can see, because the evidence for it is split
across two of them:

- `committed_secret` knows a key leaked. `duplicate_file` knows that file
  exists in three places. Neither knows the leak has to be remediated in
  three places.
- `merge_conflict_marker` knows a file is syntactically broken.
  `test_status` knows forty tests cannot be collected. Neither says the
  one marker is why the forty tests are red.
- `doc_test_count_drift` knows a README claims 353 tests and can only
  ever compute a static lower bound -- its own detail says "confirm by
  running the real suite". `--tests` ran the real suite. Neither closes
  the loop alone.

A connector is a function over the findings a run already produced. It
does no new parsing, runs no new subprocess, and reads no new files: if
the inputs are not there (a check was not enabled, a detector found
nothing) the connector simply produces nothing.

CORRELATIONS ARE ADDITIVE, ON PURPOSE
----------------------------------------
A correlation does not replace or suppress the findings it joins. A secret
in a duplicated file stays one `committed_secret` and one
`duplicate_file`, plus one correlation. That is deliberate: the inputs are
each independently true and independently actionable, and collapsing them
would hide one behind the other. What the correlation adds is the thing
neither input can state -- blast radius, root cause, or a verified number.

Every correlation names its input findings by id in `detail`, so a reader
can always get back to the two independent facts it was built from.

WHY THEY JOIN ON ATTRIBUTES, NOT ON PROSE
--------------------------------------------
`summary` and `detail` are written for humans and get reworded. Joining on
them would mean regex-parsing English, and a wording change in one
detector would silently switch a connector off -- failing quiet, which is
the failure mode this whole project treats as worse than crashing. So
findings publish machine-readable join keys in `Finding.attributes` (see
schema.py) and connectors read only those, plus `evidence.file`, which is
already a portable project-relative path for every detector.

WHAT DOES NOT GET CORRELATED
-------------------------------
- **Semantic (REASONED) findings.** Correlating a deterministic fact with
  an unverified LLM claim would produce something that is neither, and the
  schema is explicit that a mechanical-layer finding cannot be REASONED.
  Only `Status.CONFIRMED` findings are eligible. When the semantic layer
  is wired into the CLI, connectors over it need their own status rule,
  written then rather than guessed at now.
- **Correlations themselves.** Connectors run once, over detector output
  only. A correlation of correlations compounds every assumption in both
  and is unreadable when it fires; nothing here does it.

WHAT A CONNECTOR CANNOT SEE
------------------------------
A connector is only as complete as the run it reads. `--tests` and
`--secrets` are opt-in and off by default, so most connectors here are
silent on a default scan -- that is honest (no input, no claim), but it
means "no correlations" never implies "nothing to correlate". The
per-connector docstrings name the specific joins each one cannot make.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .schema import Category, Evidence, Finding, Layer, Severity, Status

ConnectorFn = Callable[["CorrelationInput"], List[Finding]]

_REGISTRY: Dict[str, ConnectorFn] = {}


def connector(name: str):
    """Same registry shape as mechanical.py's `register`, for the same
    reason: connectors are independent and order-independent, and adding
    one must not require editing a dispatch table."""
    def decorator(fn: ConnectorFn) -> ConnectorFn:
        _REGISTRY[name] = fn
        return fn
    return decorator


def registered_connectors() -> Dict[str, ConnectorFn]:
    return dict(_REGISTRY)


@dataclass
class PriorRun:
    """One other repository's findings, read from a `--json` dump of a
    previous scan. `label` is how that repository is named back to the
    reader -- the file's stem, unless the caller knows better."""

    label: str
    findings: List[Finding] = field(default_factory=list)


@dataclass
class CorrelationInput:
    """Everything a connector may read. Deliberately a closed set: a
    connector that needs something not in here needs a detector, not a
    correlation."""

    findings: List[Finding] = field(default_factory=list)
    prior_runs: List[PriorRun] = field(default_factory=list)
    # testsuite.TestStatusReport when --tests ran, else None. Typed loosely
    # so correlate.py does not import testsuite.py just for an annotation.
    test_report: object = None

    def by_detector(self, name: str) -> List[Finding]:
        return [f for f in self.findings if f.detector == name]


def _portable(path: str) -> str:
    """Separator-normalized form of a path a finding carries."""
    return PurePath(path).as_posix()


def _same_file(a: str, b: str) -> bool:
    """True when two paths from the same run name the same file.

    Exact comparison, deliberately. Every path a finding carries --
    `evidence.file` and every entry in `evidence.related_files` -- is put
    through `_portable_path` by `Finding.__post_init__`, so within one run
    they are all project-relative and directly comparable. An earlier
    version matched on a shared path suffix instead, to paper over
    `related_files` still holding absolute paths, and that version happily
    matched `certs/key.pem` against `vendor/certs/key.pem` -- reporting a
    file's own vendored copy as itself, which is exactly backwards for a
    connector whose whole job is counting copies. The fix belonged
    upstream, in the schema, not in a looser comparison here.
    """
    return _portable(a) == _portable(b)


def _ids(findings: Sequence[Finding]) -> str:
    """Provenance ids, de-duplicated. Two repositories carrying the same
    vendored leak produce findings with the same id by construction (same
    detector, same project-relative path, same summary), so listing them
    raw printed one id twice and read like a bug rather than like the
    signal it is."""
    seen: List[str] = []
    for f in findings:
        if f.id not in seen:
            seen.append(f.id)
    return ", ".join(seen)


# ---------------------------------------------------------------------------
# Connector: secret_in_duplicated_file
# ---------------------------------------------------------------------------

@connector("secret_in_duplicated_file")
def correlate_secret_in_duplicated_file(data: CorrelationInput) -> List[Finding]:
    """A committed secret sitting in a file that has byte-identical twins.

    `committed_secret` reports one leak, at one path. `duplicate_file`
    reports that path is one of N identical copies. Read together: the
    credential is in every copy, and purging history in one place leaves it
    live in the others -- which is exactly the state a repository lands in
    when a module (or a whole vendored directory) is copied between
    projects.

    Blind spot, stated plainly: `duplicate_file` looks at files on disk
    now, while `committed_secret` looks at history. A secret whose file was
    later deleted, or whose copies have since diverged by one byte, has no
    duplicate_file finding to join against and will not correlate here even
    though the copies' histories both still carry it. This connector finds
    the still-duplicated case, not every case.
    """
    secrets = data.by_detector("committed_secret")
    duplicates = data.by_detector("duplicate_file")
    if not secrets or not duplicates:
        return []

    out: List[Finding] = []
    for secret in secrets:
        for dup in duplicates:
            copies = [dup.evidence.file, *dup.evidence.related_files]
            if not any(_same_file(secret.evidence.file, c) for c in copies):
                continue
            others = [c for c in copies if not _same_file(secret.evidence.file, c)]
            rule = secret.attributes.get("rule", "unknown-rule")
            out.append(Finding(
                detector="secret_in_duplicated_file",
                category=Category.COMMITTED_SECRET,
                layer=Layer.MECHANICAL,
                severity=Severity.CRITICAL,
                status=Status.CONFIRMED,
                summary=(
                    f"the '{rule}' secret in {secret.evidence.file} is also in "
                    f"{len(others)} byte-identical cop{'y' if len(others) == 1 else 'ies'}: "
                    + ", ".join(_portable(o) for o in others)
                ),
                detail=(
                    "Neither detector can see this alone: the secrets scan reports one "
                    "leak at one path, and the duplication scan reports that path has "
                    "identical twins. Together they say the credential is present in "
                    f"{len(others) + 1} files, so rotating it and purging one file's "
                    "history leaves it readable in the rest. Rotate once, then purge "
                    "every copy listed here.\n"
                    f"Built from findings: {_ids([secret, dup])}."
                ),
                attributes={
                    "secret_finding": secret.id,
                    "duplicate_finding": dup.id,
                    "copies": str(len(others) + 1),
                    "content_sha256": dup.attributes.get("content_sha256", ""),
                },
                evidence=Evidence(
                    file=secret.evidence.absolute_file or secret.evidence.file,
                    line_start=secret.evidence.line_start,
                    line_end=secret.evidence.line_end,
                    related_files=list(others),
                ),
            ))
    return out


# ---------------------------------------------------------------------------
# Connector: secret_in_multiple_repositories
# ---------------------------------------------------------------------------

@connector("secret_in_multiple_repositories")
def correlate_secret_across_repositories(data: CorrelationInput) -> List[Finding]:
    """The same leak, by gitleaks' own fingerprint, in more than one
    repository.

    A scan is scoped to one directory, so two repositories that both carry
    a leaked key are two separate runs producing two unrelated CRITICALs,
    with nothing saying they are the same key. That is not hypothetical:
    measured across this ecosystem, a committed TLS private key appeared in
    both `sentinel_os` and a second repository that vendors a copy of it,
    at the same path and the same commit.

    The join key is gitleaks' `Fingerprint` (commit:file:rule:line), which
    is identical across repositories that share the commit -- a fork, a
    vendored checkout, or a directory copied with its history. Two
    repositories that arrived at the same secret independently (retyped,
    different commit) do NOT share a fingerprint and are deliberately not
    joined: this connector claims "the same leak, copied", and a
    coincidental match of secret *values* is a claim it cannot make, since
    the value never reaches a finding.

    Requires `--correlate-with` pointing at another repository's `--json`
    output; silent otherwise.
    """
    if not data.prior_runs:
        return []
    secrets = data.by_detector("committed_secret")
    if not secrets:
        return []

    out: List[Finding] = []
    for secret in secrets:
        fingerprint = secret.attributes.get("fingerprint", "")
        if not fingerprint:
            continue
        elsewhere: List[Tuple[str, Finding]] = []
        for prior in data.prior_runs:
            for other in prior.findings:
                if other.detector != "committed_secret":
                    continue
                # Same default on both sides. With one side defaulting to
                # None and the other to "", two findings that both lack a
                # fingerprint could never collide -- which quietly made the
                # empty-key guard above unreachable rather than unnecessary.
                if other.attributes.get("fingerprint", "") == fingerprint:
                    elsewhere.append((prior.label, other))
                    break
        if not elsewhere:
            continue
        labels = ", ".join(label for label, _ in elsewhere)
        out.append(Finding(
            detector="secret_in_multiple_repositories",
            category=Category.COMMITTED_SECRET,
            layer=Layer.MECHANICAL,
            severity=Severity.CRITICAL,
            status=Status.CONFIRMED,
            summary=(
                f"the '{secret.attributes.get('rule', 'unknown-rule')}' secret in "
                f"{secret.evidence.file} is the same leak as one in: {labels}"
            ),
            detail=(
                "Matched on gitleaks' own fingerprint (commit:file:rule:line), so this "
                "is the same commit carrying the same secret in more than one "
                "repository -- a fork, a vendored copy, or a directory copied with its "
                "history. A single-repository scan cannot see this: each repository "
                "reports its own leak with nothing to say they are one credential. "
                "Rotate once; purge history in every repository listed, or the "
                "rotation is the only thing that happened.\n"
                f"Fingerprint: {fingerprint}\n"
                f"Built from findings: {_ids([secret] + [f for _, f in elsewhere])}."
            ),
            attributes={
                "fingerprint": fingerprint,
                "repositories": str(len(elsewhere) + 1),
                "also_in": labels,
            },
            evidence=Evidence(
                file=secret.evidence.absolute_file or secret.evidence.file,
                line_start=secret.evidence.line_start,
                line_end=secret.evidence.line_end,
            ),
        ))
    return out


# ---------------------------------------------------------------------------
# Connector: conflict_marker_breaks_tests
# ---------------------------------------------------------------------------

@connector("conflict_marker_breaks_tests")
def correlate_conflict_marker_breaks_tests(data: CorrelationInput) -> List[Finding]:
    """An unresolved conflict marker in the same file as tests that could
    not run.

    A `<<<<<<<` triplet in a .py file is a syntax error, so pytest cannot
    import that module and every test in it reports as a collection error
    or a failure. Read separately, that is one MAJOR marker finding and N
    test findings that look like N independent broken tests. Read together,
    it is one line to fix and N tests that come back.

    Only same-file attribution is attempted. A marker in a module that
    *other* test files import would break those too, and this connector
    will not claim that: proving it needs an import graph, and a
    correlation that guesses at causation is worse than one that stays
    quiet. What it reports is the case where the broken file and the
    unrunnable tests are literally the same file.
    """
    markers = data.by_detector("merge_conflict_marker")
    tests = data.by_detector("test_status")
    if not markers or not tests:
        return []

    out: List[Finding] = []
    for marker in markers:
        blocked = [
            t for t in tests
            if _same_file(marker.evidence.file, t.evidence.file)
            and t.attributes.get("kind") in ("failing test", "blocked test")
        ]
        if not blocked:
            continue
        collection = [t for t in blocked if t.attributes.get("phase") == "collect"]
        out.append(Finding(
            detector="conflict_marker_breaks_tests",
            category=Category.MERGE_CONFLICT_MARKER,
            layer=Layer.MECHANICAL,
            severity=Severity.CRITICAL,
            status=Status.CONFIRMED,
            summary=(
                f"the unresolved conflict marker in {marker.evidence.file}"
                f":{marker.evidence.line_start} is why {len(blocked)} test"
                f"{'' if len(blocked) == 1 else 's'} cannot run"
            ),
            detail=(
                "Neither detector can see this alone: the marker scan reports broken "
                "syntax, the test scan reports tests that did not pass, and nothing "
                "connects them. The same file carries both, so these test results are "
                "one symptom, not "
                f"{len(blocked)} independent problems"
                + (f" ({len(collection)} of them could not even be collected)"
                   if collection else "")
                + ". Resolve the marker and re-run before triaging any of them.\n"
                f"Built from findings: {_ids([marker] + blocked)}."
            ),
            attributes={
                "marker_finding": marker.id,
                "blocked_tests": str(len(blocked)),
                "collection_errors": str(len(collection)),
            },
            evidence=Evidence(
                file=marker.evidence.absolute_file or marker.evidence.file,
                line_start=marker.evidence.line_start,
                line_end=marker.evidence.line_end,
                related_files=[t.attributes.get("nodeid", t.evidence.file) for t in blocked],
            ),
        ))
    return out


# ---------------------------------------------------------------------------
# Connector: doc_count_contradicted_by_run
# ---------------------------------------------------------------------------

@connector("doc_count_contradicted_by_run")
def correlate_doc_count_against_run(data: CorrelationInput) -> List[Finding]:
    """A documented test count, checked against the suite actually running.

    `doc_test_count_drift` counts `test_*` functions in the AST and says so
    itself: that is a lower bound, never the collected count, and its own
    detail ends "confirm by running the real suite and update the claim."
    When `--tests` ran, the real numbers are right there -- collected,
    passed, failed, skipped -- and the correlation closes the loop the
    static detector explicitly leaves open, with the exact number a human
    would otherwise have to go and measure before editing the doc.

    It also catches what the static count structurally cannot: a
    documented number can be *right* while the claim around it is wrong,
    because a test that is collected is not a test that passes. A README
    saying "429 tests" next to a suite where 40 of them fail is accurate
    arithmetic and a misleading sentence.

    Silent unless `--tests` ran; a static count alone is not something to
    contradict.
    """
    report = data.test_report
    if report is None or not getattr(report, "ran", False):
        return []
    drifts = data.by_detector("doc_test_count_drift")
    if not drifts:
        return []

    collected = int(getattr(report, "collected", 0) or 0)
    passed = int(getattr(report, "passed", 0) or 0)
    not_passing = collected - passed

    out: List[Finding] = []
    for drift in drifts:
        documented = drift.attributes.get("documented_count", "")
        static = drift.attributes.get("static_lower_bound", "")
        if not documented:
            continue
        out.append(Finding(
            detector="doc_count_contradicted_by_run",
            category=Category.DOC_DRIFT,
            layer=Layer.MECHANICAL,
            severity=Severity.MINOR if not_passing == 0 else Severity.MAJOR,
            status=Status.CONFIRMED,
            summary=(
                f"'{drift.evidence.file}' claims {documented} test(s); the suite "
                f"actually collects {collected} and {passed} pass"
                + ("" if not_passing == 0 else f" ({not_passing} do not)")
            ),
            detail=(
                "The static count is a lower bound and says so; this is the measured "
                f"number from the run that just happened. Write {collected} into the "
                "doc, not the static bound of "
                f"{static or 'the AST scan'}."
                + ("" if not_passing == 0 else
                   f" Note also that {not_passing} collected test(s) did not pass, so a "
                   "sentence claiming this suite is green is wrong independently of the "
                   "number.")
                + f"\nBuilt from findings: {_ids([drift])} plus the --tests run."
            ),
            attributes={
                "drift_finding": drift.id,
                "documented_count": documented,
                "collected": str(collected),
                "passed": str(passed),
            },
            evidence=Evidence(
                file=drift.evidence.absolute_file or drift.evidence.file,
                line_start=drift.evidence.line_start,
                line_end=drift.evidence.line_end,
            ),
        ))
    return out


# ---------------------------------------------------------------------------

def eligible_findings(findings: Sequence[Finding]) -> List[Finding]:
    """The findings a connector is allowed to read: deterministic ones a
    detector produced. Excludes anything a connector itself produced (no
    correlations of correlations) and anything not `Status.CONFIRMED` (no
    joining a fact to an unverified claim). Both rules are in the module
    docstring; this is where they are enforced."""
    return [
        f for f in findings
        if f.status == Status.CONFIRMED and f.detector not in _REGISTRY
    ]


def run_connectors(findings: Sequence[Finding], *, prior_runs: Optional[List[PriorRun]] = None,
                   test_report: object = None) -> List[Finding]:
    """Run every registered connector over one scan's findings.

    Only `Status.CONFIRMED` findings are eligible, and correlations are
    never fed back in (see the module docstring). Returns the new
    correlation findings only -- the caller appends them; nothing here
    mutates or removes an input.
    """
    data = CorrelationInput(
        findings=eligible_findings(findings),
        prior_runs=list(prior_runs or []),
        test_report=test_report,
    )
    out: List[Finding] = []
    for _name, fn in registered_connectors().items():
        out.extend(fn(data))
    return out


def load_prior_run(path) -> PriorRun:
    """Read a `--json` dump from another repository's scan into a PriorRun.

    Accepts either `path` or `label=path`. Without a label the file's stem
    is used, which is only as good as the filename -- a dump called
    `sentinel_os_findings.json` reports as "sentinel_os_findings", so the
    explicit form exists for the common case of naming the repository
    rather than the file.

    Raises ValueError with the offending path on anything unreadable, so a
    typo in `--correlate-with` is a usage error rather than a silently
    empty correlation."""
    from pathlib import Path

    from .schema import FindingSet

    label = ""
    text_path = str(path)
    if "=" in text_path:
        candidate_label, _, candidate_path = text_path.partition("=")
        # Only treat it as a label when what follows is a plausible path;
        # a bare Windows drive letter or an `=` inside a filename is not.
        if candidate_label and candidate_path:
            label, text_path = candidate_label, candidate_path
    p = Path(text_path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"{p}: {type(e).__name__}: {e}") from e
    try:
        findings = list(FindingSet.from_json(text))
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{p}: not a ghost_buster --json finding set ({e})") from e
    return PriorRun(label=label or p.stem, findings=findings)


def render_report(correlations: Sequence[Finding]) -> str:
    if not correlations:
        return "ghost_buster: correlation found nothing to connect"
    by_detector: Dict[str, int] = {}
    for f in correlations:
        by_detector[f.detector] = by_detector.get(f.detector, 0) + 1
    parts = ", ".join(f"{n} {name}" for name, n in sorted(by_detector.items()))
    return f"ghost_buster: correlation connected {len(correlations)} finding(s): {parts}"
