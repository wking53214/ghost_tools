"""`--ledger-path` writes where it is told and invents nothing on the way.

Found by probing the shipped CLI: `--ledger-path /nonexistent/dir/ledger.json`
created `/nonexistent/dir`, silently, because `Ledger.save` made every missing
parent. A mistyped path then built folders wherever it pointed (and, run as a
user who can write there, anywhere on the disk), and the scan reported
success. The rule now: the ledger's folder must exist, or the scan does not
start (exit 2, a plain reason on stderr, the usual error envelope under
--json) and NOTHING is created. `--create-ledger-dir` is the explicit opt-in.
"""
from __future__ import annotations

import json

import pytest

from ghost_buster import cli as buster_cli
from ghost_buster.ledger import Ledger

BASE = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
        "--no-correlate", "--no-structure", "--single-repo"]


def _tree(tmp_path):
    root = tmp_path / "tgt"
    root.mkdir()
    (root / "m.py").write_text("def orphan_one():\n    return 1\n")
    return root


def _run(root, extra, capsys):
    rc = buster_cli.main([str(root), *BASE, *extra])
    out, err = capsys.readouterr()
    return rc, out, err


def test_a_missing_parent_is_a_usage_error_and_nothing_is_created(tmp_path, capsys):
    root = _tree(tmp_path)
    ledger = tmp_path / "does" / "not" / "exist" / "ledger.json"
    rc, out, err = _run(root, ["--ledger-path", str(ledger)], capsys)
    assert rc == 2
    assert "does not exist" in err and "--create-ledger-dir" in err and "Nothing was created" in err
    assert not (tmp_path / "does").exists(), "the scan invented folders for a path it then refused"
    assert not ledger.exists()


def test_the_refusal_is_the_json_error_envelope_under_json(tmp_path, capsys):
    root = _tree(tmp_path)
    ledger = tmp_path / "nope" / "ledger.json"
    rc, out, err = _run(root, ["--ledger-path", str(ledger), "--json"], capsys)
    envelope = json.loads(out)
    assert rc == 2 and envelope["exit_code"] == 2
    assert envelope["status"] == "error" and envelope["error"]["kind"] == "usage"
    assert "--ledger-path" in envelope["error"]["message"]
    assert not (tmp_path / "nope").exists()


def test_the_refusal_comes_before_the_scan(tmp_path, capsys):
    """Refused up front: the ledger is written last, so finding out after a
    long scan that it cannot be written would waste the whole run."""
    root = _tree(tmp_path)
    rc, out, err = _run(root, ["--ledger-path", str(tmp_path / "gone" / "l.json")], capsys)
    assert rc == 2
    assert "scanning" not in err, err


def test_the_opt_in_creates_the_folders_and_writes_the_ledger(tmp_path, capsys):
    root = _tree(tmp_path)
    ledger = tmp_path / "made" / "deeper" / "ledger.json"
    rc, out, err = _run(root, ["--ledger-path", str(ledger), "--create-ledger-dir"], capsys)
    assert rc in (0, 1), err
    assert json.loads(ledger.read_text())["runs"], "the ledger was not written"


def test_an_existing_folder_needs_no_opt_in(tmp_path, capsys):
    root = _tree(tmp_path)
    folder = tmp_path / "state"
    folder.mkdir()
    rc, out, err = _run(root, ["--ledger-path", str(folder / "ledger.json")], capsys)
    assert rc in (0, 1), err
    assert (folder / "ledger.json").is_file()


def test_a_bare_filename_in_the_working_directory_is_fine(tmp_path, capsys, monkeypatch):
    root = _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc, out, err = _run(root, ["--ledger-path", "ledger.json"], capsys)
    assert rc in (0, 1), err
    assert (tmp_path / "ledger.json").is_file()


def test_a_parent_that_is_a_file_is_refused_even_with_the_opt_in(tmp_path, capsys):
    root = _tree(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a folder")
    rc, out, err = _run(root, ["--ledger-path", str(blocker / "ledger.json"), "--create-ledger-dir"], capsys)
    assert rc == 2 and "not a folder" in err
    assert blocker.read_text() == "not a folder"


def test_a_ledger_path_that_is_a_folder_is_refused(tmp_path, capsys):
    root = _tree(tmp_path)
    folder = tmp_path / "state"
    folder.mkdir()
    rc, out, err = _run(root, ["--ledger-path", str(folder)], capsys)
    assert rc == 2 and "is a folder" in err


def test_no_ledger_means_the_path_is_never_asked_about(tmp_path, capsys):
    root = _tree(tmp_path)
    rc, out, err = _run(root, ["--ledger-path", str(tmp_path / "gone" / "l.json"), "--no-ledger"], capsys)
    assert rc in (0, 1), err
    assert not (tmp_path / "gone").exists()


def test_verify_chain_still_reports_a_missing_ledger_as_it_did(tmp_path, capsys):
    root = _tree(tmp_path)
    rc, out, err = _run(root, ["--verify-chain", "--ledger-path", str(tmp_path / "gone" / "l.json")], capsys)
    assert rc == 2 and "no ledger at" in err
    assert not (tmp_path / "gone").exists()


def test_the_library_fails_closed_too(tmp_path):
    """Not only the command line: `Ledger.save()` itself no longer makes folders."""
    ledger = Ledger(tmp_path / "missing" / "ledger.json")
    with pytest.raises(FileNotFoundError):
        ledger.save()
    assert not (tmp_path / "missing").exists()
    ledger.save(create_dirs=True)
    assert (tmp_path / "missing" / "ledger.json").is_file()


def test_the_pipeline_itself_does_not_create_folders_when_called_without_the_cli_check(tmp_path):
    """`gather()` is a library entry point (SWIZZLE and others call it with their own arguments), so it
    must not rely on the command line having refused first: a missing parent is a `Stop`, and nothing is made."""
    from ghost_buster.pipeline import Stop, gather

    root = _tree(tmp_path)
    args = buster_cli._build_parser().parse_args(
        [str(root), *BASE, "--ledger-path", str(tmp_path / "late" / "ledger.json")])
    with pytest.raises(Stop, match="could not be written"):
        gather(args)
    assert not (tmp_path / "late").exists()

    args = buster_cli._build_parser().parse_args(
        [str(root), *BASE, "--ledger-path", str(tmp_path / "late" / "ledger.json"), "--create-ledger-dir"])
    gather(args)
    assert (tmp_path / "late" / "ledger.json").is_file()
