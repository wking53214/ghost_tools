"""Tests for ghost_buster/testsuite.py, exercised against real pytest
projects built in tmp_path -- the suite IS the input, the same way the
repository is the input for test_branches.py.

One project carrying every outcome shape is scanned once per module (a
scan is a full pytest run plus one isolated rerun per attempt, so it is
the expensive part); the small "did not run" cases build their own.
"""
from __future__ import annotations

import os
import re
import sys
import textwrap
from pathlib import Path

import pytest

from ghost_buster.cli import main
from ghost_buster.schema import Category, Severity, Status
from ghost_buster.testsuite import _index_local_modules, classify_dependency, render_report, scan

STALE_ENV = "GHOST_STALE_ENV_PROBE"
ABSENT_ENV = "GHOST_ABSENT_ENV_PROBE"

SHAPES = textwrap.dedent('''
    import pathlib
    import pytest


    def test_passes():
        assert True


    def test_fails_for_real():
        assert 1 == 2


    def test_token_math():
        # A genuine failure whose source mentions a word the skip-reason
        # vocabulary treats as a service. Must read as failing, not blocked.
        token = 1
        server = "db"
        assert token == 2, server


    def test_handles_refusal_then_fails():
        # The source names an exception the failure vocabulary recognises,
        # but the failure itself is a plain assertion. Only the error lines
        # may be classified; the source walked to reach them may not.
        try:
            raise ConnectionRefusedError("refused")
        except ConnectionRefusedError:
            handled = True
        assert handled is False


    @pytest.mark.parametrize("tag", ["a b"])
    def test_flaky(tag):
        p = pathlib.Path(__file__).parent / "flaky.counter"
        n = int(p.read_text()) if p.exists() else 0
        p.write_text(str(n + 1))
        assert n >= 1


    def test_blocked_module():
        import definitely_not_a_module_ghost_xyz  # noqa: F401


    def test_blocked_service():
        raise ConnectionRefusedError("[Errno 111] Connection refused")


    @pytest.mark.skip
    def test_skip_no_reason():
        pass


    @pytest.mark.skip(reason="TODO: fix later")
    def test_skip_todo():
        pass


    @pytest.mark.skip(reason="requires Postgres")
    def test_skip_postgres():
        pass


    @pytest.mark.skip(reason="AUGUR checkout not available")
    def test_skip_sibling_checkout():
        pass


    @pytest.mark.skip(reason="requires json")
    def test_skip_stale_module():
        pass


    @pytest.mark.skip(reason="needs %s set")
    def test_skip_stale_env():
        pass


    @pytest.mark.skip(reason="needs %s set")
    def test_skip_absent_env():
        pass


    def test_importorskip():
        pytest.importorskip("definitely_not_a_module_ghost_abc")


    @pytest.mark.xfail(reason="known")
    def test_xfail_fails():
        assert False


    @pytest.mark.xfail(reason="known")
    def test_xpass():
        assert True


    @pytest.fixture
    def broken_fixture():
        raise RuntimeError("fixture broke")


    def test_setup_error(broken_fixture):
        pass
''') % (STALE_ENV, ABSENT_ENV)

COLLECT_ERROR = "import definitely_not_a_module_ghost_collect  # noqa: F401\n"
LOCAL_IMPORT = "import helper_local_ghost  # noqa: F401\n\n\ndef test_uses_helper():\n    pass\n"


def _project(path: Path, files: dict) -> Path:
    tests = path / "tests"
    tests.mkdir(parents=True)
    for name, content in files.items():
        (tests / name).write_text(content)
    return path


@pytest.fixture(scope="module")
def shapes(tmp_path_factory):
    proj = _project(tmp_path_factory.mktemp("shapes"),
                    {"test_shapes.py": SHAPES, "test_collect_error.py": COLLECT_ERROR,
                     "test_local_import.py": LOCAL_IMPORT})
    (proj / "src").mkdir()
    (proj / "src" / "helper_local_ghost.py").write_text("VALUE = 1\n")
    saved = {k: os.environ.get(k) for k in (STALE_ENV, ABSENT_ENV)}
    os.environ[STALE_ENV] = "1"
    os.environ.pop(ABSENT_ENV, None)
    try:
        findings, report = scan(proj)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return proj, findings, report


