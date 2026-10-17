"""`ghost_buster --version`, and the guard that keeps it honest.

The flag exists so someone can ask a binary what it is. That makes a stale
answer worse than no answer, so the test that matters here is not "does it
print something" but "does it print what pyproject.toml says".
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from ghost_buster import BACKRONYM, __version__, version_string
from ghost_buster.cli import main

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _declared_version() -> str:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_version_matches_pyproject():
    """The whole point of reading rather than restating: one bump, one place."""
    assert __version__ == _declared_version()
    assert __version__ != "unknown"


def test_version_string_carries_the_version_and_the_backronym():
    assert version_string() == f"ghost_buster {_declared_version()} ({BACKRONYM})"


def test_version_flag_prints_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == version_string()


def test_version_flag_does_not_require_a_path():
    """A required positional would normally make `--version` alone exit 2.
    argparse consumes a `version` action during parsing and exits before it
    checks for missing positionals; this pins that behaviour so a later
    reshuffle of the argument table cannot quietly break it."""
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_unknown_version_never_raises(monkeypatch):
    """An undeterminable version is cosmetic. An import that raises is not."""
    import ghost_buster

    monkeypatch.setattr(ghost_buster, "_DISTRIBUTION", "no-such-distribution")
    monkeypatch.setattr(
        ghost_buster.Path, "open",
        lambda *a, **k: (_ for _ in ()).throw(OSError("gone")),
    )
    assert ghost_buster._read_version() == "unknown"


# --------------------------------------------------------------------------
# Every console script answers --version, with the same text.

def _console_scripts():
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["project"]["scripts"]


def _resolve(target):
    import importlib
    module, _, attr = target.partition(":")
    return getattr(importlib.import_module(module), attr)


def test_there_are_six_console_scripts():
    assert sorted(_console_scripts()) == [
        "blackhole-extrapolator", "ghost-buster", "ghost-rank", "ghost-triage", "ghost-writer", "stack-census"]


@pytest.mark.parametrize("script", sorted(_console_scripts()))
def test_every_console_script_prints_the_version_and_exits_zero(script, capsys):
    """Run through the entry point the wheel installs, with no other argument."""
    entry = _resolve(_console_scripts()[script])
    with pytest.raises(SystemExit) as exc:
        entry(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == version_string()
    assert _declared_version() in captured.out


@pytest.mark.parametrize("module", ["ghost_writer.cli", "ghost_writer.triage", "blackhole_extrapolator.cli",
                                    "stack_census.cli", "ghost_buster.consequence", "ghost_buster.cli"])
def test_python_dash_m_prints_the_version_too(module):
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-m", module, "--version"], capture_output=True, text=True,
                            cwd=PYPROJECT.parent)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == version_string()
