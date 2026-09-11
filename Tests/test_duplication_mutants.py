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
# The gathering half of the CLI moved to pipeline.py in 1.6.0. The
# mutants below that point at it were re-aimed, not removed: the code
# they mutate is the same code, in its new module.
_P = "ghost_buster/pipeline.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- doc_test_count_drift claim-shape rules (v0.10.1) ---
    ("claim-shape filter bypassed (deltas and quotations flagged again)", _M,
     "            if claim_shape(before) is not None:\n                continue\n",
     ""),
    ("delta rule dropped ('gained 13 tests' reads as a total)", _M,
     '    ("delta", re.compile(\n'
     '        r"\\b(?:gained|gains|gain|added|adds|add|grew|grown|grows|growing|plus|minus|"\n'
     '        r"removed|removes|dropped|drops|another|extra|net|more|fewer)\\b\\s*(?:by\\s+)?$",\n'
     '        re.IGNORECASE)),\n',
     '    ("delta", re.compile(r"(?!x)x")),\n'),
    ("transition rule dropped ('went from 255 to 272 tests' reads as a total)", _M,
     '    ("transition", re.compile(\n'
     '        r"(?:\\bfrom\\s+\\d+\\s+to\\s+|\\b\\d+\\s*(?:->|-->|\\u2192)\\s*)$", re.IGNORECASE)),\n',
     '    ("transition", re.compile(r"(?!x)x")),\n'),
    ("quotation rule dropped (another project's quoted claim reads as ours)", _M,
     '    ("quotation", re.compile(r"[\\"\'\\u201c\\u2018]\\s*$")),\n',
     '    ("quotation", re.compile(r"(?!x)x")),\n'),
    ("attribution rule dropped ('claimed 3 tests' reads as a total)", _M,
     '    ("attribution", re.compile(r"\\b(?:claimed|reported|said)\\s*$", re.IGNORECASE)),\n',
     '    ("attribution", re.compile(r"(?!x)x")),\n'),
    ("backtick back in the quote set (a live claim under a code fence is suppressed)", _M,
     '    ("quotation", re.compile(r"[\\"\'\\u201c\\u2018]\\s*$")),\n',
     '    ("quotation", re.compile(r"[\\"\'`\\u201c\\u2018]\\s*$")),\n'),
    ("lookback window widened past the adjacent word", _M,
     "_CLAIM_LOOKBACK = 80\n", "_CLAIM_LOOKBACK = 0\n"),
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
     "    for digest, group in _identical_file_groups(files):\n        group = sorted(group)\n",
     "    for digest, group in []:\n        group = sorted(group)\n"),
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
    ("symlinked directories scanned twice again", _P,
     "        real = p.resolve()\n        if real in seen_real:\n            continue\n        seen_real.add(real)\n",
     "        real = p\n        if real in seen_real:\n            continue\n        seen_real.add(real)\n"),
    ("build/ and dist/ no longer excluded", _P,
     '    "build", "dist",\n', ""),
    ("egg-info directories no longer excluded", _P,
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
