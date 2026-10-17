"""The package list in pyproject.toml names folders that exist.

#89 deleted ghost_writer/polish and left it in `packages`. Every install from
git failed from then on (`error: package directory 'ghost_writer/polish' does
not exist`), and nothing here noticed, because the suite runs from source and
never builds the package. URE's CI installs Ghost Tools from git, so it is the
first thing that would break.
"""
from __future__ import annotations

import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((ROOT / "pyproject.toml").read_text())
SETUPTOOLS = CONFIG["tool"]["setuptools"]


def _folder(package: str) -> pathlib.Path:
    return ROOT.joinpath(*package.split("."))


def test_every_listed_package_is_a_real_package_folder():
    missing = [p for p in SETUPTOOLS["packages"] if not (_folder(p) / "__init__.py").is_file()]
    assert not missing, f"pyproject lists packages with no folder: {missing}"


def test_package_data_names_listed_packages_and_files_that_exist():
    data = SETUPTOOLS.get("package-data", {})
    stray = [p for p in data if p not in SETUPTOOLS["packages"]]
    assert not stray, f"package-data names packages that are not listed: {stray}"
    absent = [f"{p}/{name}" for p, names in data.items() for name in names
              if not (_folder(p) / name).is_file()]
    assert not absent, f"package-data names files that do not exist: {absent}"


def test_every_console_script_points_into_a_listed_package():
    listed = set(SETUPTOOLS["packages"])
    scripts = CONFIG["project"]["scripts"]
    orphans = {name: target for name, target in scripts.items()
               if target.split(":")[0].rsplit(".", 1)[0] not in listed}
    assert not orphans, f"console scripts point outside the listed packages: {orphans}"


#: Folders that are not shipped code, whatever they contain.
_NOT_SHIPPED = {"Tests", "docs", "tools", "build", "dist"}


def _package_folders():
    """Every folder holding an `__init__.py`, as a dotted name: the code that
    exists, found by looking at the tree and not at the list that describes it."""
    found = []
    for init in sorted(ROOT.rglob("__init__.py")):
        parts = init.parent.relative_to(ROOT).parts
        if not parts or parts[0] in _NOT_SHIPPED or any(
                p.startswith(".") or p == "__pycache__" or p.endswith(".egg-info") for p in parts):
            continue
        found.append(".".join(parts))
    return found


def test_every_package_folder_in_the_tree_is_listed_so_it_ships():
    """The converse of the first test. `ghost_buster/production/` sat in the
    tree for months, 214 lines with a hardcoded development signing key, and
    was missing from `packages`: a wheel would not have contained it, the
    suite (which runs from source) could import it, and nothing imported it.
    Code that exists but does not ship is either dead or a release that
    works only from a checkout; both are findings, not states to leave."""
    listed = set(SETUPTOOLS["packages"])
    unlisted = [p for p in _package_folders() if p not in listed]
    assert not unlisted, (
        f"package folders in the tree but not in pyproject's `packages`: {unlisted}. "
        "List them, or delete them if nothing uses them.")


def test_the_package_finder_sees_the_four_shipped_packages():
    """Guards the guard: if the walk above silently found nothing, the test
    above would pass for the wrong reason."""
    assert set(SETUPTOOLS["packages"]) <= set(_package_folders())
