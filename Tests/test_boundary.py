"""The seam between two repositories.

A cross-repo boundary is the one place both sides are blind: the
importing repository guards the import and skips its tests when the other
is absent, and the providing repository has never heard of the importer.
So these tests are built around two-repo fixtures, because a one-repo
fixture cannot express the thing being checked.
"""
from __future__ import annotations

import json

import pytest

from ghost_buster.boundary import (
    build_joined_model, derive_findings, render_report, render_single_repo_notice,
)
from ghost_buster.cli import main
from ghost_buster.pipeline import _collect_files
from ghost_buster.schema import Severity

GUARDED = '''import sys

try:
    from provider import {names}
except ImportError:
    {fallback} = {nones}
'''


def _consumer(tmp_path, names=("Thing",), package="provider", source=None,
              extra=None, name="consumer"):
    root = tmp_path / name
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "__init__.py").write_text("")
    body = GUARDED.format(
        names=", ".join(names), fallback=", ".join(names),
        nones=", ".join(["None"] * len(names)),
    ).replace("from provider import", f"from {source or package} import")
    (root / "app" / "adapter.py").write_text(body)
    for name, text in (extra or {}).items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def _provider(tmp_path, body="class Thing:\n    pass\n", extra=None,
              name="provider_repo"):
    root = tmp_path / name
    (root / "provider").mkdir(parents=True, exist_ok=True)
    (root / "provider" / "__init__.py").write_text(body)
    for name, text in (extra or {}).items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def _join(*roots):
    files_by_root = {str(r.resolve()): _collect_files(r) for r in roots}
    joined = build_joined_model(list(roots), files_by_root)
    return joined, derive_findings(joined, files_by_root)


def _kinds(findings):
    return {f.attributes["kind"] for f in findings}


# --------------------------------------------------------- the seam resolves

def test_a_resolvable_import_with_a_test_is_silent(tmp_path):
    consumer = _consumer(tmp_path, extra={
        "tests/test_adapter.py": "from app.adapter import Thing\n\n\ndef test_t():\n    assert Thing\n"})
    joined, findings = _join(consumer, _provider(tmp_path))
    assert "cross repo import unresolved" not in _kinds(findings)
    assert "boundary symbol untested" not in _kinds(findings)


def test_a_symbol_the_provider_does_not_export_is_critical(tmp_path):
    """Neither repository's CI can catch this. It fails at the join."""
    joined, findings = _join(_consumer(tmp_path, names=("Missing",)), _provider(tmp_path))
    unresolved = [f for f in findings if f.attributes["kind"] == "cross repo import unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0].severity == Severity.CRITICAL
    assert "Missing" in unresolved[0].summary


@pytest.mark.parametrize("guard", [
    "ImportError", "ModuleNotFoundError", "(ImportError, AttributeError)", "Exception",
])
def test_every_way_of_writing_the_guard_declares_a_boundary(tmp_path, guard):
    """observe-perceive's own adapter says it: "ModuleNotFoundError is the
    ordinary case; a bare ImportError means a partial or shadowing package,
    which is equally not available." A checker that only understands one
    spelling misses most real seams."""
    root = tmp_path / f"c_{abs(hash(guard))}"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "a.py").write_text(
        f"try:\n    from provider import Thing\nexcept {guard}:\n    Thing = None\n")
    _, findings = _join(root, _provider(tmp_path))
    assert "boundary symbol untested" in _kinds(findings), (
        f"a guard written as `except {guard}` still declares a boundary"
    )


def test_a_module_level_constant_counts_as_an_export(tmp_path):
    """Collecting only defs and classes reported MINIMUM_MATCH_LENGTH as
    missing from a real package that exports it on line one."""
    provider = _provider(tmp_path, body="MINIMUM_MATCH_LENGTH = 12\n")
    joined, findings = _join(_consumer(tmp_path, names=("MINIMUM_MATCH_LENGTH",)), provider)
    assert "cross repo import unresolved" not in _kinds(findings)


def test_a_submodule_import_resolves_against_that_submodule(tmp_path):
    """`from provider.matching import X` must be checked against
    provider.matching. Resolving it against every module in the package
    would accept a name that lives somewhere else entirely."""
    provider = _provider(tmp_path, extra={
        "provider/matching.py": "LIMIT = 3\n",
        "provider/other.py": "ELSEWHERE = 1\n",
    })
    _, ok = _join(_consumer(tmp_path, names=("LIMIT",), source="provider.matching",
                            name="c_ok"), provider)
    assert "cross repo import unresolved" not in _kinds(ok)

    _, bad = _join(_consumer(tmp_path, names=("ELSEWHERE",), source="provider.matching",
                             name="c_bad"), provider)
    assert "cross repo import unresolved" in _kinds(bad), (
        "a name from a different submodule must not satisfy this import"
    )


# ------------------------------------------------- are new tests necessary

