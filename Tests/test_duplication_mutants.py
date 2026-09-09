"""The proof that the v0.9 duplication-heuristic tests in
test_ghost_buster.py are not vacuous: break each new rule in a scratch copy
and run only that file. Every mutant here must be killed.

Every rule below was adopted because a measurement on the first
whole-library run (37 repositories) said it should be, and each has a
test that says exactly what it does. A mutant that survives here means the
measurement is no longer being enforced by anything.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

GHOST_BUSTER_TESTS = "Tests/test_ghost_buster.py"
_M = "ghost_buster/mechanical.py"
_C = "ghost_buster/cli.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    ("near_duplicate default min_lines reverted to 6", _M,
     "def detect_near_duplicate_functions(files: List[Path], min_lines: int = 10) -> List[Finding]:\n",
     "def detect_near_duplicate_functions(files: List[Path], min_lines: int = 6) -> List[Finding]:\n"),
    ("test-only clusters no longer informational", _M,
     "        if all(_is_test_file(p) for p, _ in occurrences):\n            severity = Severity.INFORMATIONAL\n        elif len(occurrences) > 2:\n",
     "        if False:\n            severity = Severity.INFORMATIONAL\n        elif len(occurrences) > 2:\n"),
    ("byte-identical twins no longer collapsed before fingerprinting", _M,
     "    representatives = [p for p in files if p not in seen_twins]\n",
     "    representatives = list(files)\n"),
    ("duplicate_file reports nothing", _M,
     "    for group in _identical_file_groups(files):\n        group = sorted(group)\n",
     "    for group in []:\n        group = sorted(group)\n"),
    ("empty files counted as duplicates again", _M,
     "        if not content:\n",
     "        if False:\n"),
    ("duplicate_file severity downgraded", _M,
     '            detector="duplicate_file",\n            category=Category.DUPLICATION,\n            layer=Layer.MECHANICAL,\n            severity=Severity.MAJOR,\n',
     '            detector="duplicate_file",\n            category=Category.DUPLICATION,\n            layer=Layer.MECHANICAL,\n            severity=Severity.MINOR,\n'),
    ("_is_test_file ignores the tests/ directory convention", _M,
     '    return any(part.lower() in ("tests", "test") for part in path.parts[:-1])\n',
     "    return False\n"),
    ("single statements counted within one block again (distinct-block rule removed)", _M,
     "                if len(units[0]) == 1 and len(blocks_of[fp]) < 2:\n                    continue  # one block repeating a statement is a list, not a ghost\n",
     "                if False:\n                    continue\n"),
    ("intra complexity floor reverted to 15", _M,
     "    files: List[Path], min_statements: int = 3, min_complexity: int = 20\n",
     "    files: List[Path], min_statements: int = 3, min_complexity: int = 15\n"),
    ("intra complexity floor raised to 25 (loses a gate.py branch)", _M,
     "    files: List[Path], min_statements: int = 3, min_complexity: int = 20\n",
     "    files: List[Path], min_statements: int = 3, min_complexity: int = 25\n"),
    ("symlinked directories scanned twice again", _C,
     "        real = p.resolve()\n        if real in seen_real:\n            continue\n        seen_real.add(real)\n",
     "        real = p\n        if real in seen_real:\n            continue\n        seen_real.add(real)\n"),
    ("build/ and dist/ no longer excluded", _C,
     '    "build", "dist",\n', ""),
    ("egg-info directories no longer excluded", _C,
     '        if any(part.endswith(".egg-info") for part in p.parts[:-1]):\n            continue\n', ""),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_duplication_mutant_is_killed(label, rel, old, new):
    assert_killed(label, GHOST_BUSTER_TESTS, run_tests_with_mutation(GHOST_BUSTER_TESTS, rel, old, new))


def test_ghost_buster_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        GHOST_BUSTER_TESTS, _M, 'DetectorFn = Callable[[List[Path]], List[Finding]]\n',
        'DetectorFn = Callable[[List[Path]], List[Finding]]\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
