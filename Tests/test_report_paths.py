"""A finding's file is always shown relative to the folder that was scanned.

The red team's case: a root-level `m.py` in a folder named `tgt` was reported as
`tgt/m.py`, because with no project marker the path was cut to its last two
pieces. A tool that joins the reported path onto the scan folder then looked for
`tgt/tgt/m.py`. The finding's id must not move when the shown path does.
"""
from __future__ import annotations

import json
import subprocess

from ghost_buster import cli as buster_cli
from ghost_buster.schema import _stable_id

QUIET = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
         "--no-correlate", "--no-ledger", "--no-structure", "--json"]
DEAD = "def orphan():\n    return 2\n"


def _scan(root, capsys):
    buster_cli.main([str(root), *QUIET])
    return json.loads(capsys.readouterr().out)["findings"]


def _dead(rows):
    return {r["attributes"]["name"] + "@" + r["evidence"]["file"]: r for r in rows
            if r["detector"] == "dead_code"}


def test_a_root_level_file_is_not_prefixed_with_the_scan_folder_name(tmp_path, capsys):
    root = tmp_path / "tgt"
    root.mkdir()
    (root / "m.py").write_text(DEAD, encoding="utf-8")
    assert list(_dead(_scan(root, capsys))) == ["orphan@m.py"]


def test_a_file_three_folders_deep_keeps_its_whole_path(tmp_path, capsys):
    root = tmp_path / "tgt"
    (root / "a" / "b" / "c").mkdir(parents=True)
    (root / "a" / "b" / "c" / "m.py").write_text(DEAD, encoding="utf-8")
    assert list(_dead(_scan(root, capsys))) == ["orphan@a/b/c/m.py"]


def test_a_packaging_marker_in_the_scan_folder_changes_nothing(tmp_path, capsys):
    root = tmp_path / "tgt"
    (root / "pkg").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1"\n', encoding="utf-8")
    (root / "m.py").write_text(DEAD, encoding="utf-8")
    (root / "pkg" / "n.py").write_text(DEAD, encoding="utf-8")
    assert sorted(_dead(_scan(root, capsys))) == ["orphan@m.py", "orphan@pkg/n.py"]


def test_scanning_a_subfolder_of_a_git_checkout_is_relative_to_that_subfolder(tmp_path, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    root = tmp_path / "sub" / "deeper"
    root.mkdir(parents=True)
    (root / "m.py").write_text(DEAD, encoding="utf-8")
    assert list(_dead(_scan(root, capsys))) == ["orphan@m.py"]


def test_a_relative_scan_path_gives_the_same_answer(tmp_path, capsys, monkeypatch):
    root = tmp_path / "tgt"
    (root / "pkg").mkdir(parents=True)
    (root / "m.py").write_text(DEAD, encoding="utf-8")
    (root / "pkg" / "n.py").write_text(DEAD, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    buster_cli.main(["tgt", *QUIET])
    rows = json.loads(capsys.readouterr().out)["findings"]
    assert sorted(_dead(rows)) == ["orphan@m.py", "orphan@pkg/n.py"]


def test_the_finding_id_is_the_hash_of_the_shown_path(tmp_path, capsys):
    """Since ids became scan-root relative (see
    test_ids_ignore_how_the_path_was_typed.py) the shown path and the path
    in the id are the same thing, so the two cannot drift apart again."""
    root = tmp_path / "tgt"
    (root / "a" / "b" / "c").mkdir(parents=True)
    (root / "m.py").write_text(DEAD, encoding="utf-8")
    (root / "a" / "b" / "c" / "m.py").write_text(DEAD, encoding="utf-8")
    rows = _dead(_scan(root, capsys))
    assert sorted(rows) == ["orphan@a/b/c/m.py", "orphan@m.py"]
    for row in rows.values():
        assert row["id"] == _stable_id("dead_code", row["evidence"]["file"], row["summary"])


def test_a_markdown_finding_is_relative_to_the_scan_root_too(tmp_path, capsys):
    root = tmp_path / "tgt"
    (root / "docs").mkdir(parents=True)
    (root / "test_a.py").write_text("def test_a():\n    pass\n\ndef test_b():\n    pass\n", encoding="utf-8")
    (root / "docs" / "NOTES.md").write_text("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> b\n", encoding="utf-8")
    files = {r["evidence"]["file"] for r in _scan(root, capsys)}
    assert "docs/NOTES.md" in files
