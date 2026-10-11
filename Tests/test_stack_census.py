"""stack_census: a read-only census of the clones in one folder.

Real throwaway git repositories are used so the facts come from git itself.
The census reports what git, the manifests and the Graveyard say; it assigns
no tier and writes nothing.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from stack_census import census as census_mod
from stack_census import cli, facts, graveyard, pins, render

OWNER = "me"
SHA_A = "a" * 40
SHA_B = "b" * 40


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.name=t",
                    "-c", "user.email=t@example.com", "-C", str(repo), *args],
                   check=True, capture_output=True)


def make_repo(parent: Path, name: str, files: dict | None = None, branch: str = "main") -> Path:
    repo = parent / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(repo)], check=True)
    for rel, text in {"README.md": "# x\n", "LICENSE": "MIT\n", **(files or {})}.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")
    return repo


def dep(target: str, ref: str = "") -> str:
    suffix = f"@{ref}" if ref else ""
    return f'dependencies = ["{target} @ git+https://github.com/{OWNER}/{target}.git{suffix}"]\n'


def snapshot(root: Path) -> dict:
    out = {}
    for here, _dirs, names in os.walk(root):
        for name in names:
            path = Path(here) / name
            stat = path.stat()
            out[str(path)] = (stat.st_size, stat.st_mtime_ns)
    return out


# --- refs and pins ---------------------------------------------------------

@pytest.mark.parametrize("ref,kind", [
    ("", "none"), (SHA_A, "commit"), ("3b465db", "commit"), ("v1.4.0", "tag"),
    ("1.4.0", "tag"), ("main", "branch"), ("feature/x", "branch"),
])
def test_a_ref_is_classified_by_what_it_names(ref, kind):
    assert pins.classify_ref(ref) == kind


def test_pins_are_read_from_every_common_spelling():
    text = (
        f'a = "cns @ git+https://github.com/{OWNER}/cns.git@{SHA_A}"\n'
        f"b = git+https://github.com/{OWNER}/CNS.git@v1.4.0\n"
        f"c = git+https://github.com/{OWNER}/other\n"
        f"d = git+ssh://git@github.com:{OWNER}/viaSsh.git@abc1234\n"
        f"e = git+https://github.com/{OWNER}/onbranch@main\n"
    )
    found = {(p.target, p.kind) for p in pins.pins_in_text(text, "app", "pyproject.toml", OWNER)}
    assert found == {("cns", "commit"), ("CNS", "tag"), ("other", "none"),
                     ("viaSsh", "commit"), ("onbranch", "branch")}


def test_other_owners_self_pins_and_prose_ellipses_are_not_pins():
    text = (
        "git+https://github.com/someone-else/lib.git@abc1234\n"
        f"git+https://github.com/{OWNER}/app.git@abc1234\n"
        f"see github.com/{OWNER}/... for the others\n"
    )
    assert pins.pins_in_text(text, "app", "pyproject.toml", OWNER) == []


def test_manifests_are_found_in_subfolders_and_workflows_but_not_in_fixtures(tmp_path):
    repo = make_repo(tmp_path, "app", {
        "sub/requirements.txt": f"git+https://github.com/{OWNER}/libsub@{SHA_A}\n",
        ".github/workflows/ci.yml": f"run: pip install git+https://github.com/{OWNER}/libci@main\n",
        "Tests/fixtures/pyproject.toml": dep("libfixture", SHA_A),
        "node_modules/x/pyproject.toml": dep("libnode", SHA_A),
    })
    targets = {p.target for p in pins.scan_repo(repo, OWNER)}
    assert targets == {"libsub", "libci"}


# --- the Graveyard ---------------------------------------------------------

def test_the_graveyard_separates_whole_retirements_from_partial_burials(tmp_path):
    grave = tmp_path / "Graveyard"
    (grave / "augur" / "2026-10-07-full-retirement").mkdir(parents=True)
    (grave / "ccc" / "2026-10-06-turning-points").mkdir(parents=True)
    (grave / "README.md").write_text("x")
    burials = graveyard.read_graveyard(grave)
    assert burials.read
    assert burials.retired_on("Augur") == "2026-10-07"
    assert burials.retired_on("CCC") == ""
    assert burials.partial == {"ccc": 1}


def test_a_missing_graveyard_is_not_read_rather_than_empty(tmp_path):
    burials = graveyard.read_graveyard(tmp_path / "nope")
    assert burials.read is False and burials.whole == {}


# --- facts -----------------------------------------------------------------

def test_facts_come_from_git_and_the_files(tmp_path):
    repo = make_repo(tmp_path, "lab", {"README.md": "Status: lab, asking one question\n"},
                     branch="claude/work")
    f = facts.gather(repo)
    assert f.branch == "claude/work" and f.commits_total == 1 and f.commits_30d == 1
    assert f.has_license and f.readme == "status" and not f.has_ci
    assert f.last_commit == date.today().isoformat() or f.last_commit is not None


def test_readme_state_has_three_answers(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    assert facts.readme_state(bare) == "none"
    (bare / "README.md").write_text("# title\n\nno marker here\n")
    assert facts.readme_state(bare) == "no-status"
    (bare / "README.md").write_text("> LAB: one question\n")
    assert facts.readme_state(bare) == "status"


def test_a_detached_head_has_no_branch(tmp_path):
    repo = make_repo(tmp_path, "r")
    (repo / ".git" / "HEAD").write_text(SHA_A + "\n")
    assert facts.checked_out_branch(repo) is None


def test_what_git_cannot_say_is_unknown_not_zero(tmp_path):
    broken = tmp_path / "broken"
    (broken / ".git").mkdir(parents=True)
    f = facts.gather(broken)
    assert f.commits_total is None and f.commits_30d is None and f.last_commit is None
    row = render._table_rows([census_mod.Row(f, "live", "", [], [], "LAB")])[1]
    assert row[1:4] == ["?", "?", "?"]


# --- the census ------------------------------------------------------------

def stack(tmp_path: Path) -> Path:
    make_repo(tmp_path, "lib")
    make_repo(tmp_path, "app", {"pyproject.toml": dep("lib", SHA_A) + dep("Gone", SHA_B)})
    make_repo(tmp_path, "solo")
    make_repo(tmp_path, "Gone", {"NOTICE": "n\n"})
    make_repo(tmp_path, "Graveyard", {
        "gone/2026-10-07-full-retirement/BURIAL.md": "b\n",
        "README.md": "| 2026-10-07 | gone |\n",
        "pyproject.toml": dep("lib", "deadbeef"),
    })
    return tmp_path


def by_name(c):
    return {r.facts.name: r for r in c.rows}


def test_hints_follow_pins_age_and_burial(tmp_path):
    parent = stack(tmp_path)
    soon = date.today() + timedelta(days=5)
    later = date.today() + timedelta(days=90)
    rows = by_name(census_mod.build(parent, OWNER, "Graveyard", soon))
    assert rows["lib"].hint == census_mod.HINT_LIBRARY and rows["lib"].pinned_by == ["app"]
    assert rows["solo"].hint == census_mod.HINT_LAB
    assert rows["Gone"].state == census_mod.GRAVESTONE and rows["Gone"].hint == census_mod.HINT_BURIED
    assert rows["Graveyard"].hint == census_mod.HINT_GRAVEYARD
    stale = by_name(census_mod.build(parent, OWNER, "Graveyard", later))
    assert stale["solo"].hint == census_mod.HINT_ARCHIVE
    assert stale["lib"].hint == census_mod.HINT_LIBRARY


def test_the_graveyards_own_manifests_are_not_counted_as_pins(tmp_path):
    parent = stack(tmp_path)
    rows = by_name(census_mod.build(parent, OWNER, "Graveyard", date.today()))
    assert "Graveyard" not in rows["lib"].pinned_by


def test_a_live_pin_to_a_retired_repo_is_flagged_on_the_pinner(tmp_path):
    parent = stack(tmp_path)
    rows = by_name(census_mod.build(parent, OWNER, "Graveyard", date.today()))
    assert any("pins Gone, retired 2026-10-07" in f for f in rows["app"].flags)


def test_a_retired_repo_whose_clone_is_still_full_is_called_out(tmp_path):
    parent = stack(tmp_path)
    for i in range(8):
        (parent / "Gone" / f"f{i}.py").write_text("x")
    rows = by_name(census_mod.build(parent, OWNER, "Graveyard", date.today()))
    assert rows["Gone"].state == census_mod.RETIRED_FULL
    assert rows["Gone"].hint == census_mod.HINT_RETIRED_FULL
    assert any("still holds the repo" in f for f in rows["Gone"].flags)


def test_pins_with_no_clone_are_listed_and_marked_when_retired(tmp_path):
    make_repo(tmp_path, "app", {"pyproject.toml": dep("Warden", SHA_A) + dep("augur", SHA_B)})
    make_repo(tmp_path, "Graveyard", {"augur/2026-10-07-full-retirement/BURIAL.md": "b\n"})
    c = census_mod.build(tmp_path, OWNER, "Graveyard", date.today())
    assert c.external["Warden"].consumers == ["app"] and c.external["Warden"].retired_on == ""
    assert c.external["augur"].retired_on == "2026-10-07"


def test_a_target_pinned_at_several_versions_and_never_by_tag_is_flagged(tmp_path):
    make_repo(tmp_path, "lib")
    make_repo(tmp_path, "one", {"pyproject.toml": dep("lib", SHA_A)})
    make_repo(tmp_path, "two", {"pyproject.toml": dep("lib", SHA_B)})
    flags = by_name(census_mod.build(tmp_path, OWNER, "Graveyard", date.today()))["lib"].flags
    assert any(f.startswith("pinned at 2 different versions") for f in flags)
    assert any("never pinned by a tag" in f for f in flags)
    make_repo(tmp_path, "three", {"pyproject.toml": dep("lib", "v1.0.0")})
    flags = by_name(census_mod.build(tmp_path, OWNER, "Graveyard", date.today()))["lib"].flags
    assert not any("never pinned by a tag" in f for f in flags)


def test_a_claude_branch_and_a_missing_license_are_flagged(tmp_path):
    make_repo(tmp_path, "wip", branch="claude/thing")
    make_repo(tmp_path, "nolic")
    (tmp_path / "nolic" / "LICENSE").unlink()
    rows = by_name(census_mod.build(tmp_path, OWNER, "Graveyard", date.today()))
    assert "checked-out branch is claude/thing" in rows["wip"].flags
    assert "no license file" in rows["nolic"].flags


def test_the_census_changes_nothing_on_disk(tmp_path):
    parent = stack(tmp_path)
    before = snapshot(parent)
    census_mod.build(parent, OWNER, "Graveyard", date.today())
    cli.main([str(parent)])
    assert snapshot(parent) == before


# --- output ----------------------------------------------------------------

def test_the_draft_entry_leaves_the_decision_to_the_person(tmp_path):
    parent = stack(tmp_path)
    entry = render.entry(census_mod.build(parent, OWNER, "Graveyard", date(2026, 10, 10)))
    assert entry.startswith("## 2026-10-10")
    assert entry.rstrip().endswith(render.DECISION_PROMPT)
    assert "no change this cycle, because ..." in entry


def test_json_output_is_valid_and_carries_what_the_table_does(tmp_path, capsys):
    parent = stack(tmp_path)
    assert cli.main([str(parent), "--owner", OWNER, "--json", "--date", "2026-10-10"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["date"] == "2026-10-10" and data["graveyard_read"] is True
    assert {r["repo"] for r in data["repos"]} >= {"lib", "app", "solo", "Gone", "Graveyard"}
    assert data["counts"]["gravestones"] == 1


def test_the_text_report_says_when_the_graveyard_was_not_read(tmp_path, capsys):
    make_repo(tmp_path, "solo")
    assert cli.main([str(tmp_path), "--owner", OWNER]) == 0
    out = capsys.readouterr().out
    assert "NOT READ" in out and "Stack census" in out


def test_a_missing_parent_folder_is_a_usage_error(tmp_path, capsys):
    assert cli.main([str(tmp_path / "nope")]) == cli.EXIT_USAGE
    assert "is not a folder" in capsys.readouterr().err
