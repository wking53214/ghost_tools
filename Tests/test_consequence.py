"""Does it matter here: ranking findings by severity and by who depends on the code.

Every case builds a small stack of repositories on disk and asks the rule about it.
"""
from __future__ import annotations

import json
import os

import pytest

from ghost_buster import consequence as c


def _put(root, rel, text=""):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def stack(tmp_path):
    _put(tmp_path, "core/liba/__init__.py", "")
    _put(tmp_path, "core/liba/work.py", "x = 1\n")
    _put(tmp_path, "core/tests/test_work.py", "import liba\n")
    _put(tmp_path, "core/archive/old.py", "x = 1\n")
    _put(tmp_path, "user/app/main.py", "import liba.work\nfrom liba import work\n")
    _put(tmp_path, "tester/tests/test_it.py", "import liba\n")
    _put(tmp_path, "copy/liba/__init__.py", "")
    _put(tmp_path, "copy/app2/main.py", "import liba\n")
    _put(tmp_path, "broken/pkg/bad.py", "def (:\n")
    return c.read_stack(tmp_path)


def test_a_package_another_repo_imports_is_shared(stack):
    got = c.consequence(stack, "core", "liba/work.py")
    assert got.kind == c.SHARED and got.package == "liba" and got.importers == ("user",)


def test_a_test_that_imports_it_is_not_a_consumer(stack):
    assert "tester" not in c.consequence(stack, "core", "liba/work.py").importers


def test_a_repo_with_its_own_copy_of_the_name_is_not_a_consumer(stack):
    assert "copy" not in c.consequence(stack, "core", "liba/work.py").importers
    assert stack.provides["liba"] == {"core", "copy"}


def test_a_package_nobody_else_imports_is_own_use(stack):
    assert c.consequence(stack, "user", "app/main.py").kind == c.OWN_USE


@pytest.mark.parametrize("rel", ["tests/test_work.py", "archive/old.py", "examples/a.py", "conftest.py",
                                 "pkg/test_thing.py", "scripts/run.py"])
def test_tests_examples_scripts_and_archives_are_off_path(stack, rel):
    assert c.consequence(stack, "core", rel).kind == c.OFF_PATH


def test_a_manifest_is_repo_level(stack):
    assert c.consequence(stack, "core", "pyproject.toml").kind == c.REPO_LEVEL


def test_src_layout_names_the_package_below_src():
    assert c.package_of("src/dit/tower.py") == "dit"
    assert c.package_of("ure_engine/engine.py") == "ure_engine"
    assert c.package_of("gsa_gateway.py") == "gsa_gateway"


def test_a_file_that_does_not_parse_is_skipped_not_fatal(stack):
    assert stack.imports["broken"] == set()


@pytest.mark.parametrize("status,severity,kind,want", [
    ("confirmed", "major", c.SHARED, 1),
    ("confirmed", "critical", c.SHARED, 1),
    ("confirmed", "major", c.OWN_USE, 2),
    ("confirmed", "major", c.REPO_LEVEL, 2),
    ("confirmed", "major", c.OFF_PATH, 3),
    ("confirmed", "minor", c.SHARED, 4),
    ("confirmed", "informational", c.SHARED, 4),
    ("confirmed", "minor", c.OWN_USE, 5),
    ("confirmed", "minor", c.OFF_PATH, 5),
    ("reasoned", "major", c.SHARED, 1),
    ("rejected", "major", c.SHARED, 0),
    ("suppressed", "critical", c.SHARED, 0),
])
def test_the_tier_table(status, severity, kind, want):
    assert c.tier(status, severity, kind) == want


def _finding(i, file, severity="minor", status="confirmed", detector="long_function"):
    return {"id": i, "detector": detector, "severity": severity, "status": status, "evidence": {"file": file}}


def test_rank_orders_by_tier_then_by_how_many_repos_depend_on_it(stack):
    reports = {"core": {"findings": [
        _finding("a", "liba/work.py", "minor"),
        _finding("b", "archive/old.py", "major"),
        _finding("c", "liba/work.py", "major"),
        _finding("d", "liba/work.py", "major", status="rejected"),
        _finding("e", "liba/work.py", "major", status="reasoned"),
    ]}}
    ranked = c.rank(stack, reports)
    assert [r.id for r in ranked] == ["c", "e", "b", "a", "d"]
    assert [r.tier for r in ranked] == [1, 1, 3, 4, 0]
    assert [r.verify for r in ranked] == [False, True, False, False, False]


def test_rank_does_not_change_the_findings_it_reads(stack):
    report = {"findings": [_finding("a", "liba/work.py", "major")]}
    before = json.dumps(report, sort_keys=True)
    c.rank(stack, {"core": report})
    assert json.dumps(report, sort_keys=True) == before


def test_the_ranking_is_the_same_on_every_run(stack):
    reports = {"core": {"findings": [_finding(str(i), "liba/work.py", "major") for i in range(5)]}}
    assert [r.id for r in c.rank(stack, reports)] == [r.id for r in c.rank(stack, reports)]


def test_a_symlinked_folder_is_not_followed(tmp_path):
    _put(tmp_path, "real/liba/__init__.py", "")
    _put(tmp_path, "elsewhere/secret/mod.py", "import liba\n")
    os.symlink(tmp_path / "elsewhere", tmp_path / "real" / "linked")
    stack = c.read_stack(tmp_path)
    assert "liba" not in stack.imports["real"]


def test_the_cli_prints_the_rule_and_the_tiers(stack, tmp_path, capsys):
    report = tmp_path / "core.json"
    report.write_text(json.dumps({"findings": [_finding("a", "liba/work.py", "major")]}), encoding="utf-8")
    assert c.main(["--stack", str(tmp_path), f"core={report}"]) == 0
    out = capsys.readouterr().out
    assert c.RULE in out and "FIX FIRST" in out and "core/liba/work.py" in out


def test_the_cli_json_carries_the_rule_and_the_importers(stack, tmp_path, capsys):
    report = tmp_path / "core.json"
    report.write_text(json.dumps({"findings": [_finding("a", "liba/work.py", "major")]}), encoding="utf-8")
    assert c.main(["--stack", str(tmp_path), f"core={report}", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert row["rule"] == c.RULE and row["tier_name"] == "FIX FIRST" and row["importers"] == ["user"]


def test_the_cli_refuses_a_repo_that_is_not_in_the_stack(stack, tmp_path, capsys):
    report = tmp_path / "x.json"
    report.write_text("{}", encoding="utf-8")
    assert c.main(["--stack", str(tmp_path), f"nope={report}"]) == 2
    assert "nope" in capsys.readouterr().err


def test_the_cli_refuses_an_unreadable_report(stack, tmp_path, capsys):
    assert c.main(["--stack", str(tmp_path), f"core={tmp_path / 'missing.json'}"]) == 2
