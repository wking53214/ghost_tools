"""The proof that Tests/test_naming.py is not vacuous.

Each mutant restores a version that either invented a seam it could not see,
reported the success of a refactor as its failure, or swallowed its own
fixtures. The last one is not hypothetical -- the first draft of this
detector skipped any path whose parent directory CONTAINED "test", which is
what pytest names its tmp_path after, so every test of it passed against a
detector that had examined nothing.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_naming.py"
_N = "ghost_buster/naming.py"

MUTANTS = [
    # Abstention: one cassette cannot distinguish a domain word from the
    # engine's own, and guessing anyway is the whole failure mode.
    ("one cassette is enough to name a domain", _N,
     "MINIMUM_CASSETTES = 2", "MINIMUM_CASSETTES = 1"),
    ("the seam requirement is dropped entirely", _N,
     "    if len(cassettes) < MINIMUM_CASSETTES:\n        return []",
     "    if False:\n        return []"),

    # The four filters that define a domain word. Each removal either floods
    # the report or empties it.
    ("a word in BOTH cassettes counts as one domain's", _N,
     "            if seen_in[word] == 1", "            if seen_in[word] >= 1"),
    ("generic Python vocabulary is no longer excluded", _N,
     "            and word not in contract_words and word not in generic",
     "            and word not in contract_words"),
    ("the measured false positives come back", _N,
     "            and word not in _ORDINARY_ENGLISH", "            and True"),

    # The frequency threshold that measurement removed: it deleted every
    # real pediatric term while keeping the noise.
    ("the frequency threshold returns", _N,
     "            if seen_in[word] == 1\n",
     "            if seen_in[word] == 1 and uses > 1\n"),

    # Reporting a cassette for carrying its own domain's words.
    ("cassettes are reported for being cassettes", _N,
     "        if path.name in cassette_names or path.name == \"cassette.py\":\n            continue",
     "        if False:\n            continue"),

    # The skip rule that swallowed the fixtures.
    ("the test-directory check goes back to a substring match", _N,
     "    return path.name.startswith(\"test_\") or path.parent.name.lower() in _TEST_DIRS",
     "    return path.name.startswith(\"test_\") or \"test\" in path.parent.name.lower()"),

    # Placeholders: a measurement must never be read as a leftover.
    ("a measurement is treated as a placeholder again", _N,
     '    "data2", "test1", "thing1", "untitled",',
     '    "data2", "test1", "thing1", "untitled", "temp", "bar",'),
    ("placeholder matching becomes a substring search", _N,
     "            if lowered in _PLACEHOLDER_EXACT or lowered.endswith(_PLACEHOLDER_SUFFIX):",
     "            if lowered in _PLACEHOLDER_EXACT or any(x in lowered for x in _PLACEHOLDER_SUFFIX):"),

    # Severity: a name is not a defect.
    ("a naming finding is raised above MINOR", _N,
     "                severity=Severity.MINOR,\n                status=Status.CONFIRMED,\n"
     "                summary=(f\"{path.name} carries",
     "                severity=Severity.MAJOR,\n                status=Status.CONFIRMED,\n"
     "                summary=(f\"{path.name} carries"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_naming_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_naming_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(TESTS, _N, "MINIMUM_CASSETTES = 2", "MINIMUM_CASSETTES = 2")
    assert result.returncode == 0, result.stdout[-2000:]
