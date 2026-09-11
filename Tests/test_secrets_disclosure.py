"""What the target told the scanner to ignore is part of the evidence.

gitleaks honors a repository's own `.gitleaksignore` and `.gitleaks.toml`
before this module sees a finding. For a developer scanning their own
project that is right: a fingerprint they triaged once should stay quiet.
When the question is somebody else's repository it means the subject of
the examination configures the examiner, and until this existed it did so
silently -- a scan of a repository with a suppressed leak and a scan of a
repository with no leak printed the same line.

The configuration is not disabled. It is named, with the count, beside
the number it changed, together with how far the scan itself reached.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ghost_buster.secrets import (
    SUPPRESSION_FILES, SecretsScanReport, render_report, scan, target_suppression,
)

#: A value gitleaks reports as generic-api-key. Not a live credential:
#: random characters chosen to have the shape the rule looks for.
PLANTED = 's3cr3t-Kx91ZqW4vBn7TjLp0RdYcM2eHgUa'

gitleaks = pytest.mark.skipif(shutil.which("gitleaks") is None,
                              reason="gitleaks is not installed")


def _repo(root: Path, files: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    def git(*a):
        subprocess.run(["git", "-C", str(root), *a], capture_output=True, check=False)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    for name, body in files.items():
        (root / name).write_text(body)
    git("add", "-A")
    git("commit", "-q", "-m", "commit")
    return root


# ------------------------------------------------------- what is detected

def test_a_repository_with_no_suppression_says_so(tmp_path):
    assert target_suppression(_repo(tmp_path / "clean", {"a.py": "x = 1\n"})) == {}


def test_an_ignore_list_is_found_and_its_entries_counted(tmp_path):
    root = _repo(tmp_path / "quiet", {
        "a.py": "x = 1\n",
        ".gitleaksignore": "# a triaged false positive\nabc:conf.py:generic-api-key:1\ndef:conf.py:generic-api-key:2\n",
    })
    assert target_suppression(root) == {".gitleaksignore": 2}, (
        "comments and blank lines are not fingerprints"
    )


def test_a_config_file_is_found_but_its_rules_are_not_counted(tmp_path):
    root = _repo(tmp_path / "conf", {"a.py": "x = 1\n", ".gitleaks.toml": "[extend]\nuseDefault = true\n"})
    assert target_suppression(root) == {".gitleaks.toml": None}, (
        "a toml's rules are not a list, and inventing a count would be worse than none"
    )


def test_every_name_the_module_claims_to_look_for_is_looked_for(tmp_path):
    for name in SUPPRESSION_FILES:
        root = _repo(tmp_path / f"r-{name}", {"a.py": "x = 1\n", name: "x\n"})
        assert name in target_suppression(root)


# ------------------------------------------------------- what is disclosed

def test_the_receipt_names_the_suppression_and_the_scope():
    report = SecretsScanReport(ran=True, leaks_found=0, gitleaks_version="8.21.2",
                               suppression={".gitleaksignore": 2},
                               scope="scanned the checked-out branch's own history, not every ref")
    line = render_report(report)
    assert "found 0 committed secrets" in line
    assert ".gitleaksignore (2 entries)" in line
    assert "not every ref" in line


def test_the_receipt_says_so_when_there_is_no_suppression():
    report = SecretsScanReport(ran=True, leaks_found=1, scope="scanned one branch")
    assert "configures no suppression" in render_report(report)


def test_one_entry_is_not_pluralised():
    report = SecretsScanReport(ran=True, suppression={".gitleaksignore": 1})
    assert "(1 entry)" in render_report(report)


def test_a_scan_that_did_not_run_discloses_nothing_it_did_not_establish():
    report = SecretsScanReport(ran=False, reason="gitleaks is not installed")
    assert "suppression" not in render_report(report)


# --------------------------------------------- the reason this exists at all

@gitleaks
def test_a_suppressed_leak_disappears_and_the_receipt_says_the_target_did_it(tmp_path):
    """The whole case, end to end: the same repository, scanned twice, with
    the only difference being a file the target added to silence the
    finding. Before this, both scans printed the same line."""
    root = _repo(tmp_path / "target", {"conf.py": f'api_key = "{PLANTED}"\n'})

    first, before = scan(root)
    assert len(first) == 1, "the fixture is meant to hold one detectable leak"
    fingerprint = next(line.split("fingerprint: ")[1].strip()
                       for line in first[0].detail.splitlines() if "gitleaks fingerprint:" in line)
    assert not before.suppressed_by_target
    assert "configures no suppression" in render_report(before)

    (root / ".gitleaksignore").write_text(fingerprint + "\n")
    second, after = scan(root)

    assert second == [], "the fixture is meant to silence the finding"
    assert after.leaks_found == 0
    assert after.suppressed_by_target
    assert ".gitleaksignore (1 entry)" in render_report(after), (
        "a clean result that the target arranged reads exactly like a clean "
        "result, unless the receipt says who arranged it"
    )


@gitleaks
def test_the_scope_is_stated_on_every_run_that_ran(tmp_path):
    root = _repo(tmp_path / "scoped", {"a.py": "x = 1\n"})
    _, report = scan(root)
    assert report.ran and "not every ref" in report.scope
