"""The proof that Tests/test_project.py is not vacuous.

This check earns its keep by staying quiet, so half these mutants make it
LOUD -- report every repository, count a vendored suite, treat an empty
workflows directory as configured. A check that fires on every scratch
pad is worse than no check, because it teaches people to skim the output.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

PROJECT_TESTS = "Tests/test_project.py"
_P = "ghost_buster/project.py"
_C = "ghost_buster/cli.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- it stops staying quiet ---
    ("a repo with CI is reported anyway", _P,
     "    if report.has_ci:\n        # Whether the pipeline is any good",
     "    if False:\n        # Whether the pipeline is any good"),
    ("an empty .github/workflows counts as configured CI", _P,
     "        for pattern in patterns:\n"
     "            if any(d.glob(pattern)):\n                return rel\n",
     "        return rel\n"),
    ("a vendored dependency's suite counts as this repo's tests", _P,
     '            if p.is_file() and p.suffix == ".py" and _clean(p.relative_to(root)):\n',
     '            if p.is_file() and p.suffix == ".py":\n'),
    ("a repo with neither tests nor a deploy artifact is reported", _P,
     "    if report.test_files:\n        findings.append(_finding(\n",
     "    if True:\n        findings.append(_finding(\n"),

    # --- it stops speaking up ---
    ("a deploy artifact with no CI is silent", _P,
     '    if report.deploy_artifacts:\n        named = ", ".join(report.deploy_artifacts)\n',
     '    if False:\n        named = ", ".join(report.deploy_artifacts)\n'),
    ("tests with no CI are silent", _P,
     "    if report.test_files:\n        findings.append(_finding(\n",
     "    if False:\n        findings.append(_finding(\n"),
    ("only GitHub counts, so every GitLab repo reads as having no CI", _P,
     "    for name in _CI_FILES:\n        if (root / name).is_file():\n            return name\n",
     ""),
    ("the test walk stops being recursive, so a nested suite is invisible", _P,
     '_TEST_GLOBS = ("**/test_*.py", "**/*_test.py")\n',
     '_TEST_GLOBS = ("test_*.py", "*_test.py")\n'),

    # --- it says the wrong thing ---
    ("deploying with no gate is downgraded to a nit", _P,
     '            root, "deployable without CI", Severity.MAJOR,\n',
     '            root, "deployable without CI", Severity.MINOR,\n'),
    ("unrun tests are inflated to MAJOR, drowning the deploy finding", _P,
     '            root, "tests nobody runs", Severity.MINOR,\n',
     '            root, "tests nobody runs", Severity.MAJOR,\n'),
    ("the two claims are collapsed into one, losing the louder one", _P,
     "    if report.test_files:\n        findings.append(_finding(\n"
     '            root, "tests nobody runs", Severity.MINOR,\n',
     "    if report.test_files and not findings:\n        findings.append(_finding(\n"
     '            root, "tests nobody runs", Severity.MINOR,\n'),
    ("a missing directory reads as a scanned one", _P,
     '        report.reason = f"{root} is not a directory"\n        return [], report\n',
     "        pass\n"),

    # --- the CLI contract ---
    ("the project scan silently returns to opt-in", _C,
     '        "--project", action=argparse.BooleanOptionalAction, default=True,\n',
     '        "--project", action=argparse.BooleanOptionalAction, default=False,\n'),
    ("declining the project scan leaves no receipt", _C,
     '        _skipped("project scan", "--no-project")\n', "        pass\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_project_mutant_is_killed(label, rel, old, new):
    assert_killed(label, PROJECT_TESTS, run_tests_with_mutation(PROJECT_TESTS, rel, old, new))


def test_project_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        PROJECT_TESTS, _P, 'DETECTOR = "no_ci_configuration"\n',
        'DETECTOR = "no_ci_configuration"\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
