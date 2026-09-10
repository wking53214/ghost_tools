"""The proof that Tests/test_sql.py is not vacuous.

A SQL injection detector fails badly in both directions. Silent, it
misses the vulnerability named first in every 2026 survey of AI-written
code. Loud, it fires on every parameterised query in the codebase and
gets switched off within a week, which loses the same vulnerability more
slowly. Half these mutants are each.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

SQL_TESTS = "Tests/test_sql.py"
_M = "ghost_buster/mechanical.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- it goes silent ---
    ("the injection detector is unregistered", _M,
     '@register("sql_injection")\ndef detect_sql_injection',
     "def detect_sql_injection"),
    ("the destructive detector is unregistered", _M,
     '@register("destructive_sql")\ndef detect_destructive_sql',
     "def detect_destructive_sql"),
    ("f-strings stop counting as runtime construction", _M,
     "        if has_expr and _SQL_START.search(literal):\n            return \"f-string\", literal\n",
     "        return None\n"),
    ("concatenation and %-formatting stop counting", _M,
     "    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):\n",
     "    if False:\n"),
    (".format() stops counting", _M,
     '    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \\\n'
     '            and node.func.attr in ("format", "join"):\n',
     "    if False:\n"),
    ("the walk to the leftmost operand is removed, missing nested concatenation", _M,
     "        while isinstance(left, ast.BinOp) and isinstance(left.op, (ast.Add, ast.Mod)):\n"
     "            left = left.left\n", ""),
    ("only execute() counts, so executemany and raw are missed", _M,
     '_SQL_EXECUTORS = frozenset({\n    "execute", "executemany", "executescript", "raw", "execute_query",\n'
     '    "exec_driver_sql",\n})\n',
     '_SQL_EXECUTORS = frozenset({"execute"})\n'),
    ("an unbounded DELETE is no longer reported", _M,
     '                    (_DELETE_NO_WHERE, "unbounded delete", "DELETE with no WHERE clause"),\n', ""),
    ("TRUNCATE is no longer reported", _M,
     '                    (_TRUNCATE, "truncate", "TRUNCATE"),\n', ""),

    # --- it gets loud ---
    ("any call's arguments are checked, not only a database executor's", _M,
     "    if name in _SQL_EXECUTORS and node.args:\n        yield from node.args\n",
     "    if node.args:\n        yield from node.args\n"),
    ("any string counts as SQL, so prose and log lines are reported", _M,
     '_SQL_START = re.compile(\n'
     '    r"^\\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|MERGE|WITH)\\b",\n'
     "    re.IGNORECASE)\n",
     '_SQL_START = re.compile(r"", re.IGNORECASE)\n'),
    ("SQL built but never executed is reported", _M,
     "            for arg in _sql_call_arguments(node):\n                built = _interpolated_sql_parts(arg)\n",
     "            for arg in ast.walk(node):\n                built = _interpolated_sql_parts(arg)\n"),
    ("an UPDATE with a WHERE clause is reported as unbounded", _M,
     '_UPDATE_NO_WHERE = re.compile(\n'
     '    r"^\\s*UPDATE\\s+[\\w.\\"`\\[\\]]+\\s+SET\\b(?![\\s\\S]*\\bWHERE\\b)", re.IGNORECASE)\n',
     '_UPDATE_NO_WHERE = re.compile(r"^\\s*UPDATE\\s+[\\w.\\"`\\[\\]]+\\s+SET\\b", re.IGNORECASE)\n'),
    ("a DELETE with a WHERE clause is reported as unbounded", _M,
     '_DELETE_NO_WHERE = re.compile(\n'
     '    r"^\\s*DELETE\\s+FROM\\s+[\\w.\\"`\\[\\]]+\\s*(?:;|\\Z)", re.IGNORECASE)\n',
     '_DELETE_NO_WHERE = re.compile(r"^\\s*DELETE\\s+FROM", re.IGNORECASE)\n'),
    ("an interpolated statement is also reported as destructive, doubling the noise", _M,
     "                text = _static_sql(arg)\n                if text is None:\n                    continue\n",
     "                text = _static_sql(arg) or (_interpolated_sql_parts(arg) or (None, None))[1]\n"
     "                if text is None:\n                    continue\n"),
    ("test files are scanned by the injection detector", _M,
     "        if _looks_like_a_test(path):\n            continue\n"
     "        tree = _parse(path)\n        if tree is None:\n            continue\n"
     "        for node in ast.walk(tree):\n"
     "            if not isinstance(node, ast.Call):\n                continue\n"
     "            for arg in _sql_call_arguments(node):\n"
     "                built = _interpolated_sql_parts(arg)\n",
     "        tree = _parse(path)\n        if tree is None:\n            continue\n"
     "        for node in ast.walk(tree):\n"
     "            if not isinstance(node, ast.Call):\n                continue\n"
     "            for arg in _sql_call_arguments(node):\n"
     "                built = _interpolated_sql_parts(arg)\n"),

    # --- it says the wrong thing ---
    ("injection is downgraded from CRITICAL", _M,
     '                    layer=Layer.MECHANICAL, severity=Severity.CRITICAL,\n'
     "                    status=Status.CONFIRMED,\n"
     '                    summary=(f"{_portable_path(path)}: SQL built by {how} and then "\n',
     '                    layer=Layer.MECHANICAL, severity=Severity.MINOR,\n'
     "                    status=Status.CONFIRMED,\n"
     '                    summary=(f"{_portable_path(path)}: SQL built by {how} and then "\n'),
    ("the finding stops naming how the statement was built", _M,
     '                    attributes={"built_by": how, "statement": text.strip()[:120]},\n',
     '                    attributes={"built_by": "", "statement": text.strip()[:120]},\n'),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_sql_mutant_is_killed(label, rel, old, new):
    assert_killed(label, SQL_TESTS, run_tests_with_mutation(SQL_TESTS, rel, old, new))


def test_sql_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        SQL_TESTS, _M, "def _static_sql(node) -> Optional[str]:\n",
        "def _static_sql(node) -> Optional[str]:\n",
    )
    assert result.returncode == 0, result.stdout[-2000:]
