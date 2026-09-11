"""Consent before a scan runs somebody else's code (ghost_buster/trust.py).

The scans that execute the target's code -- the test suite, and the
mutants under --mutate -- run only for a repository whose consent is on
record in a store that belongs to the user. Everything else runs as
before, and a declined scan leaves a receipt.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from ghost_buster import trust
from ghost_buster.cli import main


def _git_repo(path, remote=None):
    path.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if remote:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True)
    return path


@pytest.fixture
def store(tmp_path, monkeypatch):
    p = tmp_path / "trust.json"
    monkeypatch.setenv(trust.ENV, str(p))
    return p


def test_identity_is_the_normalised_remote(tmp_path):
    for url in ("https://github.com/Owner/Repo.git", "git@github.com:owner/repo.git",
                "ssh://git@github.com/owner/repo", "https://github.com/owner/repo/"):
        repo = _git_repo(tmp_path / url.replace("/", "_").replace(":", "_"), url)
        assert trust.identity(repo) == "github.com/owner/repo", url


def test_a_tree_with_no_remote_is_identified_by_its_path(tmp_path):
    repo = _git_repo(tmp_path / "local")
    assert trust.identity(repo) == str(repo.resolve())
    plain = tmp_path / "plain"
    plain.mkdir()
    assert trust.identity(plain) == str(plain.resolve())


def test_nothing_is_trusted_until_granted(store, tmp_path):
    repo = _git_repo(tmp_path / "r", "https://github.com/o/r.git")
    before = trust.check(repo)
    assert before.trusted is False
    assert "github.com/o/r" in before.reason and str(store) in before.reason
    granted = trust.grant(repo)
    assert granted.trusted is True
    after = trust.check(repo)
    assert after.trusted is True and "consent recorded" in after.reason
    assert json.loads(store.read_text())["github.com/o/r"]["granted"]


def test_a_fresh_clone_of_a_trusted_remote_is_trusted(store, tmp_path):
    a = _git_repo(tmp_path / "a", "git@github.com:o/r.git")
    b = _git_repo(tmp_path / "b", "https://github.com/O/R")
    trust.grant(a)
    assert trust.check(b).trusted is True


def test_a_corrupt_store_trusts_nothing(store, tmp_path):
    store.write_text("{not json")
    repo = _git_repo(tmp_path / "r", "https://github.com/o/r")
    assert trust.check(repo).trusted is False


def test_the_env_override_trusts_everything_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv(trust.ENV, trust.TRUST_ALL)
    repo = _git_repo(tmp_path / "r", "https://github.com/o/r")
    verdict = trust.check(repo)
    assert verdict.trusted is True and verdict.store is None
    assert trust.ENV in verdict.reason


# ---------------------------------------------------------------- the CLI

def _project(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "module.py").write_text("x = 1\n")
    (proj / "test_bad.py").write_text("def test_bad():\n    assert False\n")
    return proj


QUIET = ["--no-branches", "--no-secrets", "--no-project", "--no-correlate", "--no-ledger", "--single-repo"]


def test_an_untrusted_repository_does_not_have_its_tests_run(store, tmp_path, capsys):
    proj = _project(tmp_path)
    rc = main([str(proj), *QUIET, "--json", "--baseline", str(tmp_path / "b.json")])
    out, err = capsys.readouterr()
    assert "test status scan DECLINED" in err
    assert "--trust records consent once" in err
    assert '"detector": "test_status"' not in out
    assert rc == 0, "a declined scan is not a finding"


def test_trust_records_consent_and_runs_the_suite(store, tmp_path, capsys):
    proj = _project(tmp_path)
    rc = main([str(proj), *QUIET, "--trust", "--json", "--baseline", str(tmp_path / "b.json")])
    out, err = capsys.readouterr()
    assert "ghost_buster: trust:" in err and "consent recorded now" in err
    assert "test scan ran 1 collected" in err
    assert '"detector": "test_status"' in out and rc == 1
    # and it sticks: the next run needs no flag
    main([str(proj), *QUIET, "--json", "--baseline", str(tmp_path / "b.json")])
    _, err2 = capsys.readouterr()
    assert "test scan ran 1 collected" in err2 and "DECLINED" not in err2


def test_an_untrusted_repository_does_not_have_its_mutants_run(store, tmp_path, capsys):
    proj = _project(tmp_path)
    (proj / "mod.py").write_text("def ok(x):\n    return x > 0\n")
    (proj / "test_weak.py").write_text("from mod import ok\n\ndef test_weak():\n    assert ok(5) is not None\n")
    main([str(proj), *QUIET, "--no-tests", "--mutate", "--json", "--baseline", str(tmp_path / "b.json")])
    out, err = capsys.readouterr()
    assert "mutation analysis DECLINED" in err
    assert "vacuous_check" not in out


def test_no_tests_still_declines_on_purpose_with_its_own_receipt(store, tmp_path, capsys):
    proj = _project(tmp_path)
    main([str(proj), *QUIET, "--no-tests", "--json", "--baseline", str(tmp_path / "b.json")])
    _, err = capsys.readouterr()
    assert "test status scan SKIPPED at your request (--no-tests)" in err
    assert "DECLINED" not in err
