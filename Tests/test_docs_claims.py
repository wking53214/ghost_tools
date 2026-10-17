"""Numbers and facts the documentation states, held to what is true.

Each of these was wrong in a shipped README or workflow comment, and nobody
noticed because nothing compared the sentence to the thing it described:

  * the README said 199 Python files while git tracked 212;
  * the README and STACK.md called CNS private after it was made public;
  * a CI comment said the baseline holds "three MAJOR findings" while
    `.ghost_baseline.json` held one;
  * 1.9.1 was declared by pyproject.toml, the README and a tag while ~290
    lines of changes sat under "Unreleased";
  * three work-log notes sat in the repository root beside the README.

A claim that can be counted is counted here. Where a claim cannot be (prose
about intent), the test checks that no document contradicts the fact.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import tomllib

from ghost_buster.mechanical import registered_detectors

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
TESTS_YML = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

_PRUNED = {".git", "__pycache__", "build", "dist", "node_modules", "venv", ".venv", ".tox",
           ".pytest_cache", ".ruff_cache", ".mypy_cache"}
_NUMBER_WORDS = {"no": 0, "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def python_files() -> list[str]:
    """Every .py file of the project, as the README counts them: all of them
    except the fixtures, which are data. Build output, caches and VCS folders
    are not the project."""
    found = []
    for dirpath, dirs, names in os.walk(ROOT):
        rel = pathlib.Path(dirpath).relative_to(ROOT)
        dirs[:] = sorted(d for d in dirs if d not in _PRUNED and not d.endswith(".egg-info"))
        if rel.parts[:2] == ("Tests", "fixtures"):
            dirs[:] = []
            continue
        found += [(rel / n).as_posix() for n in names if n.endswith(".py")]
    return sorted(found)


def test_the_readme_python_file_count_is_the_actual_one():
    claimed = re.search(r"(\d[\d,]*) Python files", README)
    assert claimed, "the README no longer states how many Python files there are"
    assert int(claimed.group(1).replace(",", "")) == len(python_files()), (
        f"README says {claimed.group(1)} Python files; there are {len(python_files())} "
        "(excluding Tests/fixtures). Update the README sentence.")


def test_the_python_file_count_agrees_with_git_where_git_is_available():
    """The walk above and `git ls-files` must say the same thing, so the
    README number means 'tracked files', which is what a reader would check."""
    if not (ROOT / ".git").exists():
        return
    done = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
                          cwd=ROOT, capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        return
    tracked = [p for p in done.stdout.splitlines() if not p.startswith("Tests/fixtures/")]
    assert sorted(tracked) == python_files()


def test_the_readme_detector_count_is_the_registered_one():
    claimed = re.search(r"all (\d+) detectors", README)
    assert claimed, "the README no longer states the detector count"
    assert int(claimed.group(1)) == len(registered_detectors())


def test_the_readme_version_is_the_declared_one():
    claimed = re.search(r"Version (\d+\.\d+\.\d+) \(`pyproject.toml`", README)
    assert claimed and claimed.group(1) == PROJECT["version"]


def test_the_newest_changelog_release_is_the_declared_version_and_dated():
    """The mistake this catches: the code and the README say 1.9.1 while the
    changes since 1.9.1 sit under 'Unreleased', so two different programs are
    both called 1.9.1. A release heading must exist for the version in
    pyproject.toml, newest first, with a date."""
    headings = re.findall(r"^## (.+)$", CHANGELOG, re.M)
    assert headings[0] == "Unreleased", headings[:3]
    newest = headings[1]
    match = re.fullmatch(r"(\d+\.\d+\.\d+) \((\d{4}-\d{2}-\d{2})\)", newest)
    assert match, f"newest release heading {newest!r} is not 'X.Y.Z (YYYY-MM-DD)'"
    assert match.group(1) == PROJECT["version"], (
        f"pyproject.toml declares {PROJECT['version']} but the newest CHANGELOG release is {match.group(1)}")


def test_changelog_release_headings_are_unique_and_newest_first_from_1_0_on():
    """The 0.x entries were written out of order (0.7.0 above 0.8.0) on the
    day they were all made; that history is left as it is. From 1.0.0 on the
    order is strict, because that is where a reader looks for 'what changed
    since the version I run'."""
    releases = re.findall(r"^## (\d+\.\d+\.\d+) \(", CHANGELOG, re.M)
    assert len(releases) == len(set(releases))
    key = [tuple(int(x) for x in v.split(".")) for v in releases]
    modern = [k for k in key if k >= (1, 0, 0)]
    assert modern == sorted(modern, reverse=True)


