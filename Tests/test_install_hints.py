"""No install hint that a user can read names a bare PyPI distribution of this stack.

The hint `pip install 'ghost-tools[cns]'` resolved on PyPI to the owner's older ghost-tools 1.6.0, which has no `cns`
extra (its extras are `semantic` and `dev`), so it installed the wrong thing and the CNS tests and adapter stayed
unusable. The stack's repositories are not published to PyPI under their own names as these versions; what works is an
install from a checkout (`pip install -e '.[cns]'`) or from the repository at a pinned tag
(`pip install "cns @ git+https://github.com/wking53214/CNS.git@v1.9.0"`).

The check reads every file a user reads (README, STACK, PROVENANCE, docs, the shipped Python, the workflows and
scripts), finds each `pip install ...` command and fails on a requirement that is a bare name of a circuit
distribution. CHANGELOG.md is history and is not read, and neither are the tests, which quote the bad hint to prove
the check finds it.
"""
from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path
from typing import List

from ghost_buster import cns_adapter

ROOT = Path(__file__).resolve().parent.parent

#: Distribution names of the circuit. Normalised the way pip does (case folded, runs of - _ . become -).
CIRCUIT = {"ghost-tools", "ghost-buster", "ghost-writer", "ghost-triage", "blackhole-extrapolator", "stack-census",
           "ghost-rank", "swizzle", "assay", "assay-production", "warden", "judge", "drafter", "burnish",
           "watcher", "watcher-mcu", "cns"}

#: pip options that take a value as the next word.
_TAKES_VALUE = {"-e", "--editable", "-r", "--requirement", "-c", "--constraint", "-i", "--index-url",
                "--extra-index-url", "-f", "--find-links", "-t", "--target", "--prefix", "--root", "--python"}

_COMMAND = re.compile(r"\bpip3?\s+install\s+([^`;\n]*)")


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.lower())


def bare_circuit_requirements(text: str) -> List[str]:
    """Requirements in `text`'s pip install commands that are a bare circuit distribution (with or without extras
    or a version), as written."""
    found = []
    for match in _COMMAND.finditer(text):
        args = re.sub(r"[\"']?[\w.\-]+(\[[^\]]*\])?\s*@\s*\S+", " ", match.group(1))   # name @ url: a pinned source
        try:
            words = shlex.split(args)
        except ValueError:
            words = args.split()
        skip = False
        for word in words:
            if skip:
                skip = False
                continue
            if word in _TAKES_VALUE:
                skip = True
                continue
            word = word.strip("\"'()").rstrip(",.;:")
            if not word or word.startswith(("-", ".", "/", "~")) or "://" in word or "$" in word or "{" in word:
                continue
            name = re.match(r"[A-Za-z0-9][A-Za-z0-9._\-]*", word)
            if name and _normalise(name.group(0)) in CIRCUIT:
                found.append(word)
    return found


def _user_facing_files() -> List[Path]:
    files = [ROOT / "README.md", ROOT / "STACK.md", ROOT / "PROVENANCE.md"]
    files += sorted((ROOT / "docs").rglob("*.md"))
    for package in ("ghost_buster", "ghost_writer", "blackhole_extrapolator", "stack_census", "tools"):
        files += sorted((ROOT / package).rglob("*.py"))
    files += sorted((ROOT / ".github").rglob("*.yml")) + sorted((ROOT / ".github").rglob("*.sh"))
    files.append(ROOT / "pyproject.toml")
    return [path for path in files if path.is_file()]


def test_the_checker_finds_the_hint_that_installed_the_wrong_thing():
    assert bare_circuit_requirements("pip install 'ghost-tools[cns]'") == ["ghost-tools[cns]"]
    assert bare_circuit_requirements("`pip install ghost_tools`") == ["ghost_tools"]
    assert bare_circuit_requirements("python -m pip install pytest Swizzle==0.8.5") == ["Swizzle==0.8.5"]
    assert bare_circuit_requirements("pip install -q cns") == ["cns"]


def test_the_checker_accepts_the_commands_that_work():
    assert bare_circuit_requirements("pip install -e '.[cns]'") == []
    assert bare_circuit_requirements('pip install -e ".[dev]"') == []
    assert bare_circuit_requirements('pip install "cns @ git+https://github.com/wking53214/CNS.git@v1.9.0"') == []
    assert bare_circuit_requirements("python -m pip install ./swizzle pytest") == []
    assert bare_circuit_requirements("pip install -r requirements.txt anthropic") == []


def test_no_user_facing_install_hint_names_a_bare_pypi_distribution_of_the_stack():
    bad = {}
    for path in _user_facing_files():
        found = bare_circuit_requirements(path.read_text(encoding="utf-8"))
        if found:
            bad[str(path.relative_to(ROOT))] = found
    assert not bad, f"install hints that resolve to the wrong package on PyPI: {bad}"


def test_the_adapters_install_hint_gives_a_checkout_command_and_the_pinned_cns_source():
    pin = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"]["optional-dependencies"]["cns"][0]
    hint = cns_adapter.INSTALL_HINT
    assert "pip install -e '.[cns]'" in hint
    assert f'pip install "{pin}"' in hint
    assert bare_circuit_requirements(hint) == []
