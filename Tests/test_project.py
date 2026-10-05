"""Repository-shaped facts, and the noise this check refuses to make.

The failure mode for a "no CI" check is not missing a repository. It is
firing on every scratch pad, spike and data corpus until people stop
reading the output. So most of these tests are about SILENCE: what the
check declines to say, and why.
"""
from __future__ import annotations

import pytest

from ghost_buster.cli import main
from ghost_buster.project import find_ci_config, render_report, scan
from ghost_buster.schema import Severity

WORKFLOW = "name: t\non: [push]\njobs:\n  t:\n    runs-on: ubuntu-latest\n"


def _repo(tmp_path, *, ci=None, deploy=(), tests=0, empty_workflows=False):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "m.py").write_text("x = 1\n")
    if ci == "github":
        d = root / ".github" / "workflows"
        d.mkdir(parents=True)
        (d / "tests.yml").write_text(WORKFLOW)
    elif ci:
        (root / ci).write_text("pipeline\n")
    if empty_workflows:
        (root / ".github" / "workflows").mkdir(parents=True)
    for name in deploy:
        (root / name).write_text("FROM scratch\n")
    for i in range(tests):
        (root / f"test_{i}.py").write_text("def test_x():\n    assert True\n")
    return root


def _kinds(findings):
    return {f.attributes["kind"] for f in findings}


# ------------------------------------------------------------ it stays quiet

def test_a_repo_with_ci_is_not_reported(tmp_path):
    findings, report = scan(_repo(tmp_path, ci="github", deploy=["Dockerfile"], tests=3))
    assert findings == []
    assert report.has_ci


def test_a_repo_with_neither_tests_nor_a_deploy_artifact_is_not_reported(tmp_path):
    """A scratch pad, a spike, a corpus. "No CI" is true and not worth
    saying. Reporting these is how the check becomes noise."""
    findings, report = scan(_repo(tmp_path))
    assert findings == []
    assert not report.has_ci


@pytest.mark.parametrize("name", [
    ".gitlab-ci.yml", "Jenkinsfile", ".travis.yml", "azure-pipelines.yml",
    "bitbucket-pipelines.yml", ".drone.yml",
])
def test_ci_is_recognised_wherever_it_lives(tmp_path, name):
    """A GitHub-only check would report every GitLab repository on earth."""
    assert find_ci_config(_repo(tmp_path, ci=name)) == name


@pytest.mark.parametrize("where", [
    ".venv/lib/site-packages/dep",
    "node_modules/pkg",
    "tests/fixtures/node_modules/pkg",
    "build/lib/thing",
])
def test_a_vendored_suite_is_not_this_repos_tests(tmp_path, where):
    """The test walk is recursive so that src/thing/tests/test_x.py is
    found. That makes the skip list load-bearing: without it a checkout
    with a virtualenv in it reports thousands of somebody else's tests."""
    root = _repo(tmp_path)
    vendored = root / where
    vendored.mkdir(parents=True)
    (vendored / "test_theirs.py").write_text("def test_x():\n    assert True\n")
    findings, report = scan(root)
    assert report.test_files == 0
    assert findings == []


def test_tests_nested_under_source_are_found(tmp_path):
    """A root-anchored glob misses this layout entirely, and a repository
    that reads as having no tests gets nothing said about it."""
    root = _repo(tmp_path)
    nested = root / "src" / "thing" / "tests"
    nested.mkdir(parents=True)
    (nested / "test_deep.py").write_text("def test_x():\n    assert True\n")
    findings, report = scan(root)
    assert report.test_files == 1
    assert _kinds(findings) == {"tests nobody runs"}


# ------------------------------------------------------------- it speaks up

def test_tests_with_no_ci_are_minor(tmp_path):
    """The claim is about work already done and wasted, not process for
    its own sake."""
    findings, _ = scan(_repo(tmp_path, tests=2))
    assert _kinds(findings) == {"tests nobody runs"}
    assert findings[0].severity == Severity.MINOR
    assert findings[0].attributes["test_files"] == "2"


def test_a_deploy_artifact_with_no_ci_is_major(tmp_path):
    findings, _ = scan(_repo(tmp_path, deploy=["Dockerfile"]))
    assert _kinds(findings) == {"deployable without CI"}
    assert findings[0].severity == Severity.MAJOR


def test_both_are_reported_separately(tmp_path):
    """Two different claims about the same repository. Collapsing them
    would lose the one that matters more."""
    findings, _ = scan(_repo(tmp_path, deploy=["Procfile"], tests=1))
    assert _kinds(findings) == {"deployable without CI", "tests nobody runs"}
    assert {f.severity for f in findings} == {Severity.MAJOR, Severity.MINOR}


def test_an_empty_workflows_directory_is_not_ci(tmp_path):
    """The shape of CI with none of the substance. Counting it as
    configured hides exactly the repository most likely to need this."""
    root = _repo(tmp_path, tests=1, empty_workflows=True)
    findings, report = scan(root)
    assert report.ci_config is None
    assert _kinds(findings) == {"tests nobody runs"}


