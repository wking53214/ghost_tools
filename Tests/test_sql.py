"""SQL built from runtime parts, and SQL with no bounds.

Named first in every 2026 survey of AI-written code, for a structural
reason rather than a moral one: a model reproduces the patterns in its
training data, an f-string is by far the most common way SQL appears in
that data, and "make it work" never asks for a parameterised query.

The check is unusually clean because the safe form and the unsafe form
are different AST SHAPES, not different values -- one argument built at
runtime versus two with the values bound. So there is no threshold here
and no guessing at intent, and most of these tests pin the safe forms.
"""
from __future__ import annotations

import pytest

from ghost_buster.mechanical import (
    detect_destructive_sql, detect_sql_injection, run_all,
)
from ghost_buster.schema import Severity


def _write(tmp_path, text, name="db.py"):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


UNSAFE = [
    ("f-string", 'def q(cur, uid):\n    cur.execute(f"SELECT * FROM users WHERE id = {uid}")\n'),
    ("concatenation", 'def q(cur, n):\n    cur.execute("SELECT * FROM t WHERE n = \'" + n + "\'")\n'),
    ("%-formatting", 'def q(cur, uid):\n    cur.execute("DELETE FROM s WHERE id = %s" % uid)\n'),
    (".format()", 'def q(cur, t):\n    cur.execute("UPDATE t SET a = 1 WHERE b = {}".format(t))\n'),
]


@pytest.mark.parametrize("how,src", UNSAFE, ids=[u[0] for u in UNSAFE])
def test_sql_built_at_runtime_and_executed_is_critical(tmp_path, how, src):
    findings = detect_sql_injection([_write(tmp_path, src)])
    assert len(findings) == 1
    assert findings[0].severity == Severity.CRITICAL
    assert findings[0].attributes["built_by"] == how


def test_nested_concatenation_is_found(tmp_path):
    """`"SELECT ..." + a + b` parses as BinOp(BinOp(...)), so checking the
    outer node's left operand finds a BinOp and misses the statement. That
    was the first version of this detector, and it missed the single most
    common way this bug is written by hand."""
    src = 'def q(cur, a, b):\n    cur.execute("SELECT * FROM t WHERE a = " + a + " AND b = " + b)\n'
    assert len(detect_sql_injection([_write(tmp_path, src)])) == 1


SAFE = [
    ("parameterised", 'def q(cur, uid):\n    cur.execute("SELECT * FROM t WHERE id = ?", (uid,))\n'),
    ("plain literal", 'def q(cur):\n    cur.execute("SELECT count(*) FROM t")\n'),
    ("an f-string that is not SQL",
     'def log(logger, n):\n    logger.info(f"selecting the best option for {n}")\n'),
    ("SQL built but never executed",
     'def build(uid):\n    return f"SELECT * FROM t WHERE id = {uid}"\n'),
    ("a formatted string passed to something else",
     'def go(client, uid):\n    client.send(f"SELECT * FROM t WHERE id = {uid}")\n'),
]


@pytest.mark.parametrize("label,src", SAFE, ids=[s[0] for s in SAFE])
def test_the_safe_form_is_not_reported(tmp_path, label, src):
    assert detect_sql_injection([_write(tmp_path, src)]) == []


def test_a_parameterised_call_is_safe_even_with_ugly_sql(tmp_path):
    src = ('def q(cur, a, b):\n'
           '    cur.execute("SELECT * FROM t WHERE a = ? AND b = ? ORDER BY c", (a, b))\n')
    assert detect_sql_injection([_write(tmp_path, src)]) == []


@pytest.mark.parametrize("call", ["executemany", "raw", "execute_query", "exec_driver_sql"])
def test_every_executor_spelling_counts(tmp_path, call):
    """An execute()-only rule misses executemany, Django's raw(), and
    SQLAlchemy's exec_driver_sql -- three of the four most common ways this
    code is actually written."""
    src = f'def q(cur, uid):\n    cur.{call}(f"SELECT * FROM t WHERE id = {{uid}}")\n'
    assert len(detect_sql_injection([_write(tmp_path, src)])) == 1


