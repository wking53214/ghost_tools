"""The proof that Tests/test_secrets.py is not vacuous: break
ghost_buster/secrets.py one way at a time in a scratch copy and run only
that file. Every mutant here must be killed.

Like test_branches.py and test_testsuite.py, `ghost_buster --mutate` finds
no candidate in test_secrets.py -- every assertion is a direct comparison
against a scan result. This suite is the hand-made complement.

Requires gitleaks on PATH, same as test_secrets.py; skipped entirely
otherwise.

One mutant from the exploratory run is deliberately absent: dropping
`--redact` from the gitleaks invocation. Not a real gap -- `_finding()`
never reads gitleaks' `Secret` or `Match` fields at all, redacted or not,
so no black-box test through `scan()`'s public return value can observe
the difference. `--redact` is kept as defense-in-depth against a future
change to `_finding()` ever reading those fields, the same way
branches.py keeps `_is_ancestor` as a cheap fast path without treating it
as load-bearing for its own hand-mutant suite.

The working tree is never modified.
"""
from __future__ import annotations

import shutil

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

pytestmark = pytest.mark.skipif(
    shutil.which("gitleaks") is None,
    reason="gitleaks is not installed; install it to run this mutant suite",
)

SECRETS_TESTS = "Tests/test_secrets.py"
_S = "ghost_buster/secrets.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    ("git-repo precondition check skipped (a non-git directory can read as clean)", _S,
     "    if not _is_git_repo(root):\n        report.reason = f\"{root} is not a git repository\"\n        return [], report\n\n",
     ""),
    ("git-repo check always true (masks a non-git directory)", _S,
     '    return proc.returncode == 0\n', '    return True\n'),
    ("missing gitleaks binary treated as found (would try to exec nothing)", _S,
     "    binary = gitleaks_path or shutil.which(\"gitleaks\")\n    if not binary:\n",
     "    binary = gitleaks_path or shutil.which(\"gitleaks\") or \"true\"\n    if False:\n"),
    ("non-zero gitleaks exit treated as a clean scan", _S,
     "        if proc.returncode != 0:\n", "        if False:\n"),
    ("--exit-code 0 override dropped (a real leak flips this to 'did not run')", _S,
     '            "--redact", "--exit-code", "0",\n', '            "--redact",\n'),
    ("timeout not enforced (a hung gitleaks run hangs the scan)", _S,
     '                cmd, capture_output=True, text=True, errors="replace", timeout=timeout,\n',
     '                cmd, capture_output=True, text=True, errors="replace", timeout=None,\n'),
    ("missing report file treated as zero findings instead of a failure", _S,
     "        if not report_path.exists():\n", "        if False:\n"),
    ("invalid JSON report treated as zero findings instead of a failure", _S,
     "    except ValueError as e:\n        report.reason = f\"gitleaks report was not valid JSON: {e}\"\n"
     "        return [], report\n",
     "    except ValueError:\n        entries = []\n"),
    ("severity hardcoded to something other than CRITICAL", _S,
     "        severity=Severity.CRITICAL,\n", "        severity=Severity.MINOR,\n"),
    ("category hardcoded wrong", _S,
     "        category=Category.COMMITTED_SECRET,\n", "        category=Category.OTHER,\n"),
    ("status hardcoded to something other than CONFIRMED", _S,
     "        status=Status.CONFIRMED,\n", "        status=Status.REJECTED,\n"),
    ("commit sha no longer disambiguates the summary (two exposures of one secret collide)", _S,
     '    summary = f"a \'{rule}\' secret is committed in {location} (commit {commit_short})"\n',
     '    summary = f"a \'{rule}\' secret is committed in {location}"\n'),
    ("column no longer disambiguates the summary (two secrets on one line collide)", _S,
     "    if column is not None:\n        location += f\":{column}\"\n", ""),
    ("leaks_found count not set on a successful scan", _S,
     "    report.leaks_found = len(findings)\n", "    report.leaks_found = 0\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_secrets_scanner_mutant_is_killed(label, rel, old, new):
    assert_killed(label, SECRETS_TESTS, run_tests_with_mutation(SECRETS_TESTS, rel, old, new))


def test_secrets_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        SECRETS_TESTS, _S, 'DETECTOR = "committed_secret"\n', 'DETECTOR = "committed_secret"\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
