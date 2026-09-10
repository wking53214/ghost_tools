"""The proof that Tests/test_correlate.py is not vacuous: break
ghost_buster/correlate.py one way at a time in a scratch copy and run only
that file. Every mutant here must be killed.

A correlation is a claim about two other findings, so the failure that
matters most is not "it crashed" but "it fired when it shouldn't" or
"stayed quiet when it should have fired" -- a connector that silently
never matches looks exactly like a repository with nothing to correlate.
Most mutants below are that shape: loosen a join, drop a guard, and see
whether any test notices.

One mutant from the exploratory run is deliberately absent: deleting the
`if not secrets or not duplicates: return []` early-out in
`secret_in_duplicated_file`. Not a real gap -- with it gone the loops
below it iterate empty lists and produce exactly nothing, so no test
through the module's public contract can tell the two versions apart. It
is a cost guard, not a correctness one, and is documented here rather
than propped up with a test that would only be asserting its own setup.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

CORRELATE_TESTS = "Tests/test_correlate.py"
_C = "ghost_buster/correlate.py"
_S = "ghost_buster/schema.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- the join itself ---
    ("file join loosened to a shared suffix (a file matches its own vendored copy)", _C,
     "    return _portable(a) == _portable(b)\n",
     "    pa, pb = PurePath(_portable(a)).parts, PurePath(_portable(b)).parts\n"
     "    n = min(len(pa), len(pb))\n"
     "    return bool(n) and pa[-n:] == pb[-n:]\n"),
    ("file join loosened to basename only", _C,
     "    return _portable(a) == _portable(b)\n",
     "    return PurePath(a).name == PurePath(b).name\n"),
    ("related_files no longer made portable (breaks every within-run join)", _S,
     "        self.evidence.related_files = [\n"
     "            _portable_path(p) for p in self.evidence.related_files\n"
     "        ]\n",
     ""),

    # --- eligibility rules ---
    ("REASONED findings become eligible for correlation", _C,
     "        if f.status == Status.CONFIRMED and f.detector not in _REGISTRY\n",
     "        if f.detector not in _REGISTRY\n"),
    ("correlations fed back into connectors (correlations of correlations)", _C,
     "        if f.status == Status.CONFIRMED and f.detector not in _REGISTRY\n",
     "        if f.status == Status.CONFIRMED\n"),
    ("eligibility filter bypassed entirely", _C,
     "        findings=eligible_findings(findings),\n", "        findings=list(findings),\n"),

    # --- secret_in_duplicated_file ---
    ("the leaked file is counted as one of its own copies", _C,
     "            others = [c for c in copies if not _same_file(secret.evidence.file, c)]\n",
     "            others = list(copies)\n"),
    ("secret/duplicate severity downgraded from CRITICAL", _C,
     '                severity=Severity.CRITICAL,\n'
     '                status=Status.CONFIRMED,\n'
     '                summary=(\n'
     '                    f"the \'{rule}\' secret in {secret.evidence.file} is also in "\n',
     '                severity=Severity.MINOR,\n'
     '                status=Status.CONFIRMED,\n'
     '                summary=(\n'
     '                    f"the \'{rule}\' secret in {secret.evidence.file} is also in "\n'),

    # --- secret_in_multiple_repositories ---
    ("cross-repo connector matches any secret, not the same fingerprint", _C,
     '                if other.attributes.get("fingerprint", "") == fingerprint:\n',
     "                if True:\n"),
    ("cross-repo connector guesses when a fingerprint is missing", _C,
     '        fingerprint = secret.attributes.get("fingerprint", "")\n'
     "        if not fingerprint:\n            continue\n",
     '        fingerprint = secret.attributes.get("fingerprint", "")\n'),
    ("cross-repo connector counts one repository many times", _C,
     "                    elsewhere.append((prior.label, other))\n                    break\n",
     "                    elsewhere.append((prior.label, other))\n"),

    # --- conflict_marker_breaks_tests ---
    ("conflict marker attributed to tests in other files", _C,
     "            if _same_file(marker.evidence.file, t.evidence.file)\n",
     "            if True\n"),
    ("conflict marker attributed to skipped tests", _C,
     '            and t.attributes.get("kind") in ("failing test", "blocked test")\n',
     "            and True\n"),

    # --- doc_count_contradicted_by_run ---
    ("connector stops re-checking the claim shape (recommends overwriting a delta)", _C,
     '        shape = claim_shape(drift.attributes.get("claim_context", ""))\n'
     "        if shape is not None:\n            continue\n",
     ""),
    ("connector re-checks the wrong attribute (re-check becomes a no-op)", _C,
     '        shape = claim_shape(drift.attributes.get("claim_context", ""))\n',
     '        shape = claim_shape(drift.attributes.get("no_such_key", ""))\n'),
    ("doc/run connector fires without a --tests run", _C,
     '    if report is None or not getattr(report, "ran", False):\n        return []\n', ""),
    ("doc/run connector reports the static bound instead of the measured count", _C,
     '    collected = int(getattr(report, "collected", 0) or 0)\n',
     '    collected = int(getattr(report, "static_lower_bound", 0) or 0)\n'),
    ("a suite with failures still reads as MINOR doc drift", _C,
     "            severity=Severity.MINOR if not_passing == 0 else Severity.MAJOR,\n",
     "            severity=Severity.MINOR,\n"),

    # --- provenance and plumbing ---
    ("correlations stop naming the findings they were built from", _C,
     '                    f"Built from findings: {_ids([secret, dup])}."\n', '                    ""\n'),
    ("a bad --correlate-with path silently yields an empty prior run", _C,
     '        raise ValueError(f"{p}: {type(e).__name__}: {e}") from e\n',
     "        return PriorRun(label=p.stem, findings=[])\n"),
    ("a non-finding-set JSON file silently yields an empty prior run", _C,
     '        raise ValueError(f"{p}: not a ghost_buster --json finding set ({e})") from e\n',
     "        return PriorRun(label=p.stem, findings=[])\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_correlate_mutant_is_killed(label, rel, old, new):
    assert_killed(label, CORRELATE_TESTS, run_tests_with_mutation(CORRELATE_TESTS, rel, old, new))


def test_correlate_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        CORRELATE_TESTS, _C, 'ConnectorFn = Callable[["CorrelationInput"], List[Finding]]\n',
        'ConnectorFn = Callable[["CorrelationInput"], List[Finding]]\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
