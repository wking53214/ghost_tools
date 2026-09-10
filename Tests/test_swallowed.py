"""A handler that catches something and does nothing with it.

The same failure `dead_end_call` reports one level up: the operation reports
success and nothing happened. What separates a defect from correct code here
is not the empty body, it is what was caught, so most of these tests are
about breadth.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from ghost_buster.schema import Category, Layer, Severity, Status
from ghost_buster.swallowed import (
    BARE,
    DETECTOR,
    detect_swallowed_exceptions,
    find_swallowed,
)


def _tree(tmp_path: Path, files: dict) -> list:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    return sorted(tmp_path.rglob("*.py"))


def _one(tmp_path, source):
    return find_swallowed(_tree(tmp_path, {"m.py": source}))


# ---------------------------------------------------------------- breadth

def test_catching_everything_and_doing_nothing_is_major(tmp_path):
    findings = detect_swallowed_exceptions(_tree(tmp_path, {"m.py": '''\
        def publish(decision):
            try:
                send(decision)
            except Exception:
                pass
    '''}))
    assert len(findings) == 1
    f = findings[0]
    assert f.detector == DETECTOR
    assert f.category is Category.VACUOUS_CHECK
    assert f.layer is Layer.MECHANICAL
    assert f.status is Status.CONFIRMED
    assert f.severity is Severity.MAJOR
    assert "except Exception" in f.summary
    assert f.attributes["caught"] == "Exception"


def test_a_bare_except_is_major(tmp_path):
    found = _one(tmp_path, '''\
        def publish(d):
            try:
                send(d)
            except:
                pass
    ''')
    assert [s.caught for s in found] == [BARE]
    assert found[0].catches_everything


def test_base_exception_counts_as_everything(tmp_path):
    found = _one(tmp_path, '''\
        def publish(d):
            try:
                send(d)
            except BaseException:
                pass
    ''')
    assert found[0].catches_everything


def test_a_narrow_exception_is_minor(tmp_path):
    """An absent optional dependency is the usual case, and the handler IS
    the behaviour."""
    findings = detect_swallowed_exceptions(_tree(tmp_path, {"m.py": '''\
        try:
            import numpy
        except ImportError:
            pass
    '''}))
    assert findings[0].severity is Severity.MINOR
    assert "worth a look rather than a fix" in findings[0].detail


def test_a_tuple_containing_exception_still_catches_everything(tmp_path):
    """`except (ValueError, Exception)` is `except Exception` with extra
    words in front of it."""
    found = _one(tmp_path, '''\
        def f(x):
            try:
                return int(x)
            except (ValueError, Exception):
                pass
    ''')
    assert found[0].catches_everything


def test_a_tuple_of_narrow_exceptions_stays_narrow(tmp_path):
    found = _one(tmp_path, '''\
        def f(x):
            try:
                return int(x)
            except (ValueError, TypeError):
                pass
    ''')
    assert not found[0].catches_everything


# ------------------------------------------------------- what is swallowing

def test_a_handler_that_does_something_is_not_swallowing(tmp_path):
    assert _one(tmp_path, '''\
        import logging


        def f(x):
            try:
                return int(x)
            except ValueError:
                logging.warning("bad value")
                return 0
    ''') == []


def test_a_handler_that_re_raises_is_not_swallowing(tmp_path):
    assert _one(tmp_path, '''\
        def f(x):
            try:
                return int(x)
            except ValueError:
                raise
    ''') == []


def test_a_documented_empty_handler_is_still_empty(tmp_path):
    """Documented at length, implemented not at all."""
    found = _one(tmp_path, '''\
        def f(x):
            try:
                return int(x)
            except ValueError:
                """Bad input is expected here and safely ignored."""
                pass
    ''')
    assert len(found) == 1


def test_contextlib_suppress_is_not_flagged(tmp_path):
    """It says in its own name what it does, which is the opposite of the
    defect."""
    assert _one(tmp_path, '''\
        import contextlib


        def f(path):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
    ''') == []


def test_a_pass_that_is_not_in_a_handler_is_not_flagged(tmp_path):
    assert _one(tmp_path, '''\
        class Marker:
            pass


        def f():
            for i in range(3):
                pass
    ''') == []


# ------------------------------------------------------------- test files

def test_test_files_are_left_alone(tmp_path):
    """Best-effort cleanup in a teardown is ordinary. `is_test_path` is
    shared with naming.py and deadend.py so all three agree what a test is."""
    assert find_swallowed(_tree(tmp_path, {
        "tests/test_thing.py": '''\
            def test_it():
                try:
                    cleanup()
                except Exception:
                    pass
        ''',
    })) == []


def test_every_handler_in_a_file_is_reported(tmp_path):
    found = _one(tmp_path, '''\
        def f(x):
            try:
                a = int(x)
            except ValueError:
                pass
            try:
                b = int(x)
            except Exception:
                pass
            return 0
    ''')
    assert len(found) == 2
    assert [s.line for s in found] == sorted(s.line for s in found)


def test_a_file_that_does_not_parse_is_skipped(tmp_path):
    assert _one(tmp_path, "def broken(:\n") == []