def test_a_non_sql_execute_is_not_reported(tmp_path):
    """`execute` is not a database-only method name. A task runner, a
    command object and a workflow step all have one, and a detector that
    reports every f-string passed to any `execute` fires constantly on code
    that touches no database at all."""
    src = 'def run(task, n):\n    task.execute(f"step {n} of the pipeline")\n'
    assert detect_sql_injection([_write(tmp_path, src)]) == []


def test_test_files_are_skipped(tmp_path):
    src = 'def q(cur, uid):\n    cur.execute(f"SELECT * FROM t WHERE id = {uid}")\n'
    assert detect_sql_injection([_write(tmp_path, src, "test_db.py")]) == []


def test_run_all_actually_calls_the_injection_detector(tmp_path):
    src = 'def q(cur, uid):\n    cur.execute(f"SELECT * FROM t WHERE id = {uid}")\n'
    assert "sql_injection" in {f.detector for f in run_all([_write(tmp_path, src)])}


# --------------------------------------------------------- destructive SQL

DESTRUCTIVE = [
    ("unbounded delete", 'def w(cur):\n    cur.execute("DELETE FROM audit_log")\n'),
    ("unbounded update", 'def w(cur):\n    cur.execute("UPDATE accounts SET balance = 0")\n'),
    ("truncate", 'def w(cur):\n    cur.execute("TRUNCATE TABLE staging")\n'),
]


@pytest.mark.parametrize("kind,src", DESTRUCTIVE, ids=[d[0] for d in DESTRUCTIVE])
def test_an_unbounded_statement_is_major(tmp_path, kind, src):
    findings = detect_destructive_sql([_write(tmp_path, src)])
    assert len(findings) == 1
    assert findings[0].severity == Severity.MAJOR
    assert findings[0].attributes["kind"] == kind


BOUNDED = [
    ("delete with a where", 'def w(cur):\n    cur.execute("DELETE FROM t WHERE id = 1")\n'),
    ("update with a where", 'def w(cur):\n    cur.execute("UPDATE t SET a = 1 WHERE id = 2")\n'),
    ("a select", 'def w(cur):\n    cur.execute("SELECT * FROM t")\n'),
    ("an insert", 'def w(cur):\n    cur.execute("INSERT INTO t VALUES (1)")\n'),
    ("prose mentioning delete", 'def w(logger):\n    logger.info("delete from the queue when done")\n'),
]


@pytest.mark.parametrize("label,src", BOUNDED, ids=[b[0] for b in BOUNDED])
def test_a_bounded_statement_is_not_reported(tmp_path, label, src):
    assert detect_destructive_sql([_write(tmp_path, src)]) == []


def test_a_multiline_update_with_a_where_is_not_reported(tmp_path):
    """The WHERE may be several lines below the SET."""
    src = ('def w(cur):\n'
           '    cur.execute("""\n'
           '        UPDATE accounts\n'
           '        SET balance = 0\n'
           '        WHERE closed = 1\n'
           '    """)\n')
    assert detect_destructive_sql([_write(tmp_path, src)]) == []


def test_an_interpolated_destructive_statement_is_left_to_the_other_detector(tmp_path):
    """An interpolated statement may carry a WHERE this scan cannot see,
    and sql_injection has more urgent things to say about it. The literal
    part here matches the unbounded-delete pattern exactly, so this test
    only means something because the detector refuses interpolated text --
    the first fixture used `f"DELETE FROM {t}"`, whose literal part is
    `DELETE FROM ` with no table, and passed for the wrong reason."""
    src = 'def w(cur, sfx):\n    cur.execute(f"DELETE FROM audit_log{sfx}")\n'
    assert detect_destructive_sql([_write(tmp_path, src)]) == []
    assert len(detect_sql_injection([_write(tmp_path, src)])) == 1


def test_run_all_actually_calls_the_destructive_detector(tmp_path):
    src = 'def w(cur):\n    cur.execute("DELETE FROM audit_log")\n'
    assert "destructive_sql" in {f.detector for f in run_all([_write(tmp_path, src)])}


def test_ghost_tools_own_source_is_clean():
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "ghost_buster"
    files = sorted(src.glob("*.py"))
    assert detect_sql_injection(files) == []
    assert detect_destructive_sql(files) == []
