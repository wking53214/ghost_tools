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
