"""The proof that Tests/test_annotate.py is not vacuous.

This module writes to files. The mutants that matter are the ones that
remove a guard and let a comment change what a program means -- and one
that was not hypothetical: checking the whole strip at once instead of line
by line, which silently cost every annotation in any file containing the
marker inside a string.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_annotate.py"
_A = "ghost_buster/annotate.py"

MUTANTS = [
    # The invariant itself. Without the comparison, every refusal below
    # becomes an acceptance.
    ("the syntax trees are no longer compared", _A,
     "        return ast.dump(ast.parse(before)) == ast.dump(ast.parse(after))",
     "        return True"),
    ("a file that does not parse is edited anyway", _A,
     "    except (SyntaxError, ValueError):\n        return False",
     "    except (SyntaxError, ValueError):\n        return True"),

    # The per-line strip. The whole-file version is the version that shipped
    # first and lost a file's annotations to one string literal.
    ("removals stop being checked one at a time", _A,
     "        if keep(candidate):\n            lines = candidate\n\n    for number, bodies",
     "        lines = candidate\n\n    for number, bodies"),

    # Lines that cannot carry a comment.
    # `if False` here covers both halves. The backslash half is also caught
    # by the syntax-tree check -- a comment after a backslash is a
    # SyntaxError -- so the blank-line half is what this mutant actually
    # distinguishes, and it is a judgement the tree check cannot make.
    ("a blank line or a backslash continuation is annotated anyway", _A,
     '        if not content.strip() or content.rstrip().endswith("\\\\"):',
     "        if False:"),

    # Trailing, not inserted: the line-number promise.
    ("the note is given a line of its own", _A,
     "        candidate[number - 1] = content + note + ending",
     "        candidate[number - 1] = note.strip() + ending + content + ending"),

    # The file with nothing left to say is the one that keeps a stale note.
    ("only files with something to say are swept", _A,
     "    targets = sorted({str(f) for f in map(Path, files) if f.suffix == \".py\"}\n"
     "                     | set(by_file))",
     "    targets = sorted(set(by_file))"),

    # Idempotence, both records.
    ("old notes are left in place and new ones appended", _A,
     "        without = _TRAILING.sub(\"\", content)",
     "        without = content"),
    ("the README block is appended instead of replaced", _A,
     "    opened, closed = _BEGIN_LINE.search(before), _END_LINE.search(before)",
     "    opened, closed = None, None"),
    ("a marker written as prose counts as a marker", _A,
     '_BEGIN_LINE = re.compile(r"^" + re.escape(BEGIN) + r"[ \\t]*$", re.M)',
     '_BEGIN_LINE = re.compile(re.escape(BEGIN))'),
    ("the README is rewritten even when nothing changed", _A,
     "    if after == before:\n        return False",
     "    if False:\n        return False"),

    # A clean run must leave a record that it ran.
    ("a clean run writes no table at all", _A,
     '    body = "\\n".join(rows) if rows else "| _none_ | | | |"',
     '    body = "\\n".join(rows)'),

    # Absolute paths in a table that gets committed.
    ("the table carries machine paths", _A,
     "def _relative(path: str, root: Path | None) -> str:\n    if root is None:",
     "def _relative(path: str, root: Path | None) -> str:\n    return str(path)\n    if root is None:"),

    # The two sides of the note say different things on purpose.
    ("both sides of the pair get the same sentence", _A,
     '            add(path, line, f"`{d.arg}` is `{d.param}` in the signature")',
     '            add(path, line, f"`{d.param}` is `{d.arg}` at every call site")'),

    # Determinism when a line carries more than one note.
    ("notes on one line keep discovery order", _A,
     '    note = "  # " + MARKER + " -- " + "; ".join(sorted(bodies))',
     '    note = "  # " + MARKER + " -- " + "; ".join(bodies)'),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_annotate_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_annotate_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(TESTS, _A, "MARKER = ", "MARKER = ")
    assert result.returncode == 0, result.stdout[-2000:]