def test_a_crossing_symbol_no_test_mentions_is_major(tmp_path):
    """The mechanical form of 'is a new test needed here'."""
    joined, findings = _join(_consumer(tmp_path), _provider(tmp_path))
    untested = [f for f in findings if f.attributes["kind"] == "boundary symbol untested"]
    assert len(untested) == 1
    assert untested[0].severity == Severity.MAJOR
    assert "Thing" in untested[0].summary


def test_a_dormant_test_counts_as_covering_the_boundary(tmp_path):
    """A test written for the seam and waiting for the other side is
    exactly right. It must not also be reported as a missing test."""
    consumer = _consumer(tmp_path, extra={
        "tests/test_seam.py": (
            "import pytest\n\n"
            "try:\n    from provider import Thing\n"
            "except ImportError:\n    Thing = None\n\n"
            "@pytest.mark.skipif(Thing is None, reason='provider not available')\n"
            "def test_thing():\n    assert Thing\n"),
    })
    _, findings = _join(consumer, _provider(tmp_path))
    assert "boundary symbol untested" not in _kinds(findings)


# -------------------------------------------------------------- inventory

def test_a_dormant_test_is_inventoried_not_complained_about(tmp_path):
    consumer = _consumer(tmp_path, extra={
        "tests/test_seam.py": (
            "import pytest\n\n"
            "def test_x():\n    pytest.skip('provider checkout not available')\n"),
    })
    _, findings = _join(consumer, _provider(tmp_path))
    dormant = [f for f in findings if f.attributes["kind"] == "dormant boundary test"]
    assert len(dormant) == 1
    assert dormant[0].severity == Severity.INFORMATIONAL


def test_a_skip_for_an_ordinary_reason_is_not_a_dormant_boundary(tmp_path):
    """`skip('too slow')` is not a seam waiting to wake up."""
    consumer = _consumer(tmp_path, extra={
        "tests/test_slow.py": "import pytest\n\n\ndef test_x():\n    pytest.skip('too slow')\n"})
    _, findings = _join(consumer, _provider(tmp_path))
    assert "dormant boundary test" not in _kinds(findings)


def test_reaching_for_a_repo_that_was_not_joined_is_minor(tmp_path):
    consumer = _consumer(tmp_path, package="somewhere_else", source="somewhere_else")
    _, findings = _join(consumer, _provider(tmp_path))
    absent = [f for f in findings if f.attributes["kind"] == "boundary provider absent"]
    assert len(absent) == 1
    assert absent[0].severity == Severity.MINOR


def test_reaching_for_itself_is_not_a_boundary(tmp_path):
    root = tmp_path / "solo"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("class Thing:\n    pass\n")
    (root / "app" / "b.py").write_text(
        "try:\n    from app import Thing\nexcept ImportError:\n    Thing = None\n")
    other = _provider(tmp_path)
    _, findings = _join(root, other)
    assert "cross repo import unresolved" not in _kinds(findings)
    assert "boundary symbol untested" not in _kinds(findings)


def test_an_unguarded_import_is_not_a_declared_boundary(tmp_path):
    """A boundary is declared by writing a fallback for it. A plain import
    with no guard is an ordinary hard dependency, and undeclared-dependency
    in structure.py is the check for that."""
    root = tmp_path / "hard"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "x.py").write_text("from provider import Thing\n")
    _, findings = _join(root, _provider(tmp_path))
    assert findings == []


# ------------------------------------------------------- mode and plumbing

def test_one_repository_is_not_a_boundary(tmp_path):
    joined, findings = _join(_consumer(tmp_path))
    assert joined.ran is False
    assert findings == []
    assert "at least two repositories" in render_report(joined, findings)


def test_a_dynamic_import_is_recorded_as_unresolved(tmp_path):
    root = tmp_path / "dyn"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "d.py").write_text(
        "from importlib import import_module\n\n"
        "try:\n    m = import_module('provider')\nexcept ImportError:\n    m = None\n")
    joined, _ = _join(root, _provider(tmp_path))
    assert any("import_module" in u for u in joined.unresolved)


def test_a_single_repo_scan_says_it_is_looking_at_half_a_system(tmp_path):
    root = _consumer(tmp_path)
    notice = render_single_repo_notice(root, _collect_files(root))
    assert notice is not None
    assert "--join" in notice
    assert "provider" in notice


def test_a_guarded_stdlib_import_is_not_a_cross_repo_boundary(tmp_path):
    """`try: from importlib.metadata import x / except ImportError` is the
    ordinary way to support more than one Python version, not a seam with
    another repository. This project does exactly that, and the very first
    self-scan after the boundary check landed reported ghost_tools as
    reaching for an outside package called `importlib`."""
    root = tmp_path / "stdlib_guard"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "compat.py").write_text(
        "try:\n    from importlib.metadata import version\n"
        "except ImportError:\n    version = None\n")
    assert render_single_repo_notice(root, _collect_files(root)) is None

    _, findings = _join(root, _provider(tmp_path))
    assert "boundary provider absent" not in _kinds(findings)


