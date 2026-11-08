"""The proof that Tests/test_serum.py is not vacuous.

The serum's failure mode is not a crash. It is a report that looks
generous and says nothing, which is exactly what the first one did for
four releases. So most of these mutants make it LIE QUIETLY: grade a blind
site as covered, drop a site the budget did not reach, print the scanner's
numbers as the patient's, or go silent on a clean sweep.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

SERUM_TESTS = "Tests/test_serum.py"
_S = "ghost_buster/serum.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- the verdict inverts, or stops being earned ---
    ("a site its suite cannot see is graded as verifiable", _S,
     "    if code == 0:\n        return BLIND, (f\"the suite passes with {function}() emptied",
     "    if code == 0:\n        return COVERED, (f\"the suite passes with {function}() emptied"),
    ("the verdict stops naming the function it emptied", _S,
     'return COVERED, (f"the suite fails with {function}() emptied, so a mistake "',
     'return COVERED, (f"the suite fails with something emptied, so a mistake "'),
    ("every site is graded verifiable without running anything", _S,
     "    doses = [Dose(site) for site in sites]\n",
     "    doses = [Dose(site, verdict=COVERED) for site in sites]\n"),
    ("a weaker operator replaces the emptied body, so covered code reads blind", _S,
     'OPERATOR = "drop_body"\n',
     'OPERATOR = "bump_constants"\n'),
    ("the mutation is planned and never written, so every suite run is the baseline", _S,
     "            _write_tree(target, tree)\n",
     "            pass\n"),
    ("the file is never restored, so one mutation contaminates every site after it", _S,
     "            scratch.restore(dose.site.path)\n",
     "            pass\n"),

    # --- it stops failing closed ---
    ("a baseline that is not green still produces verdicts", _S,
     "        if code != 0:\n            # The suite passed during the workup",
     "        if False:\n            # The suite passed during the workup"),
    ("the budget forgets to leave room for the run it is about to start", _S,
     "    return spent + baseline_seconds > budget\n",
     "    return spent > budget\n"),
    ("the budget stops bounding anything", _S,
     "    return spent + baseline_seconds > budget\n",
     "    return False\n"),
    ("a site at module scope is silently skipped", _S,
     "            if not dose.site.function:\n",
     "            if False:\n"),
    ("a run that did not complete is graded as covered rather than left unknown", _S,
     '    return UNKNOWN, f"not assessed: the run did not complete ({tail[-120:]})"\n',
     '    return COVERED, f"not assessed: the run did not complete ({tail[-120:]})"\n'),
    ("a crashed run is read as a suite that noticed", _S,
     "    if code > 0:\n",
     "    if code != 0:\n"),

    # --- silence returns ---
    ("a sweep that found nothing says nothing, as the first serum did", _S,
     '    if not report.sites:\n        lines.append(\n            f"  enhancement surface: none. {report.files_swept} file(s) swept for "\n            f"loop pitstops, no site found.")\n',
     "    if not report.sites:\n        pass\n"),
    ("the dose block disappears when there are sites", _S,
     "    if report.sites and not report.assessed:\n",
     "    if False:\n"),

    # --- whose numbers those are ---
    ("the scanner's own work is printed under the patient's name again", _S,
     '        lines.append("  the scan\'s own work over this patient (ghost_buster\'s, "\n                     "not the patient\'s):")\n',
     '        lines.append("  measured redundancy (same input, done again):")\n'),
    ("every profile is material, so 0% of a four-file run prints as a finding", _S,
     "            if int(share) >= 10:\n                return True\n",
     "            if int(share) >= 0:\n                return True\n"),
    ("no profile is ever material, so the one real redundancy is suppressed too", _S,
     "def _material(lines: Sequence[str]) -> bool:\n",
     "def _material(lines: Sequence[str]) -> bool:\n    return False\n"),

    # --- the site loses what makes it verifiable ---
    ("a site forgets which function holds it, so nothing can be emptied", _S,
     "        function = enclosing_function(tree, stop.line) if tree is not None else \"\"\n",
     '        function = ""\n'),
    ("the outermost function wins, so a nested def is verified by its parent", _S,
     "                    if start > best[0]:\n",
     "                    if start < best[0] or best[0] == -1:\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_serum_mutant_is_killed(label, rel, old, new):
    assert_killed(label, SERUM_TESTS, run_tests_with_mutation(SERUM_TESTS, rel, old, new))


def test_serum_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        SERUM_TESTS, _S, 'OPERATOR = "drop_body"\n', 'OPERATOR = "drop_body"\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