def _kinds(findings):
    out = {}
    for f in findings:
        kind = f.summary.split(":", 1)[0]
        out.setdefault(kind, []).append(f)
    return out


def _named(findings, test_name):
    pattern = re.compile(rf"(::|: ){re.escape(test_name)}( |$)")
    matches = [f for f in findings if pattern.search(f.summary)]
    assert len(matches) == 1, [f.summary for f in findings]
    return matches[0]


def test_report_counts_every_outcome_once(shapes):
    _, _, report = shapes
    assert report.ran is True
    assert report.collected == 18
    assert report.passed == 1
    assert report.failed == 6
    assert report.errored == 3        # the fixture error and two uncollectable modules
    assert report.skipped == 8
    assert report.xfailed == 1
    assert report.xpassed == 1
    assert report.pytest_exit == 1


def test_every_not_passing_test_gets_exactly_one_finding(shapes):
    _, findings, _ = shapes
    kinds = {k: len(v) for k, v in _kinds(findings).items()}
    assert kinds == {
        "failing test": 5,
        "flaky test": 1,
        "blocked test": 3,
        "skipped without a dependency reason": 2,
        "stale skip": 2,
        "skipped for a dependency": 4,
        "stale xfail": 1,
    }
    assert len(findings) == 18
    assert all(f.category == Category.TEST_STATUS for f in findings)
    assert all(f.status == Status.CONFIRMED for f in findings)
    assert all(f.layer.value == "mechanical" for f in findings)


def test_passing_and_expected_failing_tests_produce_nothing(shapes):
    _, findings, _ = shapes
    assert not any("test_passes" in f.summary for f in findings)
    assert not any("test_xfail_fails" in f.summary for f in findings)


