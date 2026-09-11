"""The number of mutants this repository claims to run, held to the number
it runs.

`pyproject.toml`, `Tests/mutant_harness.py` and the CI workflow each state
a mutant count in a comment, and the README states how many mutant files
there are. Every one of them was written by hand and then left behind: at
1.2.4 the comments said 454 and the suites held 548, a gap of 94 nobody
would notice, in a repository whose entire argument is that unmeasured
claims drift.

A number in prose is a claim. This test makes it a checked one. When the
count moves, this fails and names the files to update; updating them is
the point, not a chore the test invents.
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "Tests"

#: Every place the count is written down, and the pattern that finds it.
CLAIM_SITES = {
    "pyproject.toml": re.compile(r"# (\d+) mutants, each copying the project"),
    "Tests/mutant_harness.py": re.compile(r"every one of the (\d+) mutants"),
    ".github/workflows/tests.yml": re.compile(r"because the suite is (\d+)"),
}
FILE_COUNT_SITE = (ROOT / "README.md", re.compile(r"the (\d+) `Tests/\*_mutants\.py` files"))


def _mutant_files():
    return sorted(TESTS.glob("*_mutants.py"))


def _entries(path: pathlib.Path) -> int:
    """Count a MUTANTS list without importing the module: an import would
    pull in the harness and every dependency of the code under test."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "MUTANTS" for t in node.targets
        ):
            return len(node.value.elts)
    raise AssertionError(f"{path.name} matches *_mutants.py but declares no MUTANTS list")


def census() -> tuple[int, int]:
    files = _mutant_files()
    return len(files), sum(_entries(p) for p in files)


def test_every_mutant_file_declares_its_list():
    files, entries = census()
    assert files > 0 and entries > 0


def test_the_stated_mutant_count_is_the_actual_one():
    _, entries = census()
    wrong = []
    for rel, pattern in CLAIM_SITES.items():
        text = (ROOT / rel).read_text()
        found = pattern.search(text)
        assert found, f"{rel}: the mutant-count claim this test guards is gone; update CLAIM_SITES"
        if int(found.group(1)) != entries:
            wrong.append(f"{rel} says {found.group(1)}")
    assert not wrong, (
        f"the suites hold {entries} mutants; " + ", ".join(wrong)
        + ". Update the prose, or delete the number if it is not worth keeping true."
    )


def test_the_stated_number_of_mutant_files_is_the_actual_one():
    files, _ = census()
    path, pattern = FILE_COUNT_SITE
    found = pattern.search(path.read_text())
    assert found, "README.md: the mutant-file-count claim this test guards is gone"
    assert int(found.group(1)) == files, (
        f"there are {files} Tests/*_mutants.py files; README.md says {found.group(1)}"
    )
