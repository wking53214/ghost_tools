"""The proof that Tests/test_archive.py is not vacuous. The working tree is
never modified."""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

ARCHIVE_TESTS = "Tests/test_archive.py"
_A = "ghost_buster/archive.py"
_C = "ghost_buster/cli.py"
# The gathering half of the CLI moved to pipeline.py in 1.6.0. The
# mutants below that point at it were re-aimed, not removed: the code
# they mutate is the same code, in its new module.
_P = "ghost_buster/pipeline.py"

MUTANTS = [
    ("the marker is never found", _A,
     "    if not p.is_file():\n        return None\n",
     "    return None\n    if not p.is_file():\n        return None\n"),
    ("the surgeon operates on an archive", _C,
     '    if archive is not None:\n        print("refused: an archive is not a patient; remove .ghost_archive to operate",\n',
     '    if False:\n        print("refused: an archive is not a patient; remove .ghost_archive to operate",\n'),
    ("an archive is assessed for candidacy anyway", _C,
     '    if archive is not None:\n        print(f"serum candidacy: not assessed (archive: {archive.reason or \'no reason given\'})")\n',
     '    if False:\n        pass\n'),
    ("the receipt line is silent", _C,
     "    if archive is not None:\n        print(archive.receipt(), file=sys.stderr)\n",
     "    if False:\n        pass\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_archive_mutant_is_killed(label, rel, old, new):
    assert_killed(label, ARCHIVE_TESTS, run_tests_with_mutation(ARCHIVE_TESTS, rel, old, new))


def test_archive_tests_pass_unmutated():
    result = run_tests_with_mutation(ARCHIVE_TESTS, _A, 'MARKER = ".ghost_archive"', 'MARKER = ".ghost_archive"')
    assert result.returncode == 0, result.stdout[-2000:]