def test_the_notice_reads_cleanly_with_only_dormant_tests(tmp_path):
    """It used to print an empty parenthesis when the package list was
    empty: "reaches for 0 package(s) it does not provide ()"."""
    root = tmp_path / "only_dormant"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text(
        "import pytest\n\n\ndef test_x():\n    pytest.skip('sibling not available')\n")
    notice = render_single_repo_notice(root, _collect_files(root))
    assert notice is not None
    assert "0 package(s)" not in notice
    assert "()" not in notice
    assert "1 dormant test(s)" in notice


def test_a_self_contained_repo_gets_no_notice(tmp_path):
    root = tmp_path / "solo"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("def go():\n    pass\n")
    assert render_single_repo_notice(root, _collect_files(root)) is None


def test_the_cli_does_not_prompt_when_stdin_is_not_a_terminal(tmp_path, capsys, monkeypatch):
    """A prompt in CI hangs the build forever, and a tool that hangs a
    build gets removed from the build."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    root = _consumer(tmp_path)
    main([str(root), "--no-tests", "--no-secrets", "--no-branches", "--no-ledger",
          "--no-project", "--no-structure", "--baseline", str(tmp_path / "b.json")])
    err = capsys.readouterr().err
    assert "--join" in err, "it must still say the seams went unchecked"
    assert "boundary scan joined" not in err


def test_single_repo_flag_skips_the_question(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    root = _consumer(tmp_path)
    main([str(root), "--single-repo", "--no-tests", "--no-secrets", "--no-branches",
          "--no-ledger", "--no-project", "--no-structure",
          "--baseline", str(tmp_path / "b.json")])
    assert "boundary scan joined" not in capsys.readouterr().err


def test_the_cli_joins_when_told_to(tmp_path, capsys):
    consumer, provider = _consumer(tmp_path), _provider(tmp_path)
    main([str(consumer), "--join", str(provider), "--no-tests", "--no-secrets",
          "--no-branches", "--no-ledger", "--no-project", "--no-structure",
          "--baseline", str(tmp_path / "b.json")])
    assert "boundary scan joined 2 repositories" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# What a single-repo run FILES the check as (1.8.0)
#
# "Nobody looked" and "there was nothing to look at" are different claims and
# the ledger had only the first, so every single-repository scan grew a
# blind-spot streak no action could clear -- the check could not run, because
# there was nothing for it to run on. Measured on ATS: 7 consecutive runs of
# a permanent finding reporting a gap that did not exist.
#
# The notice already draws the line, so the state follows it rather than
# assuming the worse of the two.
# ---------------------------------------------------------------------------

def _boundary_state(root, tmp_path, capsys):
    from ghost_buster.ledger import Ledger
    ledger_path = tmp_path / "led.json"
    main([str(root), "--single-repo", "--no-tests", "--no-secrets", "--no-branches",
          "--no-project", "--no-structure", "--ledger-path", str(ledger_path),
          "--baseline", str(tmp_path / "b.json")])
    capsys.readouterr()
    return Ledger(ledger_path).runs[-1].checks["boundary"], ledger_path


def test_a_repo_with_no_seam_files_the_boundary_check_as_not_applicable(tmp_path, capsys):
    from ghost_buster.ledger import NOT_APPLICABLE
    root = tmp_path / "solo"
    (root / "app").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "app" / "__init__.py").write_text("def go():\n    pass\n")
    state, _ = _boundary_state(root, tmp_path, capsys)
    assert state == NOT_APPLICABLE


def test_a_repo_with_an_unchecked_seam_still_files_it_as_not_run(tmp_path, capsys):
    """The half that must not soften. This repository DOES reach across a
    boundary and was scanned alone, so the seam really is unchecked and the
    streak it accrues is the point."""
    from ghost_buster.ledger import NOT_RUN
    root = _consumer(tmp_path)
    (root / ".git").mkdir(exist_ok=True)
    state, _ = _boundary_state(root, tmp_path, capsys)
    assert state == NOT_RUN


def test_a_seamless_repo_never_grows_a_boundary_blind_spot(tmp_path, capsys):
    """The consequence, end to end: the finding that could not be cleared."""
    from ghost_buster.ledger import BLIND_SPOT_AFTER
    root = tmp_path / "solo2"
    (root / "app").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "app" / "__init__.py").write_text("def go():\n    pass\n")
    for _ in range(BLIND_SPOT_AFTER + 2):
        _, ledger_path = _boundary_state(root, tmp_path, capsys)
    main([str(root), "--single-repo", "--json", "--no-tests", "--no-secrets",
          "--no-branches", "--no-project", "--no-structure",
          "--ledger-path", str(ledger_path), "--baseline", str(tmp_path / "b.json")])
    rows = json.loads(capsys.readouterr().out)
    assert not [r for r in rows if r.get("attributes", {}).get("check") == "boundary"]
