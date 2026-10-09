"""--json says which checks did not run, and how much it looked at.

The red team's case: an empty findings list with exit 0 was identical
whether every check ran or half of them could not (no git, no gitleaks, an
unparsable file, a detector that raised). The reasons were on stderr only,
and so was the scanned-file count.
"""
from __future__ import annotations

import json
import subprocess

from ghost_buster import cli as buster_cli
from ghost_buster import mechanical

QUIET = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
         "--no-correlate", "--no-ledger", "--no-structure", "--single-repo", "--json"]


def _scan(root, *extra, capsys):
    rc = buster_cli.main([str(root), *extra])
    return rc, json.loads(capsys.readouterr().out)


def _tree(tmp_path, files):
    root = tmp_path / "tgt"
    root.mkdir()
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def _git(root):
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t",
                                                 "commit", "-qm", "x"]):
        subprocess.run(["git", *cmd], cwd=root, check=True, capture_output=True)


def test_json_carries_the_scanned_file_count(tmp_path, capsys):
    root = _tree(tmp_path, {"a.py": "X = 1\n", "b.py": "Y = 2\n", "README.md": "hi\n"})
    _, payload = _scan(root, *QUIET, capsys=capsys)
    assert payload["scan"]["files_scanned"] == 3


def test_files_left_out_by_exclusion_are_counted_as_skipped(tmp_path, capsys):
    root = _tree(tmp_path, {"a.py": "X = 1\n", "venv/lib.py": "Z = 3\n", ".hidden.py": "H = 1\n"})
    _, payload = _scan(root, *QUIET, capsys=capsys)
    assert payload["scan"]["files_scanned"] == 1 and payload["scan"]["files_skipped"] == 2


def test_an_unparsable_file_is_listed_with_its_reason(tmp_path, capsys):
    root = _tree(tmp_path, {"good.py": "X = 1\n", "pkg/bad.py": "def (:\n"})
    _, payload = _scan(root, *QUIET, capsys=capsys)
    assert payload["scan"]["files_unparsable"] == 1
    assert payload["scan"]["unparsable"][0]["file"] == "pkg/bad.py"
    assert payload["scan"]["unparsable"][0]["reason"]
    row = [u for u in payload["unmeasured"] if u["check"] == "parse"][0]
    assert row["by_request"] is False
    assert payload["status"] == "incomplete"


def test_a_check_that_could_not_run_is_unmeasured_with_a_plain_reason(tmp_path, capsys):
    root = _tree(tmp_path, {"a.py": "X = 1\n"})        # not a git repository
    argv = [a for a in QUIET if a != "--no-branches"]
    _, payload = _scan(root, *argv, capsys=capsys)
    row = [u for u in payload["unmeasured"] if u["check"] == "branches"][0]
    assert row["state"] == "could_not_run" and row["by_request"] is False
    assert "git" in row["reason"].lower()
    assert payload["status"] == "incomplete"


def test_a_missing_secrets_tool_is_unmeasured(tmp_path, capsys):
    root = _tree(tmp_path, {"a.py": "X = 1\n"})
    argv = [a for a in QUIET if a != "--no-secrets"]
    _, payload = _scan(root, *argv, "--secrets-binary", str(tmp_path / "no-gitleaks"), capsys=capsys)
    row = [u for u in payload["unmeasured"] if u["check"] == "secrets"][0]
    assert row["state"] == "could_not_run" and row["reason"]
    assert payload["status"] == "incomplete"


def test_a_detector_that_raises_is_reported_and_the_others_still_run(tmp_path, monkeypatch, capsys):
    root = _tree(tmp_path, {"m.py": "def (:\n"})           # unassessable_file fires
    real = mechanical.registered_detectors()

    def explode(_files):
        raise ValueError("kaput")

    monkeypatch.setattr(mechanical, "registered_detectors", lambda: {"explode": explode, **real})
    rc, payload = _scan(root, *QUIET, capsys=capsys)
    assert rc == 1                                           # not a crash
    row = [u for u in payload["unmeasured"] if u["check"] == "structural"][0]
    assert row["state"] == "could_not_run"
    assert row["detail"] == [{"detector": "explode", "error": "ValueError: kaput"}]
    assert any(f["detector"] == "unassessable_file" for f in payload["findings"])
    assert payload["status"] == "incomplete"


def test_checks_the_caller_turned_off_are_listed_but_do_not_make_the_run_incomplete(tmp_path, capsys):
    root = _tree(tmp_path, {"a.py": "X = 1\n"})
    _git(root)
    _, payload = _scan(root, *QUIET, capsys=capsys)
    off = {u["check"]: u for u in payload["unmeasured"]}
    assert off["tests"]["by_request"] is True and off["tests"]["state"] == "declined"
    assert "--no-tests" in off["tests"]["reason"]
    assert off["mutate"]["by_request"] is True
    assert payload["status"] == "ok"
    assert payload["exit_code"] == 0 and payload["error"] is None
