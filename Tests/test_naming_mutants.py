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

    # ------------------------------------------- one thing under two names

    # The 1:1 requirement, both directions. Dropping either produces a
    # rename that collides with a name legitimately in use elsewhere.
    ("a parameter taking several variables is reported anyway", _N,
     "        if len(args) != 1:\n            continue",
     "        if False:\n            continue"),
    ("a variable reaching several parameters is reported anyway", _N,
     "        if not _renamable(param, arg) or len(to_param[arg]) != 1:",
     "        if not _renamable(param, arg):"),

    # Somebody else's function, and two of ours sharing a name. Both were
    # measured false positives, and the second was the worst of them.
    ("an unresolvable call is reconciled anyway", _N,
     "            if resolved is None:\n                continue",
     "            if False:\n                continue"),
    ("two definitions of a name are no longer ambiguous", _N,
     "        found = self.everywhere.get(name)\n        if found is None or len(found) != 1:",
     "        found = self.everywhere.get(name)\n        if found is None:"),
    ("a same-file duplicate is resolved by picking the first", _N,
     "            if len(here) != 1:\n                return None",
     "            if False:\n                return None"),
    ("a stranger's module wins over the local definition", _N,
     "        here = self.per_file.get(str(path), {}).get(name)\n        if here is not None:",
     "        here = None\n        if here is not None:"),
    ("any attribute call is treated as ours", _N,
     "    if (isinstance(node.func, ast.Attribute)\n"
     "            and isinstance(node.func.value, ast.Name)\n"
     "            and node.func.value.id in (\"self\", \"cls\")):",
     "    if isinstance(node.func, ast.Attribute):"),

    # The three exclusions in _renamable, each an observed false positive.
    ("a constant is renamed after the parameter it is passed to", _N,
     "    if param.isupper() or arg.isupper():\n        return False",
     "    if False:\n        return False"),
    ("privacy stops being part of the name", _N,
     "    if param.startswith(\"_\") != arg.startswith(\"_\"):\n        return False",
     "    if False:\n        return False"),
    ("camelCase is treated as ours to rename", _N,
     "    return not (_CAMEL.search(param) or _CAMEL.search(arg))",
     "    return True"),

    # Keyword arguments carry the same disagreement as positional ones.
    ("keyword arguments stop being read", _N,
     "                if kw.arg and isinstance(kw.value, ast.Name):",
     "                if False:"),

    # Severity: a name is not a defect.
    ("a disagreement finding is raised above MINOR", _N,
     "            severity=Severity.MINOR,\n            status=Status.CONFIRMED,\n"
     "            summary=(f\"`{d.param}` and `{d.arg}` are one value under two names, \"",
     "            severity=Severity.MAJOR,\n            status=Status.CONFIRMED,\n"
     "            summary=(f\"`{d.param}` and `{d.arg}` are one value under two names, \""),
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