def test_no_document_calls_cns_private():
    """CNS is public (https://github.com/wking53214/CNS)."""
    stale = []
    documents = [ROOT / "README.md", ROOT / "STACK.md", ROOT / "PROVENANCE.md",
                 *sorted((ROOT / "docs").glob("*.md"))]
    for path in documents:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"private\s+`?CNS|CNS\s*\(private\)|CNS is private|CNS`? is a private", line, re.I):
                stale.append(f"{path.relative_to(ROOT)}:{number}")
    assert not stale, f"CNS is public; these lines still say otherwise: {stale}"


def test_the_ci_comment_about_the_baseline_matches_the_baseline():
    baseline = json.loads((ROOT / ".ghost_baseline.json").read_text(encoding="utf-8"))
    majors = sum(1 for entry in baseline if entry.get("severity") == "major")
    claimed = re.search(r"baseline holds (\w+) MAJOR", TESTS_YML)
    assert claimed, "tests.yml no longer says how many MAJOR findings the baseline holds"
    assert _NUMBER_WORDS[claimed.group(1).lower()] == majors, (
        f"tests.yml says {claimed.group(1)}; .ghost_baseline.json holds {majors}")


def test_the_root_holds_only_the_documents_that_belong_there():
    """Work-log notes (PHASE_1_SUMMARY.md and friends) lived here and read as
    current status. They are in docs/archive/ now, with an index saying so."""
    allowed = {"README.md", "CHANGELOG.md", "STACK.md", "PROVENANCE.md", "NOTICE"}
    stray = sorted(p.name for p in ROOT.glob("*.md") if p.name not in allowed)
    assert not stray, f"move to docs/archive/ (or delete): {stray}"
    assert (ROOT / "docs" / "archive" / "README.md").is_file()


def test_every_relative_markdown_link_resolves():
    """Moving a file must not leave a link behind. Checks README, STACK,
    PROVENANCE, CHANGELOG and everything under docs/ (fragments ignored)."""
    broken = []
    documents = [ROOT / n for n in ("README.md", "STACK.md", "PROVENANCE.md", "CHANGELOG.md")]
    documents += sorted((ROOT / "docs").rglob("*.md"))
    for path in documents:
        text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            file_part = target.split("#", 1)[0]
            if file_part and not (path.parent / file_part).exists():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    assert not broken, f"links to files that do not exist: {broken}"


def test_the_ci_matrix_covers_every_python_the_package_claims():
    classified = sorted(re.findall(r"Python :: (3\.\d+)$", "\n".join(PROJECT["classifiers"]), re.M))
    matrix = re.search(r'python-version: \[([^\]]+)\]', TESTS_YML)
    assert matrix, "tests.yml has no python-version matrix"
    tested = sorted(re.findall(r'"(3\.\d+)"', matrix.group(1)))
    assert tested == classified, f"CI tests {tested}; pyproject classifiers claim {classified}"
    assert f">={tested[0]}" == PROJECT["requires-python"]


def test_the_static_gates_are_configured_and_run_in_ci():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]
    assert {"E", "F", "W", "B"} <= set(config["ruff"]["lint"]["select"])
    assert config["mypy"]["files"], "mypy has no target"
    assert "python -m ruff check ." in TESTS_YML
    assert "python -m mypy" in TESTS_YML


def test_the_readme_and_changelog_say_truthfully_what_is_tagged():
    """No document claims "no release is tagged": older tags exist. What they say instead is checked."""
    for name, text in (("README", README), ("CHANGELOG", CHANGELOG)):
        assert "`v0.10.0`" in text and "matches no current version" in text, name
        assert "not tagged yet" in text and "owner's decision" in text, name
    assert not re.search(r"no release has been tagged", README + CHANGELOG, re.I)
