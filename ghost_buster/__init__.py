"""ghost_tools -- a codebase integrity toolkit.

WHY THE VERSION IS READ, NOT WRITTEN

pyproject.toml is the single source of truth for the version. This module
reads it back instead of restating it. A hardcoded `__version__ = "0.10.1"`
here would be exactly the second copy that this toolkit exists to find:
one release that bumps only pyproject and `--version` starts lying, quietly,
to the one audience that went looking for the truth. Tests/test_version.py
holds the two in agreement either way.
"""
from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version as _installed_version
from pathlib import Path

#: The backronym. ghost_tools catalogues the mistakes that founders make
#: often enough to be worth automating away, so this is less a joke than an
#: accurate table of contents.
BACKRONYM = "FFF: Founders' Favorite Fuckups"

_DISTRIBUTION = "ghost-tools"


def _read_version() -> str:
    """The version of the code that is RUNNING, not of what is installed.

    The source checkout comes first, deliberately. Installed metadata
    describes a distribution somebody installed once; the pyproject.toml
    sitting beside this file describes the code the interpreter actually
    imported. When they disagree -- an older wheel installed, a newer
    checkout on sys.path, which is how every contributor and every `pip
    install -e` workflow runs -- the second is the truth, and the first is
    a version number for code that is not executing.

    That is not cosmetic here. `--operate` and every scan stamp this
    string into the ledger as `tool_version`, so a run's evidence would
    otherwise carry the version of a build that did not produce it.
    Measured: with a fake `ghost-tools 9.9.9` distribution on the path and
    the 1.2.4 source imported, the package reported 9.9.9.

    An installed wheel has no pyproject.toml next to the package, so
    metadata remains the answer there, and it is the right one: nothing
    else is running.
    """
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        with pyproject.open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        pass
    try:
        return _installed_version(_DISTRIBUTION)
    except PackageNotFoundError:
        # Never raise from an import. A version we cannot determine is a
        # cosmetic problem; a package that will not import is not.
        return "unknown"


__version__ = _read_version()


def version_string() -> str:
    """What `ghost_buster --version` prints."""
    return f"ghost_buster {__version__} ({BACKRONYM})"
