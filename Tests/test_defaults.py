"""Every check is on by default, and no check is ever silently absent.

THE FAILURE THIS FILE GUARDS AGAINST (v0.11.0)

Until 0.10.1, --branches, --tests and --secrets were opt-in, and a run that
did not perform one said nothing whatsoever about it. Measured on a real
repository: `ghost-buster . --branches --secrets` printed 34 findings and
exit 1, looked like a complete audit, and never mentioned that test status
had gone unexamined. That suite was hiding five clinical missed detections
behind skips that --tests rates MAJOR.

Two rules follow, and both are tested here:

  1. The checks are on unless the caller turns them off.
  2. A check that does not run says so -- whether it was declined
     (--no-X), impossible (not a git repo, no tests), or opt-in on cost
     (--mutate). Silence about a check is the bug.
"""
from __future__ import annotations

import pytest

from ghost_buster.cli import _build_parser, main

# (attribute, opt-out flag, the phrase that must appear when declined)
CHECKS = [
    ("branches", "--no-branches", "branch scan SKIPPED at your request (--no-branches)"),
    ("tests", "--no-tests", "test status scan SKIPPED at your request (--no-tests)"),
    ("secrets", "--no-secrets", "secrets scan SKIPPED at your request (--no-secrets)"),
]

# Every check must be accounted for in the stderr of EVERY run, whatever
# state it is in. Matched as "the check is named at all", so a run that
# performs it, declines it, or cannot do it all satisfy the invariant --
# and a run that quietly omits it does not.
ACCOUNTED_FOR = ["branch scan", "test", "secrets scan", "correlation", "mutation analysis"]


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "m.py").write_text("x = 1\n")
    return proj


def _run(project, tmp_path, *flags):
    return main([str(project), "--baseline", str(tmp_path / "b.json"), *flags])


@pytest.mark.parametrize("attr,_flag,_phrase", CHECKS, ids=[c[0] for c in CHECKS])
def test_check_is_on_by_default(attr, _flag, _phrase):
    args = _build_parser().parse_args(["."])
    assert getattr(args, attr) is True


@pytest.mark.parametrize("attr,flag,_phrase", CHECKS, ids=[c[0] for c in CHECKS])
def test_check_can_still_be_turned_off(attr, flag, _phrase):
    args = _build_parser().parse_args([".", flag])
    assert getattr(args, attr) is False


@pytest.mark.parametrize("attr,_flag,_phrase", CHECKS, ids=[c[0] for c in CHECKS])
def test_explicit_positive_flag_still_works(attr, _flag, _phrase):
    """`--tests` was the only way to ask before 0.11.0. Scripts that pass it
    must keep working, not error on an unrecognised argument."""
    args = _build_parser().parse_args([".", f"--{attr}"])
    assert getattr(args, attr) is True


def test_mutation_stays_opt_in():
    """The one exception, and it is a cost exception, not a value one: one
    pytest process per mutant. A default that takes hours does not get run."""
    assert _build_parser().parse_args(["."]).mutate is False


@pytest.mark.parametrize("attr,flag,phrase", CHECKS, ids=[c[0] for c in CHECKS])
def test_declining_a_check_leaves_a_receipt(attr, flag, phrase, project, tmp_path, capsys):
    _run(project, tmp_path, flag)
    assert phrase in capsys.readouterr().err


def test_mutation_being_off_is_announced(project, tmp_path, capsys):
    _run(project, tmp_path)
    assert "mutation analysis NOT RUN (opt-in: --mutate)" in capsys.readouterr().err


def test_correlation_opt_out_leaves_a_receipt(project, tmp_path, capsys):
    _run(project, tmp_path, "--no-correlate")
    assert "correlation SKIPPED at your request (--no-correlate)" in capsys.readouterr().err


@pytest.mark.parametrize("flags", [
    (),
    ("--no-branches",),
    ("--no-tests",),
    ("--no-secrets",),
    ("--no-correlate",),
    ("--no-branches", "--no-tests", "--no-secrets", "--no-correlate"),
], ids=["defaults", "no-branches", "no-tests", "no-secrets", "no-correlate", "all-off"])
def test_no_check_is_ever_silently_absent(flags, project, tmp_path, capsys):
    """The invariant, stated once. Whatever the caller asks for, the reader
    of the output can tell what was looked at and what was not."""
    _run(project, tmp_path, *flags)
    err = capsys.readouterr().err
    missing = [name for name in ACCOUNTED_FOR if name not in err]
    assert not missing, f"unaccounted for with {flags or '(defaults)'}: {missing}\n{err}"
