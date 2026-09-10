"""Tests for ghost_buster/secrets.py, exercised against real git repositories
built in tmp_path and the real `gitleaks` binary -- like test_branches.py,
there is no honest way to test a git-history scan against parsed strings.

Requires gitleaks on PATH. Skipped entirely otherwise (CI installs it; see
.github/workflows/tests.yml), the same shape as any test that needs a real
external tool this project does not vendor.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ghost_buster.cli import main
from ghost_buster.schema import Category, Severity, Status
from ghost_buster.secrets import render_report, scan

pytestmark = pytest.mark.skipif(
    shutil.which("gitleaks") is None,
    reason="gitleaks is not installed; install it to run this detector's test suite "
           "(https://github.com/gitleaks/gitleaks#installing)",
)

AWS_KEY = "AKIAABCDEFGHIJKLMNOP"  # gitleaks:allow -- fixture, not a real key


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "a.txt").write_text("one\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-q", "-m", "initial")
    return path


def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content)
    _git(repo, "add", filename)
    _git(repo, "commit", "-q", "-m", message)


def test_clean_repo_reports_zero_findings(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    findings, report = scan(repo)
    assert findings == []
    assert report.ran is True
    assert report.leaks_found == 0
    assert render_report(report) == \
        f"ghost_buster: secrets scan ({report.gitleaks_version}) found 0 committed secrets"


def test_committed_secret_is_flagged_even_after_removal_from_head(tmp_path):
    # The exact shape this module exists to catch: a secret committed, then
    # "fixed" by deleting the line in a later commit. Still exposed via
    # history; must still be flagged.
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "config.py", f"AWS_KEY = '{AWS_KEY}'\n", "add key")
    _commit(repo, "config.py", "AWS_KEY = None\n", "remove key from HEAD")

    findings, report = scan(repo)

    assert report.ran is True
    assert len(findings) == 1
    f = findings[0]
    assert f.category == Category.COMMITTED_SECRET
    assert f.layer.value == "mechanical"
    assert f.severity == Severity.CRITICAL
    assert f.status == Status.CONFIRMED
    assert "aws-access-token" in f.summary
    assert "config.py" in f.summary
    assert f.evidence.file.endswith("config.py")
    assert f.evidence.line_start == 1


def test_secret_value_never_appears_in_the_finding(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "config.py", f"AWS_KEY = '{AWS_KEY}'\n", "add key")

    findings, _ = scan(repo)

    assert len(findings) == 1
    f = findings[0]
    blob = json.dumps(f.as_dict())
    assert AWS_KEY not in blob
    assert "REDACTED" not in blob  # not even the redaction placeholder leaks through


def test_secret_reintroduced_touches_the_same_line_only_once(tmp_path):
    # A later commit that does not touch the line carrying the secret must
    # not re-report it -- gitleaks scans added diff lines, not full file
    # content at every commit.
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "config.py", f"AWS_KEY = '{AWS_KEY}'\n", "add key")
    _commit(repo, "other.py", "x = 1\n", "unrelated change")

    findings, _ = scan(repo)

    assert len(findings) == 1


def test_finding_id_is_stable_across_repeated_scans(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "config.py", f"AWS_KEY = '{AWS_KEY}'\n", "add key")

    first, _ = scan(repo)
    second, _ = scan(repo)

    assert first[0].id == second[0].id


def test_two_distinct_commits_of_the_same_secret_are_two_findings(tmp_path):
    # Genuinely two separate exposure events -- both need purging from
    # history -- so both must be visible, with distinct ids.
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "config.py", f"AWS_KEY = '{AWS_KEY}'\n", "add key")
    _commit(repo, "config.py", "AWS_KEY = None\n", "remove")
    _commit(repo, "config.py", f"AWS_KEY = '{AWS_KEY}'\n", "re-add key, same value")

    findings, report = scan(repo)

    assert report.leaks_found == 2
    assert len({f.id for f in findings}) == 2


def test_gitleaksignore_suppresses_a_fingerprint_at_the_source(tmp_path):
    # gitleaks' own suppression mechanism, honored as-is -- no extra
    # suppression logic lives in this module.
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "config.py", f"AWS_KEY = '{AWS_KEY}'\n", "add key")
    first, _ = scan(repo)
    assert len(first) == 1

    fingerprint = first[0].detail.rsplit("gitleaks fingerprint: ", 1)[1].strip()
    (repo / ".gitleaksignore").write_text(fingerprint + "\n")
    _git(repo, "add", ".gitleaksignore")
    _git(repo, "commit", "-q", "-m", "ignore known-rotated key")

    findings, report = scan(repo)

    assert findings == []
    assert report.ran is True


def test_relative_root_from_an_unrelated_working_directory_still_finds_the_repo(tmp_path, monkeypatch):
    # A real bug caught by dogfooding this detector across a library of
    # repos: gitleaks was given `--source <root>` while the subprocess's
    # own cwd was ALSO set to `root`. With a relative root ("ats", say)
    # that resolves the path twice (root/root), which does not exist, and
    # gitleaks fails the whole scan rather than silently misreading it --
    # still a real defect, since a caller has no reason to expect a
    # relative path to behave differently from an absolute one.
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "config.py", f"AWS_KEY = '{AWS_KEY}'\n", "add key")
    monkeypatch.chdir(tmp_path)

    findings, report = scan(Path("repo"))

    assert report.ran is True
    assert len(findings) == 1


def test_non_git_directory_does_not_read_as_a_clean_scan(tmp_path):
    # The false-negative gitleaks itself is prone to (see module docstring):
    # confirm the wrapper's own precondition check catches it.
    findings, report = scan(tmp_path)
    assert findings == []
    assert report.ran is False
    assert "not a git repository" in report.reason


def test_missing_gitleaks_binary_does_not_read_as_a_clean_scan(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    findings, report = scan(repo, gitleaks_path="/no/such/gitleaks-binary")
    assert findings == []
    assert report.ran is False
    assert "gitleaks could not be run" in report.reason
    assert render_report(report).startswith("ghost_buster: secrets scan did not run:")


def test_bad_source_path_does_not_read_as_a_clean_scan(tmp_path):
    # A real gitleaks failure (confirmed separately to exit non-zero even
    # with --exit-code 0 in effect) must not read as zero findings.
    repo = _init_repo(tmp_path / "repo")
    findings, report = scan(repo / "does-not-exist")
    assert findings == []
    assert report.ran is False


def test_timeout_does_not_read_as_a_clean_scan(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    findings, report = scan(repo, timeout=0.0001)
    assert findings == []
    assert report.ran is False
    assert "did not finish" in report.reason


def test_cli_secrets_flag_runs_the_scan_and_reports(tmp_path, capsys):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "config.py", f"AWS_KEY = '{AWS_KEY}'\n", "add key")
    rc = main([str(repo), "--secrets", "--json", "--baseline", str(tmp_path / "b.json")])
    out, err = capsys.readouterr()
    assert rc == 1
    assert "ghost_buster: secrets scan" in err
    assert "found 1 committed secret" in err
    assert '"detector": "committed_secret"' in out
    assert AWS_KEY not in out
    assert AWS_KEY not in err


def test_cli_without_secrets_flag_never_runs_the_scan(tmp_path, capsys):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "config.py", f"AWS_KEY = '{AWS_KEY}'\n", "add key")
    (repo / "module.py").write_text("x = 1\n")
    rc = main([str(repo), "--json", "--baseline", str(tmp_path / "b.json")])
    out, err = capsys.readouterr()
    assert rc == 0
    assert "secrets scan" not in err
    assert "committed_secret" not in out


def test_multiple_rules_or_lines_in_one_commit_are_distinct_findings(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(
        repo, "config.py",
        f"AWS_KEY = '{AWS_KEY}'\nGH_TOKEN = 'ghp_1234567890abcdefghijklmnopqrstuvwxyz'\n",  # gitleaks:allow
        "add two secrets",
    )

    findings, report = scan(repo)

    assert report.leaks_found == 2
    assert len({f.id for f in findings}) == 2


def test_two_secrets_on_one_line_are_distinct_findings(tmp_path):
    # gitleaks' own Fingerprint is file:rule:line -- it does not include
    # column, so two matches of the same rule on one line share a
    # fingerprint. Confirmed directly: without column in the summary (and
    # so in the finding id), these two real, distinct leaks collide into
    # one id and the baseline would only ever remember one of them.
    repo = _init_repo(tmp_path / "repo")
    second_key = "AKIAZYXWVUTSRQPONMLK"  # gitleaks:allow -- fixture, not a real key
    _commit(repo, "two.py", f"A='{AWS_KEY}'; B='{second_key}'\n", "two keys one line")

    findings, report = scan(repo)

    assert report.leaks_found == 2
    assert len({f.id for f in findings}) == 2


def _fake_binary(path, script: str) -> str:
    path.write_text(script)
    path.chmod(0o755)
    return str(path)


def test_gitleaks_not_on_path_does_not_read_as_a_clean_scan(tmp_path, monkeypatch):
    # gitleaks IS installed on this machine (the module skip guarantees
    # it), so this exercises the "not found" branch directly rather than
    # relying on the environment lacking it.
    import shutil as shutil_module
    monkeypatch.setattr(shutil_module, "which", lambda name: None)
    repo = _init_repo(tmp_path / "repo")

    findings, report = scan(repo)

    assert findings == []
    assert report.ran is False
    assert "gitleaks is not installed" in report.reason


def test_gitleaks_non_zero_exit_does_not_read_as_a_clean_scan(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    fake = _fake_binary(tmp_path / "fake-gitleaks", "#!/bin/sh\necho 'internal boom' >&2\nexit 2\n")

    findings, report = scan(repo, gitleaks_path=fake)

    assert findings == []
    assert report.ran is False
    assert "gitleaks exited 2" in report.reason
    assert "internal boom" in report.reason


def test_gitleaks_exiting_clean_with_no_report_file_does_not_read_as_a_clean_scan(tmp_path):
    # A real gitleaks always writes --report-path on a normal exit; this
    # proves the wrapper does not just trust a zero exit code.
    repo = _init_repo(tmp_path / "repo")
    fake = _fake_binary(tmp_path / "fake-gitleaks", "#!/bin/sh\nexit 0\n")

    findings, report = scan(repo, gitleaks_path=fake)

    assert findings == []
    assert report.ran is False
    assert "no report file" in report.reason


def test_invalid_json_report_does_not_read_as_a_clean_scan(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    fake = _fake_binary(
        tmp_path / "fake-gitleaks",
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "path = sys.argv[sys.argv.index('--report-path') + 1]\n"
        "open(path, 'w').write('not valid json{')\n",
    )

    findings, report = scan(repo, gitleaks_path=fake)

    assert findings == []
    assert report.ran is False
    assert "not valid JSON" in report.reason
