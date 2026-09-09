"""The proof that the merge_conflict_marker tests in test_ghost_buster.py
are not vacuous: break ghost_buster/mechanical.py's detector one way at a
time in a scratch copy and run only that file. Every mutant here must be
killed.

ghost_buster --mutate reports zero candidates among these tests -- they
are either direct equality/membership checks on a call's result, which the
shape scanner doesn't treat as weak, or empty-list checks the scanner has
no shape rule for. So this is the hand-made complement, the same
arrangement every other mutant suite in this repo exists for.

An initial exploratory run of 11 mutants found four survivors. One is not
a real bug and is not here: starting the separator search AT ours_line
instead of ours_line + 1 makes no observable difference, because
_CONFLICT_OURS and _CONFLICT_SEP are mutually exclusive patterns (a line
of all "<" can never also be a line of all "="), so the one extra index
checked can never match. The same reasoning would make a matching mutant
of _next_matching's own off-by-one inert too, given how the detector's
two call sites happen to use it -- but a *direct* test of _next_matching's
own contract (never return an index before `start`) closes that gap on
the helper's own terms, independent of who happens to call it correctly
today, and that mutant is included below.

The other two survivors were real gaps, closed by new tests in
test_ghost_buster.py before this file was written, not by weakening this
file's requirements: a second, nested <<<<<<<-shaped line landing between
a real ours-line and its own resolution was being re-scanned as the start
of a second, overlapping finding once the first triplet already resolved,
and a file that is not valid UTF-8 was not covered by any test exercising
the UnicodeDecodeError branch specifically (only the unrelated
OSError-classes were implicitly covered by nothing crashing on ordinary
input).

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

GHOST_BUSTER_TESTS = "Tests/test_ghost_buster.py"
_M = "ghost_buster/mechanical.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    ("ours pattern matches nothing", _M,
     'r"^<{7}(?:\\s.*)?$"', 'r"^ZZZZZZZ(?:\\s.*)?$"'),
    ("separator pattern matches nothing", _M,
     'r"^={7}$"', 'r"^ZZZZZZZ$"'),
    ("theirs pattern matches nothing", _M,
     'r"^>{7}(?:\\s.*)?$"', 'r"^ZZZZZZZ(?:\\s.*)?$"'),
    ("missing triplet treated as a finding anyway", _M,
     '            if sep_line is None or theirs_line is None:\n'
     '                i = ours_line + 1\n                continue\n',
     '            if False:\n                i = ours_line + 1\n                continue\n'),
    ("scan does not resume after a found triplet (double-counts a nested marker)", _M,
     '            i = theirs_line + 1\n    return findings\n',
     '            i = ours_line + 1\n    return findings\n'),
    ("severity hardcoded to MINOR instead of CRITICAL", _M,
     '                severity=Severity.CRITICAL,\n', '                severity=Severity.MINOR,\n'),
    ("category hardcoded wrong", _M,
     '                category=Category.MERGE_CONFLICT_MARKER,\n', '                category=Category.OTHER,\n'),
    ("line numbers off by one (0-indexed instead of 1-indexed)", _M,
     '                    file=str(path), line_start=ours_line + 1, line_end=theirs_line + 1,\n',
     '                    file=str(path), line_start=ours_line, line_end=theirs_line,\n'),
    ("a file that is not valid UTF-8 crashes instead of being skipped", _M,
     '            text = path.read_text(encoding="utf-8")\n'
     '        except (OSError, UnicodeDecodeError):\n'
     '            continue\n        lines = text.splitlines()\n',
     '            text = path.read_text(encoding="utf-8")\n'
     '        except OSError:\n            continue\n        lines = text.splitlines()\n'),
    ("_next_matching can return an index before the given start", _M,
     '    return next((j for j in range(start, len(lines)) if pattern.match(lines[j])), None)\n',
     '    return next((j for j in range(max(0, start - 1), len(lines)) if pattern.match(lines[j])), None)\n'),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_merge_conflict_marker_mutant_is_killed(label, rel, old, new):
    assert_killed(label, GHOST_BUSTER_TESTS, run_tests_with_mutation(GHOST_BUSTER_TESTS, rel, old, new))


def test_ghost_buster_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        GHOST_BUSTER_TESTS, _M, 'DetectorFn = Callable[[List[Path]], List[Finding]]\n',
        'DetectorFn = Callable[[List[Path]], List[Finding]]\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
