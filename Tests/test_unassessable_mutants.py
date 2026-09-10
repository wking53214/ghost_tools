"""The proof that Tests/test_unassessable.py is not vacuous.

The failure mode this detector guards against is silence, so the mutants
that matter are the ones that make it silent again -- each of which
restores exactly the bug it was written to end.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

UNASSESSABLE_TESTS = "Tests/test_unassessable.py"
_M = "ghost_buster/mechanical.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    ("the detector goes silent again (abstention reads as all-clear)", _M,
     "        reason = _parse_failure(path)\n        if reason is None:\n            continue\n",
     "        reason = _parse_failure(path)\n        continue\n"),
    ("only syntax errors abstain; an unreadable encoding is silently clean", _M,
     "    except UnicodeDecodeError as e:\n"
     '        return f"UnicodeDecodeError: not valid {e.encoding} at byte {e.start}"\n',
     "    except UnicodeDecodeError:\n        return None\n"),
    ("the reason drops the line number and stops being actionable", _M,
     '        line = f" at line {e.lineno}" if e.lineno else ""\n', '        line = ""\n'),
    ("abstention is downgraded to a nit", _M,
     "            severity=Severity.MAJOR,\n"
     "            status=Status.CONFIRMED,\n"
     '            summary=(f"{_portable_path(path)} could not be parsed, so every "\n',
     "            severity=Severity.INFORMATIONAL,\n"
     "            status=Status.CONFIRMED,\n"
     '            summary=(f"{_portable_path(path)} could not be parsed, so every "\n'),
    ('every file is reported, python or not (prose becomes noise)', _M,
     '    for path in sorted(f for f in files if f.suffix == ".py"):\n        reason = _parse_failure(path)\n',
     '    for path in sorted(files):\n        reason = _parse_failure(path)\n'),
    ("a readable file is reported too (the detector cries wolf)", _M,
     "        ast.parse(path.read_text(encoding=\"utf-8\"), filename=str(path))\n        return None\n",
     "        ast.parse(path.read_text(encoding=\"utf-8\"), filename=str(path))\n"
     '        return "SyntaxError: always"\n'),
    ("the detector is unregistered, so run_all never calls it", _M,
     '@register("unassessable_file")\ndef detect_unassessable_file',
     "def detect_unassessable_file"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_unassessable_mutant_is_killed(label, rel, old, new):
    assert_killed(label, UNASSESSABLE_TESTS,
                  run_tests_with_mutation(UNASSESSABLE_TESTS, rel, old, new))


def test_unassessable_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        UNASSESSABLE_TESTS, _M, "def _parse_failure(path: Path):\n",
        "def _parse_failure(path: Path):\n",
    )
    assert result.returncode == 0, result.stdout[-2000:]
