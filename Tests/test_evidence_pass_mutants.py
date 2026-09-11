"""The proof that this pass's tests are not vacuous.

Four claims, four suites, one mutant list: carried criteria are labelled,
a model's claim is not authoritative, the running source names the version,
and the mutant census counts what is there.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

_R = "ghost_buster/readiness.py"
_S = "ghost_buster/schema.py"
_L = "ghost_buster/ledger.py"
_B = "ghost_buster/baseline.py"
_I = "ghost_buster/__init__.py"
_O = "ghost_buster/operate.py"

CARRIED = "Tests/test_readiness.py"
BOUNDARY = "Tests/test_authoritative_boundary.py"
VERSION = "Tests/test_version_provenance.py"
CENSUS = "Tests/test_mutant_census.py"

MUTANTS = [
    # (label, file, exact text to replace, replacement)
    ("carried evidence is printed as though it were fresh", _R,
     '            note = "  [carried from the workup, not re-established]" if c.carried else ""\n',
     '            note = ""\n'),
    ("the carried flag is accepted and dropped", _R,
     "        c if c.name not in carried else Criterion(c.name, c.met, c.evidence, carried=True)\n",
     "        c\n"),
    ("an operation calls nothing carried", _O,
     "    carried = (readiness.TESTS, readiness.SECRETS) if op.cuts else ()\n",
     "    carried = ()\n"),
    ("a claim is authoritative after all", _S,
     "AUTHORITATIVE = frozenset({Status.CONFIRMED, Status.CONFIRMED_BY_REVIEW, Status.SUPPRESSED})",
     "AUTHORITATIVE = frozenset({Status.CONFIRMED, Status.CONFIRMED_BY_REVIEW, Status.SUPPRESSED, Status.REASONED})"),
    ("a human's verification stops counting as evidence", _S,
     "AUTHORITATIVE = frozenset({Status.CONFIRMED, Status.CONFIRMED_BY_REVIEW, Status.SUPPRESSED})",
     "AUTHORITATIVE = frozenset({Status.CONFIRMED})"),
    ("the gate reads claims again", _R,
     "    findings = authoritative(findings)\n",
     "    findings = list(findings)\n"),
    ("the ledger remembers claims again", _L,
     "        findings = authoritative(f for f in findings if f.detector != DETECTOR)\n",
     "        findings = [f for f in findings if f.detector != DETECTOR]\n"),
    ("the baseline accepts a claim", _B,
     "        for f in authoritative(findings):\n",
     "        for f in findings:\n"),
    ("installed metadata answers first again", _I,
     "    pyproject = Path(__file__).resolve().parent.parent / \"pyproject.toml\"\n    try:\n        with pyproject.open(\"rb\") as fh:\n",
     "    try:\n        return _installed_version(_DISTRIBUTION)\n    except PackageNotFoundError:\n        pass\n    pyproject = Path(__file__).resolve().parent.parent / \"pyproject.toml\"\n    try:\n        with pyproject.open(\"rb\") as fh:\n"),
]

CENSUS_MUTANTS = [
    ("the census counts files it cannot read as zero", "Tests/test_mutant_census.py",
     "    raise AssertionError(f\"{path.name} matches *_mutants.py but declares no MUTANTS list\")",
     "    return 0"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    tests = {
        _R: CARRIED if "carried" in label else BOUNDARY,
        _O: CARRIED,
        _S: BOUNDARY,
        _L: BOUNDARY,
        _B: BOUNDARY,
        _I: VERSION,
    }[rel]
    if rel == _O:
        tests = "Tests/test_operate.py"
    assert_killed(label, tests, run_tests_with_mutation(tests, rel, old, new))


def test_the_suites_pass_unmutated():
    """The control: a no-op substitution in a file each suite depends on.
    Without it, a mutant list that kills everything because the suite is
    broken would look like proof."""
    for tests, rel, anchor in ((BOUNDARY, _S, "def authoritative("),
                               (VERSION, _I, "def _read_version("),
                               (CENSUS, _S, "def disambiguate_ids(")):
        result = run_tests_with_mutation(tests, rel, anchor, anchor)
        assert result.returncode == 0, f"{tests}: {result.stdout[-1500:]}"
