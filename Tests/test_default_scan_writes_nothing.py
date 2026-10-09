"""A default scan does not write a ledger (or anything) into the target.

The red team's case: scanning a folder left a `.ghost_ledger.json` in it, so
a read-only audit dirtied the repository under audit. Writing the ledger is
now opt-in: `--ledger`, or an explicit `--ledger-path FILE`.
"""
from __future__ import annotations

import json
import os

from ghost_buster import cli as buster_cli

BASE = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
        "--no-correlate", "--no-structure", "--single-repo"]


def _tree(tmp_path):
    root = tmp_path / "tgt"
    root.mkdir()
    (root / "m.py").write_text("def orphan():\n    return 2\n", encoding="utf-8")
    return root


def _listing(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_a_default_scan_leaves_the_target_exactly_as_it_found_it(tmp_path, capsys):
    root = _tree(tmp_path)
    before = _listing(root)
    buster_cli.main([str(root), *BASE])
    assert _listing(root) == before
    assert not (root / ".ghost_ledger.json").exists()
    assert "ledger NOT UPDATED" in capsys.readouterr().err


def test_asking_for_the_ledger_writes_it(tmp_path):
    root = _tree(tmp_path)
    buster_cli.main([str(root), *BASE, "--ledger"])
    assert json.loads((root / ".ghost_ledger.json").read_text())["runs"]


def test_ledger_path_is_an_explicit_request_and_can_live_outside_the_target(tmp_path):
    root = _tree(tmp_path)
    elsewhere = tmp_path / "state" / "ledger.json"
    elsewhere.parent.mkdir()
    before = _listing(root)
    buster_cli.main([str(root), *BASE, "--ledger-path", str(elsewhere)])
    assert json.loads(elsewhere.read_text())["runs"]
    assert _listing(root) == before


def test_no_ledger_is_still_accepted(tmp_path, capsys):
    root = _tree(tmp_path)
    buster_cli.main([str(root), *BASE, "--no-ledger"])
    assert not (root / ".ghost_ledger.json").exists()
    assert "SKIPPED at your request (--no-ledger)" in capsys.readouterr().err


def test_an_existing_ledger_is_left_untouched_by_a_default_scan(tmp_path, capsys):
    root = _tree(tmp_path)
    buster_cli.main([str(root), *BASE, "--ledger"])
    ledger = root / ".ghost_ledger.json"
    before, stamp = ledger.read_bytes(), os.stat(ledger).st_mtime_ns
    capsys.readouterr()
    buster_cli.main([str(root), *BASE])
    assert ledger.read_bytes() == before and os.stat(ledger).st_mtime_ns == stamp
    assert "left untouched" in capsys.readouterr().err
