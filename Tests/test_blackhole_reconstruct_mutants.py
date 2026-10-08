"""The proof that Tests/test_blackhole_reconstruct.py is not vacuous.

The failure this guards is not a crash. It is a file of 135 plausible lines
handed to somebody as a recovery, or a proposal written quietly into the
repository it was reconstructed from. Both would look like success.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_blackhole_reconstruct.py"
_R = "blackhole_extrapolator/reconstruct.py"

MUTANTS = [
    # The heuristic must never touch a file the deterministic pass got right.
    ("the heuristic runs even after a program was recovered", _R,
     "    if _parses(determined):\n        return Reconstruction(determined",
     "    if False:\n        return Reconstruction(determined"),

    # A guess that compiles is still a guess.
    ("a heuristic result that parses is called a program", _R,
     '        return self.parses and "heuristic-split" not in self.passes',
     "        return self.parses"),

    # The whole deterministic pass.
    ("indent runs stop being read as line breaks", _R,
     '    determined = _INDENT_RUN.sub(lambda m: "\\n" + m.group(0)[1:], text)',
     "    determined = text"),

    # The header is the only thing standing between a draft and a recovery.
    ("the proposal no longer says it is not the original", _R,
     'HEADER = "# RECONSTRUCTED BY blackhole_extrapolator -- NOT THE ORIGINAL"',
     'HEADER = "# reconstructed"'),
    # The silent case: one line beginning with `#` parses as an empty module.
    ("a file that is one giant comment counts as recovered", _R,
     "    return bool(tree.body)", "    return True"),
    ("the header calls every draft a parsed program", _R,
     "            if self.is_program else",
     "            if True else"),

    # Writing into the scanned tree is the one thing this tool has never done.
    ("proposals are written beside the original", _R,
     "    target = into / (path.stem + \".reconstructed.py\")",
     "    target = path.parent / (path.stem + \".reconstructed.py\")"),
    ("an existing proposal is silently overwritten", _R,
     "    if target.exists():\n        raise FileExistsError",
     "    if False:\n        raise FileExistsError"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_reconstruct_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_reconstruct_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(TESTS, _R, "    determined = text", "    determined = text") \
        if False else run_tests_with_mutation(
            TESTS, _R, 'HEADER = "# RECONSTRUCTED BY blackhole_extrapolator -- NOT THE ORIGINAL"',
            'HEADER = "# RECONSTRUCTED BY blackhole_extrapolator -- NOT THE ORIGINAL"')
    assert result.returncode == 0, result.stdout[-2000:]
