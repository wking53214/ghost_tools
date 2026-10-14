"""Tests that cannot fail, and tests that only check a mock, are named as such."""
from __future__ import annotations

import textwrap
from pathlib import Path

from ghost_buster import corpus
from ghost_buster.mechanical import registered_detectors
from ghost_buster.schema import Category, Severity, Status
from ghost_buster.testshape import ASSERTLESS, MOCK_ONLY, detect_assertless_tests, detect_mock_only_tests, find_shapes


def _tree(tmp_path: Path, files: dict) -> list:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    corpus.reset()
    return sorted(tmp_path.rglob("*.py"))


def _shapes(tmp_path, body, name="tests/test_x.py"):
    return [(f.attributes["name"], f.attributes["shape"], f.severity) for f in find_shapes(_tree(tmp_path, {name: body}))]


def test_both_detectors_are_registered():
    assert {ASSERTLESS, MOCK_ONLY} <= set(registered_detectors())


def test_a_stub_test_is_major_and_an_assertless_one_is_minor(tmp_path):
    found = _shapes(tmp_path, '''\
        def test_boots():
            pass


        def test_boots_too():
            """Just a docstring."""
            ...


        def test_runs():
            run_pipeline()
    ''')
    assert found == [("test_boots", "stub", Severity.MAJOR), ("test_boots_too", "stub", Severity.MAJOR),
                     ("test_runs", "assertless", Severity.MINOR)]


def test_every_way_of_asserting_counts(tmp_path):
    found = _shapes(tmp_path, '''\
        import pytest
        import unittest


        def _assert_fine(x):
            assert x


        def _check_round_trip(v):
            if v != v:
                raise AssertionError


        def round_trips(v):
            assert v == v


        def test_assert_statement():
            assert len("x")


        def test_pytest_raises():
            with pytest.raises(ValueError):
                int("x")


        def test_raise_statement():
            if False:
                raise RuntimeError


        def test_local_helper():
            _assert_fine(1)


        def test_local_helper_that_raises():
            _check_round_trip(1)


        def test_local_helper_with_an_ordinary_name():
            round_trips(1)


        def test_verify_prefix():
            verify_output(1)


        class TestUnit(unittest.TestCase):
            def test_method(self):
                self.assertEqual(1, 1)
    ''')
    assert found == []


def test_a_helper_imported_from_a_module_beside_the_test_counts(tmp_path):
    files = _tree(tmp_path, {
        "tests/tree_guard.py": "import contextlib\n\n\n@contextlib.contextmanager\ndef unchanged(t):\n    yield\n    assert t\n",
        "tests/conftest.py": "def settled(x):\n    assert x\n",
        "tests/test_g.py": "from tree_guard import unchanged as same\n\n\ndef test_a(tree):\n    with same(tree):\n        run(tree)\n\n\ndef test_b():\n    settled(1)\n\n\ndef test_c():\n    other(1)\n",
    })
    assert [f.attributes["name"] for f in find_shapes(files)] == ["test_c"]


def test_methods_of_a_test_class_are_read_too(tmp_path):
    found = _shapes(tmp_path, '''\
        import unittest


        class TestThing(unittest.TestCase):
            def test_nothing(self):
                pass

            def test_runs(self):
                self.thing.go()

            def helper(self):
                pass
    ''')
    assert found == [("test_nothing", "stub", Severity.MAJOR), ("test_runs", "assertless", Severity.MINOR)]


def test_mock_only_is_named_and_a_real_assertion_beside_it_clears_it(tmp_path):
    found = _shapes(tmp_path, '''\
        from unittest.mock import Mock


        def test_sends():
            g = Mock()
            place(g)
            g.submit.assert_called_once()


        def test_sends_and_checks():
            g = Mock()
            result = place(g)
            g.submit.assert_called_once()
            assert result == "ok"
    ''')
    assert found == [("test_sends", "mock_only", Severity.MINOR)]


def test_xfail_and_skip_are_left_alone(tmp_path):
    found = _shapes(tmp_path, '''\
        import pytest


        @pytest.mark.xfail(reason="known")
        def test_later():
            pass


        @pytest.mark.skip
        def test_never():
            pass
    ''')
    assert found == []


def test_only_test_files_are_read(tmp_path):
    found = _shapes(tmp_path, "def test_x():\n    pass\n", name="pkg/helpers.py")
    assert found == []
    found = _shapes(tmp_path, "def test_x():\n    pass\n", name="pkg/sample_test.py")
    assert [n for n, _, _ in found] == ["test_x"]


def test_the_findings_say_what_they_are(tmp_path):
    files = _tree(tmp_path, {"tests/test_y.py": "def test_a():\n    pass\n\n\ndef test_b():\n    from unittest.mock import Mock\n    m = Mock()\n    m.go()\n    m.go.assert_called()\n"})
    (stub,) = detect_assertless_tests(files)
    (mock,) = detect_mock_only_tests(files)
    assert stub.detector == ASSERTLESS and stub.category is Category.VACUOUS_CHECK and stub.status is Status.CONFIRMED
    assert "does nothing" in stub.summary and stub.evidence.line_start == 1
    assert mock.detector == MOCK_ONLY and "only against a mock" in mock.summary and mock.evidence.line_start == 5


def test_an_assert_that_cannot_fail_is_no_assertion(tmp_path):
    found = _shapes(tmp_path, '''\
        def test_true():
            run()
            assert True


        def test_one():
            run()
            assert 1


        def test_same():
            x = run()
            assert x == x


        def test_real():
            x = run()
            assert x == 1


        def test_identity_check_is_real():
            x = run()
            assert x is None
    ''')
    assert [n for n, _, _ in found] == ["test_true", "test_one", "test_same"]


def test_two_classes_with_the_same_method_name_are_two_findings(tmp_path):
    files = _tree(tmp_path, {"tests/test_c.py": (
        "class TestA:\n    def test_runs(self):\n        pass\n\n\n"
        "class TestB:\n    def test_runs(self):\n        pass\n")})
    found = find_shapes(files)
    assert len(found) == 2 and len({f.id for f in found}) == 2


def test_the_identity_survives_an_edit_above_the_test(tmp_path):
    (before,) = find_shapes(_tree(tmp_path, {"tests/test_i.py": "def test_a():\n    pass\n"}))
    (after,) = find_shapes(_tree(tmp_path, {"tests/test_i.py": "import os\n\n\ndef helper():\n    return 1\n\n\ndef test_a():\n    pass\n"}))
    assert before.id == after.id and after.evidence.line_start == 8


def test_an_unparseable_test_file_is_skipped_not_crashed(tmp_path):
    files = _tree(tmp_path, {"tests/test_z.py": "def test_(:\n"})
    assert find_shapes(files) == []