def test_deterministic_failure_is_rerun_the_default_three_times(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_fails_for_real")
    assert f.summary.startswith("failing test:")
    assert f.severity == Severity.MAJOR
    assert "Rerun alone 3 time(s) and failed every time" in f.detail
    assert "assert 1 == 2" in f.detail


def test_reruns_are_counted(shapes):
    _, _, report = shapes
    # fails_for_real 3 + token_math 3 + handles_refusal 3 + setup_error 3 + flaky 1;
    # blocked and collection errors are not rerun.
    assert report.reruns_performed == 13
    assert report.flaky == 1
    assert report.blocked == 3        # two failures and the uncollectable module
    assert report.stale_skips == 2
    assert report.unjustified_skips == 2
    assert report.dependency_skips == 4


def test_flaky_test_is_the_one_that_passed_on_isolated_rerun(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_flaky[a b]")
    assert f.summary.startswith("flaky test:")
    assert f.severity == Severity.MAJOR
    assert "passes when rerun alone" in f.summary
    assert "rerun 1 of 3" in f.detail
    # The attempt number lives in the detail, never the summary, so the
    # finding id does not change with how many attempts it took.
    assert "of 3" not in f.summary


def test_failure_whose_source_mentions_a_service_word_is_still_failing(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_token_math")
    assert f.summary.startswith("failing test:")
    assert f.severity == Severity.MAJOR


def test_failure_whose_source_handles_a_dependency_exception_is_still_failing(shapes):
    # Found by the hand-mutant suite: with the whole traceback classified
    # instead of its error lines, nothing in the fixture project could tell
    # the difference. This test can.
    _, findings, _ = shapes
    f = _named(findings, "test_handles_refusal_then_fails")
    assert f.summary.startswith("failing test:")
    assert "assert True is False" in f.detail


def test_missing_module_is_blocked_named_and_not_rerun(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_blocked_module")
    assert f.summary.startswith("blocked test:")
    assert f.severity == Severity.MINOR
    assert "module 'definitely_not_a_module_ghost_xyz'" in f.summary
    assert "not rerun" in f.detail
    assert "Nothing was installed" in f.detail


def test_refused_connection_is_blocked_by_a_service(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_blocked_service")
    assert f.summary.startswith("blocked test:")
    assert "service" in f.summary
    assert "ConnectionRefusedError" in f.detail


def test_setup_error_is_a_failing_test_in_setup(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_setup_error")
    assert f.summary == "failing test: tests/test_shapes.py::test_setup_error errors in setup"
    assert "fixture broke" in f.detail


def test_collection_error_names_the_missing_module(shapes):
    _, findings, _ = shapes
    f = _named(findings, "tests/test_collect_error.py")
    assert f.summary.startswith("blocked test:")
    assert "cannot be collected" in f.summary
    assert "definitely_not_a_module_ghost_collect" in f.summary
    assert f.evidence.file.endswith("tests/test_collect_error.py")


def test_collection_error_for_a_module_in_the_repository_is_a_path_defect(shapes):
    # Measured on gsa-815: 17 of 19 test modules failed to collect for
    # modules that were all files in the same repository. That is not a
    # missing dependency and must not read as blocked.
    _, findings, report = shapes
    f = _named(findings, "tests/test_local_import.py")
    assert f.summary.startswith("failing test:")
    assert "module 'helper_local_ghost' is in this repository but not on the import path" in f.summary
    assert f.severity == Severity.MAJOR
    assert "src/helper_local_ghost.py" in f.detail
    assert "Not rerun" in f.detail
    assert report.blocked == 3


def test_skip_naming_a_sibling_checkout_is_a_resource_dependency(shapes):
    # Measured on observe-perceive: 47 skips of the form "<repo> checkout
    # not available", all read as naming no dependency before this pattern.
    _, findings, _ = shapes
    f = _named(findings, "test_skip_sibling_checkout")
    assert f.summary.startswith("skipped for a dependency:")
    assert "resource 'AUGUR'" in f.summary
    assert f.severity == Severity.INFORMATIONAL


def test_skip_with_no_reason_is_major(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_skip_no_reason")
    assert f.summary.endswith("is skipped with no reason")
    assert f.severity == Severity.MAJOR


def test_skip_with_a_todo_reason_is_major(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_skip_todo")
    assert f.summary.startswith("skipped without a dependency reason:")
    assert "TODO: fix later" in f.summary
    assert f.severity == Severity.MAJOR
    assert "switched off" in f.detail


def test_skip_naming_a_service_is_informational(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_skip_postgres")
    assert f.summary.startswith("skipped for a dependency:")
    assert f.severity == Severity.INFORMATIONAL
    assert "cannot be probed" in f.detail


def test_importorskip_reason_is_a_dependency_skip_with_the_module_named(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_importorskip")
    assert f.severity == Severity.INFORMATIONAL
    assert "module 'definitely_not_a_module_ghost_abc'" in f.summary
    assert "is absent here" in f.detail


def test_skip_naming_a_module_that_imports_is_stale(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_skip_stale_module")
    assert f.summary.startswith("stale skip:")
    assert "module 'json'" in f.summary
    assert "which is present" in f.summary
    assert f.severity == Severity.MAJOR


def test_skip_naming_a_set_env_var_is_stale_and_an_unset_one_is_not(shapes):
    _, findings, _ = shapes
    stale = _named(findings, "test_skip_stale_env")
    absent = _named(findings, "test_skip_absent_env")
    assert stale.summary.startswith("stale skip:")
    assert f"env '{STALE_ENV}'" in stale.summary
    assert absent.summary.startswith("skipped for a dependency:")
    assert f"env '{ABSENT_ENV}'" in absent.summary
    assert absent.severity == Severity.INFORMATIONAL


def test_unexpected_xfail_pass_is_a_stale_expectation(shapes):
    _, findings, _ = shapes
    f = _named(findings, "test_xpass")
    assert f.summary == "stale xfail: tests/test_shapes.py::test_xpass passes"
    assert f.severity == Severity.MAJOR


def test_evidence_points_at_the_test_definition(shapes):
    proj, findings, _ = shapes
    f = _named(findings, "test_fails_for_real")
    assert f.evidence.file.endswith("tests/test_shapes.py")
    assert f.evidence.absolute_file is None or f.evidence.absolute_file.startswith(str(proj))
    assert f.evidence.line_start == SHAPES.splitlines().index("def test_fails_for_real():") + 1
    assert f.evidence.snippet == "tests/test_shapes.py::test_fails_for_real"


def test_finding_ids_are_unique(shapes):
    _, findings, _ = shapes
    assert len({f.id for f in findings}) == len(findings)


def test_render_report_summarises_the_run(shapes):
    _, _, report = shapes
    line = render_report(report)
    assert line.startswith("ghost_buster: test scan ran 18 collected, 1 passed, 6 failed, 3 errored, 8 skipped")
    assert "(13 rerun(s))" in line
    assert "1 flaky" in line
    assert "3 blocked by a dependency" in line
    assert "2 stale skip(s)" in line


def test_scan_writes_nothing_into_the_project(tmp_path, monkeypatch):
    # The ambient environment must not be what suppresses bytecode, or this
    # asserts nothing. Found by running ghost_buster --tests on ghost_tools
    # itself: that run exports PYTHONDONTWRITEBYTECODE for the whole suite,
    # the nested mutation harness inherited it, and the mutant that deletes
    # testsuite.py's own export survived -- the test had been passing on the
    # environment's behaviour rather than the code's.
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    proj = _project(tmp_path, {"test_ok.py": "def test_ok():\n    assert True\n"})
    findings, report = scan(proj)
    assert findings == []
    assert report.ran is True
    assert report.passed == 1
    assert not (proj / ".pytest_cache").exists()
    assert not list(proj.rglob("__pycache__"))


def test_reruns_zero_reports_the_failure_without_rerunning(tmp_path):
    proj = _project(tmp_path, {"test_bad.py": "def test_bad():\n    assert False\n"})
    findings, report = scan(proj, reruns=0)
    assert len(findings) == 1
    assert findings[0].summary.startswith("failing test:")
    assert "Not rerun (reruns=0)" in findings[0].detail
    assert report.reruns_performed == 0


def test_directory_with_no_tests_did_not_run(tmp_path):
    (tmp_path / "README.md").write_text("nothing here\n")
    findings, report = scan(tmp_path)
    assert findings == []
    assert report.ran is False
    assert "no tests collected" in report.reason
    assert render_report(report).startswith("ghost_buster: test scan did not run:")


def test_interpreter_without_pytest_did_not_run(tmp_path):
    proj = _project(tmp_path, {"test_ok.py": "def test_ok():\n    assert True\n"})
    findings, report = scan(proj, python="/bin/false")
    assert findings == []
    assert report.ran is False
    assert "pytest is not importable" in report.reason


def test_suite_that_exceeds_the_timeout_did_not_run(tmp_path):
    proj = _project(tmp_path, {"test_slow.py": "import time\n\ndef test_slow():\n    time.sleep(3)\n"})
    findings, report = scan(proj, timeout=1.0)
    assert findings == []
    assert report.ran is False
    assert "did not finish" in report.reason
    assert "timed out" in report.reason


def test_cli_tests_flag_runs_the_suite_and_reports(tmp_path, capsys):
    proj = _project(tmp_path, {"test_bad.py": "def test_bad():\n    assert False\n"})
    (proj / "module.py").write_text("x = 1\n")
    rc = main([str(proj), "--tests", "--tests-reruns", "1", "--json",
               "--baseline", str(tmp_path / "b.json")])
    out, err = capsys.readouterr()
    assert rc == 1
    assert "ghost_buster: test scan ran 1 collected, 0 passed, 1 failed (1 rerun(s))" in err
    assert '"detector": "test_status"' in out


def test_cli_without_tests_flag_never_runs_the_suite(tmp_path, capsys):
    proj = _project(tmp_path, {"test_bad.py": "def test_bad():\n    assert False\n"})
    (proj / "module.py").write_text("x = 1\n")
    rc = main([str(proj), "--json", "--baseline", str(tmp_path / "b.json")])
    out, err = capsys.readouterr()
    assert rc == 0
    assert "test scan" not in err
    assert "test_status" not in out


@pytest.mark.parametrize("reason,kind,name", [
    ("requires Postgres", "service", ""),
    ("requires DATABASE_URL", "env", "DATABASE_URL"),
    ("needs numpy installed", "module", "numpy"),
    ("could not import 'yaml': No module named 'yaml'", "module", "yaml"),
    ("docker only", "service", ""),
    ("no network in CI", "service", ""),
    ("Windows only", "platform", ""),
    ("set $API_TOKEN to run", "env", "API_TOKEN"),
    ("AUGUR checkout not available", "resource", "AUGUR"),
    ("fixture data unavailable", "resource", ""),
])
def test_reason_classifier_names_the_dependency(reason, kind, name):
    dep = classify_dependency(reason)
    assert dep is not None, reason
    assert (dep.kind, dep.name) == (kind, name)


@pytest.mark.parametrize("reason", ["", "TODO", "broken since the refactor", "flaky, see #12"])
def test_reason_classifier_finds_nothing_in_a_reason_naming_nothing(reason):
    assert classify_dependency(reason) is None


def test_failure_classifier_reads_only_the_error_lines():
    traceback = (
        "    def test_server_roundtrip():\n"
        "        server = make_server()\n"
        "        token = server.issue_token()\n"
        "        try:\n"
        "            server.ping()\n"
        "        except ConnectionRefusedError:\n"
        "            token = None\n"
        ">       assert token == 'expected'\n"
        "E       AssertionError: assert 'actual' == 'expected'\n"
        "\n"
        "tests/test_server.py:12: AssertionError\n"
    )
    assert classify_dependency(traceback, failure=True) is None
    assert classify_dependency(traceback) is not None  # the broad tier would have matched


@pytest.mark.parametrize("line,kind,name", [
    ("E   ModuleNotFoundError: No module named 'psycopg2'", "module", "psycopg2"),
    ("E   KeyError: 'DATABASE_URL'", "env", "DATABASE_URL"),
    ("E   redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379", "service", ""),
    ("E   FileNotFoundError: [Errno 2] No such file or directory: 'terraform'", "tool", "terraform"),
    ("E   FileNotFoundError: [Errno 2] No such file or directory: '/usr/local/bin/twin_ensure_services'",
     "tool", "twin_ensure_services"),
])
def test_failure_classifier_recognises_the_usual_shapes(line, kind, name):
    dep = classify_dependency("    something()\n" + line + "\n\ntests/test_x.py:3: Error\n", failure=True)
    assert dep is not None
    assert (dep.kind, dep.name) == (kind, name)


def test_failure_classifier_does_not_call_a_missing_fixture_file_a_tool():
    # Measured on sentinel_os: 18 setup errors on a missing executable under
    # /usr/local/bin are a tool dependency. A missing relative data file is
    # the repository's own defect, not something the environment lacks.
    text = ("E   FileNotFoundError: [Errno 2] No such file or directory: 'tests/fixtures/expected.json'\n"
            "tests/test_x.py:3: FileNotFoundError\n")
    assert classify_dependency(text, failure=True) is None


def test_scan_uses_the_given_interpreter(tmp_path):
    proj = _project(tmp_path, {"test_ok.py": "def test_ok():\n    assert True\n"})
    _, report = scan(proj, python=sys.executable)
    assert report.python == sys.executable
    assert report.ran is True


def test_local_module_index_finds_files_and_packages_and_skips_environments(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "flat.py").write_text("")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "notpkg").mkdir()
    (tmp_path / "notpkg" / "thing.py").write_text("")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "vendored.py").write_text("")
    index = _index_local_modules(tmp_path)
    assert index["flat"] == "src/flat.py"
    assert index["pkg"] == "pkg"
    assert index["thing"] == "notpkg/thing.py"
    assert "notpkg" not in index
    assert "vendored" not in index
    assert "__init__" not in index