def test_tests_in_a_tests_directory_are_found(tmp_path):
    root = _repo(tmp_path)
    (root / "tests").mkdir()
    (root / "tests" / "test_pipeline.py").write_text("def test_x():\n    assert True\n")
    findings, report = scan(root)
    assert report.test_files == 1
    assert _kinds(findings) == {"tests nobody runs"}


# ------------------------------------------------------------------- plumbing

def test_a_missing_directory_reports_that_it_could_not_run(tmp_path):
    findings, report = scan(tmp_path / "nope")
    assert findings == []
    assert report.ran is False
    assert "not a directory" in render_report(report)


def test_the_cli_runs_it_by_default(tmp_path, capsys):
    root = _repo(tmp_path, tests=1)
    main([str(root), "--no-tests", "--no-secrets", "--no-branches", "--no-ledger",
          "--baseline", str(tmp_path / "b.json")])
    assert "project scan found no CI configuration" in capsys.readouterr().err


def test_no_project_leaves_a_receipt(tmp_path, capsys):
    root = _repo(tmp_path, tests=1)
    main([str(root), "--no-project", "--no-tests", "--no-secrets", "--no-branches",
          "--no-ledger", "--baseline", str(tmp_path / "b.json")])
    err = capsys.readouterr().err
    assert "project scan SKIPPED at your request (--no-project)" in err
    assert "no CI configuration" not in err


# --------------------------------------- test_config_collects_nothing

PYPROJECT_TESTPATHS = '[tool.pytest.ini_options]\ntestpaths = [{paths}]\n'


def _with_testpaths(tmp_path, paths, *, tests=1, real_dirs=(), ci=None,
                    name="pyproject.toml"):
    root = _repo(tmp_path, tests=tests, ci=ci)
    for d in real_dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
        (root / d / "test_real.py").write_text("def test_r():\n    assert True\n")
    if name == "pyproject.toml":
        written = ", ".join(f'"{p}"' for p in paths)
        (root / name).write_text(PYPROJECT_TESTPATHS.format(paths=written))
    else:
        section = "tool:pytest" if name == "setup.cfg" else "pytest"
        (root / name).write_text(f"[{section}]\ntestpaths = {' '.join(paths)}\n")
    return root


def _by_detector(findings, detector="test_config_collects_nothing"):
    return [f for f in findings if f.detector == detector]


def test_a_testpath_that_does_not_exist_is_major_when_tests_are_in_the_tree(tmp_path):
    """The defect fortress-kernel shipped: testpaths = ["tests"], no tests/
    directory, and a suite at the repository root that a bare `pytest`
    reaches only by falling back out of the configuration."""
    root = _with_testpaths(tmp_path, ["tests"])
    findings, report = scan(root)
    hits = _by_detector(findings)
    assert len(hits) == 1
    assert hits[0].severity is Severity.MAJOR
    assert "tests nobody can collect" in hits[0].summary
    assert report.test_config.collects_nothing


def test_a_testpath_that_exists_says_nothing(tmp_path):
    root = _with_testpaths(tmp_path, ["tests"], real_dirs=["tests"])
    findings, report = scan(root)
    assert not _by_detector(findings)
    assert report.test_config.missing == []


def test_one_missing_path_among_several_is_minor_because_nothing_passes_silently(tmp_path):
    root = _with_testpaths(tmp_path, ["tests", "gone"], real_dirs=["tests"])
    hits = _by_detector(scan(root)[0])
    assert len(hits) == 1
    assert hits[0].severity is Severity.MINOR
    assert "gone" in hits[0].summary


def test_a_repository_with_no_tests_at_all_is_not_reported(tmp_path):
    """testpaths naming a directory that does not exist yet is a plan in a
    repository with no tests. Reporting it is reporting emptiness."""
    root = _with_testpaths(tmp_path, ["tests"], tests=0)
    assert not _by_detector(scan(root)[0])


def test_configuring_no_testpaths_at_all_is_not_a_finding(tmp_path):
    root = _repo(tmp_path, tests=1)
    findings, report = scan(root)
    assert not _by_detector(findings)
    assert report.test_config is None


def test_ci_being_configured_does_not_suppress_it(tmp_path):
    """The opposite: CI is what turns 'collected nothing' into a green
    badge, so the finding matters more here, not less."""
    root = _with_testpaths(tmp_path, ["tests"], ci="github")
    findings, report = scan(root)
    assert report.has_ci
    assert _by_detector(findings)


@pytest.mark.parametrize("name", ["pytest.ini", "tox.ini", "setup.cfg"])
def test_the_ini_style_configuration_files_are_read_too(tmp_path, name):
    root = _with_testpaths(tmp_path, ["tests"], name=name)
    findings, report = scan(root)
    assert report.test_config.source == name
    assert _by_detector(findings)


def test_the_report_line_prints_even_when_nothing_is_wrong(tmp_path):
    """Silence is the defect: a configuration that was checked and is fine
    must not print identically to one nobody looked at."""
    configured = tmp_path / "configured"
    configured.mkdir()
    root = _with_testpaths(configured, ["tests"], real_dirs=["tests"])
    assert "all exist" in render_report(scan(root)[1])
    elsewhere = tmp_path / "bare"
    elsewhere.mkdir()
    bare = _repo(elsewhere, tests=1)
    assert "no testpaths configured" in render_report(scan(bare)[1])
