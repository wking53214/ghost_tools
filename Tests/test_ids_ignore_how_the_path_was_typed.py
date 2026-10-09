"""A finding's id depends on the file, not on how the scan path was typed.

The red team's case: the same folder scanned as `tgt`, `./tgt`, `tgt/`, an
absolute path, or through a symlink produced different ids for the same
finding, so a baseline, ledger or case file written under one spelling
matched nothing under another. The id now hashes the path relative to the
scanned folder, posix slashes.
"""
from __future__ import annotations

import json
import os

import pytest

from ghost_buster import cli as buster_cli
from ghost_buster import schema
from ghost_buster.baseline import Baseline
from ghost_buster.ledger import Ledger
from ghost_buster.mechanical import detect_dead_code

QUIET = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
         "--no-correlate", "--no-ledger", "--no-structure", "--single-repo", "--json"]
DEAD = "def orphan():\n    return 2\n"


def _rows(text):
    """The findings from `--json` output, whether it is the object (current)
    or the bare list (before the status envelope)."""
    payload = json.loads(text)
    return payload["findings"] if isinstance(payload, dict) else payload


def _scan(path, capsys, *extra):
    buster_cli.main([str(path), *QUIET, *extra])
    return _rows(capsys.readouterr().out)


def _dead(rows):
    return {(r["evidence"]["file"], r["attributes"]["name"]): r["id"]
            for r in rows if r["detector"] == "dead_code"}


def _repo(tmp_path, marker=None):
    root = tmp_path / "work" / "tgt"
    (root / "pkg" / "sub").mkdir(parents=True)
    (root / "m.py").write_text(DEAD, encoding="utf-8")
    (root / "pkg" / "sub" / "n.py").write_text(DEAD, encoding="utf-8")
    if marker:
        (root / marker).write_text("", encoding="utf-8")
    return root


@pytest.mark.parametrize("marker", [None, "pyproject.toml"])
def test_every_spelling_of_the_same_folder_gives_the_same_ids(tmp_path, capsys, monkeypatch, marker):
    root = _repo(tmp_path, marker)
    (tmp_path / "work" / "link").symlink_to(root, target_is_directory=True)
    (tmp_path / "elsewhere").mkdir()
    results = {}
    monkeypatch.chdir(tmp_path / "work")
    for spelling in ("tgt", "./tgt", "tgt/", str(root), str(root) + "/",
                     "link", "../work/tgt", "../work/link/"):
        results[spelling] = _dead(_scan(spelling, capsys))
    monkeypatch.chdir(tmp_path / "elsewhere")
    results["from-elsewhere"] = _dead(_scan("../work/tgt", capsys))
    monkeypatch.chdir(root)
    results["dot"] = _dead(_scan(".", capsys))
    reference = results["tgt"]
    assert set(reference) == {("m.py", "orphan"), ("pkg/sub/n.py", "orphan")}
    for spelling, ids in results.items():
        assert ids == reference, spelling


def test_the_id_is_the_hash_of_detector_root_relative_path_and_summary(tmp_path, capsys):
    root = _repo(tmp_path)
    row = [r for r in _scan(root, capsys) if r["evidence"]["file"] == "pkg/sub/n.py"
           and r["detector"] == "dead_code"][0]
    assert row["id"] == schema._stable_id("dead_code", "pkg/sub/n.py", row["summary"])


def test_a_nested_package_marker_no_longer_changes_the_path_in_the_id(tmp_path, capsys):
    root = _repo(tmp_path)
    (root / "pkg" / "pyproject.toml").write_text("", encoding="utf-8")
    ids = _dead(_scan(root, capsys))
    assert ("pkg/sub/n.py", "orphan") in ids
    row = [r for r in _scan(root, capsys) if r["evidence"]["file"] == "pkg/sub/n.py"
           and r["detector"] == "dead_code"][0]
    assert row["id"] == schema._stable_id("dead_code", "pkg/sub/n.py", row["summary"])


def _old_style(root):
    """Findings as the previous version identified them: built outside any
    scan, from the absolute path."""
    return detect_dead_code([root / "m.py"])


def test_a_baseline_written_with_the_old_ids_still_suppresses(tmp_path, capsys):
    root = _repo(tmp_path)
    old = _old_style(root)
    new_ids = {r["id"] for r in _scan(root, capsys) if r["detector"] == "dead_code"}
    assert old and not ({f.id for f in old} & new_ids)      # the spelling really did change
    path = tmp_path / "base.json"
    path.write_text(schema.FindingSet(old).to_json(), encoding="utf-8")
    buster_cli.main([str(root), *QUIET, "--baseline", str(path)])
    out = _rows(capsys.readouterr().out)
    shown = {(r["evidence"]["file"]) for r in out if r["detector"] == "dead_code"}
    assert "m.py" not in shown                               # suppressed by its old id
    assert "pkg/sub/n.py" in shown                           # not in the baseline: still new
    assert not [r for r in out if r["detector"] == "stale_baseline"]


def test_a_ledger_written_with_the_old_ids_carries_its_history_forward(tmp_path, capsys):
    root = _repo(tmp_path)
    old = _old_style(root)
    ledger_path = tmp_path / "ledger.json"
    first = Ledger(ledger_path)
    first.record(old, checks={}, commit="", tool_version="t", at="2026-01-01T00:00:00+00:00")
    first.save()
    old_id = old[0].id
    assert first.findings[old_id].runs_seen == 1

    buster_cli.main([str(root), *[a for a in QUIET if a != "--no-ledger"], "--ledger-path", str(ledger_path)])
    capsys.readouterr()
    after = Ledger(ledger_path)
    mine = [h for h in after.findings.values() if h.file == "m.py" and h.detector == "dead_code"]
    assert len(mine) == 1                                    # one finding, not a fixed one and a new one
    assert mine[0].runs_seen == 2 and mine[0].first_seen.startswith("2026-01-01")
    assert old_id not in after.findings and mine[0].returns == 0
