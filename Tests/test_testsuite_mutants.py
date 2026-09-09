"""The proof that Tests/test_testsuite.py is not vacuous: break
ghost_buster/testsuite.py one way at a time in a scratch copy and run only
that file. Every mutant here must be killed.

As with the branch scanner, `ghost_buster --mutate` finds nothing to
mutate in test_testsuite.py: every assertion compares a scan result
directly. This suite is the hand-made complement.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

SUITE_TESTS = "Tests/test_testsuite.py"
_T = "ghost_buster/testsuite.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    ("rerun loop never runs (a flaky test reads as failing)", _T,
     "    for attempt in range(1, reruns + 1):\n",
     "    for attempt in range(0):\n"),
    ("rerun result read for the wrong node id (no rerun can ever pass)", _T,
     "        again = _aggregate(records).get(outcome.nodeid)\n",
     '        again = _aggregate(records).get("no such test")\n'),
    ("failure classification disabled (a missing module reads as a genuine failure)", _T,
     "    dep = classify_dependency(outcome.text, failure=True)\n",
     "    dep = None\n"),
    ("failure text classified with the skip-reason vocabulary (a failure mentioning "
     "'token' in its source reads as blocked)", _T,
     "    dep = classify_dependency(outcome.text, failure=True)\n",
     "    dep = classify_dependency(outcome.text, failure=False)\n"),
    ("error-line extraction returns the whole traceback", _T,
     '    picked = [ln[1:].strip() for ln in lines if ln.startswith("E ")]\n',
     "    picked = list(lines)\n"),
    ("flaky severity hardcoded to MINOR", _T,
     '                root, outcome, "flaky test", Severity.MAJOR,\n',
     '                root, outcome, "flaky test", Severity.MINOR,\n'),
    ("category hardcoded wrong", _T,
     "        category=Category.TEST_STATUS,\n", "        category=Category.OTHER,\n"),
    ("collection errors never recorded by the plugin", _T,
     "    if report.failed:\n        _write({\n", "    if False:\n        _write({\n"),
    ("continue-on-collection-errors dropped (one uncollectable module hides the suite)", _T,
     '               "--continue-on-collection-errors"]\n', "               ]\n"),
    ("unexpected xfail pass ignored", _T,
     '            elif outcome.outcome == "xpassed":\n', "            elif False:\n"),
    ("exit code 5 treated as a run", _T,
     "        if exit_code == 5:\n", "        if False:\n"),
    ("stale-skip probe disabled (a present dependency still reads as absent)", _T,
     "    if dep is not None and _dependency_present(dep, runner):\n",
     "    if False:\n"),
    ("environment-variable probe always absent", _T,
     "        return bool(os.environ.get(dep.name))\n", "        return False\n"),
    ("module probe inverted", _T,
     "        return runner.module_importable(top)\n",
     "        return not runner.module_importable(top)\n"),
    ("a skip with no reason reported as INFORMATIONAL", _T,
     '            root, outcome, "skipped without a dependency reason", Severity.MAJOR,\n'
     '            "is skipped" + (f" ({reason})" if reason else " with no reason"),\n',
     '            root, outcome, "skipped without a dependency reason", Severity.INFORMATIONAL,\n'
     '            "is skipped" + (f" ({reason})" if reason else " with no reason"),\n'),
    ("blocked tests rerun anyway (rerun count off, and a slow suite gets slower)", _T,
     "    if dep is not None:\n        report.blocked += 1\n        return _finding(\n"
     '            root, outcome, "blocked test", Severity.MINOR,\n',
     "    if dep is not None:\n        report.blocked += 1\n        report.reruns_performed += 1\n"
     "        return _finding(\n"
     '            root, outcome, "blocked test", Severity.MINOR,\n'),
    ("a module that is a file in the repository still reads as a missing dependency", _T,
     '    if dep is not None and dep.kind == "module" and local is not None:\n',
     "    if False:\n"),
    ("local-module index never finds packages", _T,
     '            if (here / d / "__init__.py").exists():\n', "            if False:\n"),
    ("every missing path reads as a tool (a missing fixture file reads as blocked)", _T,
     "            if not _missing_path_is_a_tool(name):\n                continue\n", ""),
    ("timeout not enforced (a hung suite hangs the scan)", _T,
     "                timeout=self.timeout, env=env,\n",
     "                timeout=None, env=env,\n"),
    ("bytecode written into the scanned project", _T,
     '        env["PYTHONDONTWRITEBYTECODE"] = "1"\n', ""),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_testsuite_scanner_mutant_is_killed(label, rel, old, new):
    assert_killed(label, SUITE_TESTS, run_tests_with_mutation(SUITE_TESTS, rel, old, new))


def test_testsuite_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        SUITE_TESTS, _T, 'DETECTOR = "test_status"\n', 'DETECTOR = "test_status"\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
