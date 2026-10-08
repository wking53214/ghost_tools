"""The proof that Tests/test_secret_severity.py is not vacuous.

Each mutant restores a version of the rating that was live before
2026-09-10, when every gitleaks hit was CRITICAL regardless of what its
rule had established. The report still listed the same findings, so
nothing looked broken -- the only casualty was the reader's attention,
which is the resource a security check actually spends.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

SEVERITY_TESTS = "Tests/test_secret_severity.py"
_S = "ghost_buster/secrets.py"
_C = "ghost_buster/correlate.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    ("no rule counts as shape-only, so everything is CRITICAL again", _S,
     '_SHAPE_ONLY_RULES = frozenset({"curl-auth-header", "generic-api-key"})',
     "_SHAPE_ONLY_RULES = frozenset()"),
    ("the severity stops depending on the rule", _S,
     "        severity=Severity.MAJOR if rule in _SHAPE_ONLY_RULES else Severity.CRITICAL,\n",
     "        severity=Severity.CRITICAL,\n"),
    ("a shape-only match is downgraded silently, with no warning to verify", _S,
     '    if rule in _SHAPE_ONLY_RULES:\n        detail_lines.append(\n',
     "    if False:\n        detail_lines.append(\n"),
    ("every rule is treated as shape-only, so a real leaked token is MAJOR", _S,
     "        severity=Severity.MAJOR if rule in _SHAPE_ONLY_RULES else Severity.CRITICAL,\n",
     "        severity=Severity.MAJOR,\n"),
    # The 2026-09-10 fix as it was FIRST written: it covered the one shape
    # rule the scan had seen fire, because gitleaks had timed out on the
    # only repository where the other one fires. Restoring it puts four
    # placeholder headers in generated docs back at CRITICAL.
    ("only the rule the first measurement happened to see is shape-only", _S,
     '_SHAPE_ONLY_RULES = frozenset({"curl-auth-header", "generic-api-key"})',
     '_SHAPE_ONLY_RULES = frozenset({"generic-api-key"})'),
    # The correlated finding is where the downgrade was silently undone: it
    # asserted CRITICAL of its own accord, so a duplicated test fixture came
    # back at full volume through the other door.
    ("the duplicated-secret correlation asserts CRITICAL instead of inheriting", _C,
     "                severity=secret.severity,\n",
     "                severity=Severity.CRITICAL,\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_secret_severity_mutant_is_killed(label, rel, old, new):
    assert_killed(label, SEVERITY_TESTS, run_tests_with_mutation(SEVERITY_TESTS, rel, old, new))


def test_secret_severity_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        SEVERITY_TESTS, _S, '_SHAPE_ONLY_RULES = frozenset({"curl-auth-header", "generic-api-key"})',
        '_SHAPE_ONLY_RULES = frozenset({"curl-auth-header", "generic-api-key"})',
    )
    assert result.returncode == 0, result.stdout[-2000:]
