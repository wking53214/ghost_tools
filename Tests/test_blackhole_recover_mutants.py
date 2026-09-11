"""The proof that Tests/test_blackhole_recover.py is not vacuous.

This module writes files that a person may then commit as real source, so
the mutants that matter are the ones that loosen a match. Three of them
restore a version that shipped in a first draft and was caught by running
against a real 37-repository library: a plain substring search that matched
mid-token, a one-directional overlap score that rewarded a candidate for
being large, and returning the first hit rather than the best one.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_blackhole_recover.py"
_R = "blackhole_extrapolator/recover.py"

MUTANTS = [
    # The invariant. If collapse stops normalising newlines, nothing that was
    # flattened can ever match its own original again.
    ("collapse stops treating a newline as whitespace", _R,
     '_WHITESPACE = re.compile(r"\\s+")', '_WHITESPACE = re.compile(r" +")'),
    ("collapse stops trimming the ends", _R,
     '    return _WHITESPACE.sub(" ", text).strip()',
     '    return _WHITESPACE.sub(" ", text)'),

    # Matching mid-token: the span then starts inside an identifier.
    ("containment goes back to a plain substring search", _R,
     "                start = bounded_find(collapsed, target)",
     "                start = collapsed.find(target)"),

    # A blob that contains everything contains everything.
    ("similarity is scored by coverage instead of union", _R,
     "                    score = len(wanted & ids) / len(wanted | ids)",
     "                    score = len(wanted & ids) / len(wanted)"),

    # First hit versus best hit: the fence inside a message is the exact
    # match, and the message around it is only a containing one.
    ("the first containing hit wins over an exact one", _R,
     "                if start != -1:\n                    contained = (source, start)",
     "                if start != -1:\n                    contained = (source, start)\n                    break"),

    # A recovery is bytes from the original, not a re-derivation.
    ("the span is rebuilt from the collapsed copy", _R,
     "    _, index = collapse_with_index(text)\n"
     "    return text[index[start]:index[start + len(target) - 1] + 1]",
     "    return target"),

    # What may be written at all.
    ("a related draft counts as a recovery", _R,
     "        return self.verdict in (IDENTICAL, CONTAINED) and self.text is not None",
     "        return self.verdict in (IDENTICAL, CONTAINED, RELATED)"),
    ("the write-time collapse check is dropped", _R,
     '    if collapse(recovery.text or "") != collapse(original):',
     "    if False:"),
    ("an existing recovery is overwritten", _R,
     "    if target.exists():\n"
     '        raise FileExistsError(f"{target} exists; refusing to overwrite a recovery")',
     "    if False:\n"
     '        raise FileExistsError(f"{target} exists; refusing to overwrite a recovery")'),

    # A flattened copy in the corpus collapses to the same thing because it
    # IS the same thing, and is not the original of anything.
    ("a candidate with no line breaks is a valid original", _R,
     "MINIMUM_LINES = 3", "MINIMUM_LINES = 0"),

    # A repair must demonstrate that it helped.
    ("a substitution is applied whether or not it helps", _R,
     "    candidate = text.replace(NBSP, \" \")\n"
     "    if parses(candidate):\n"
     "        return candidate, (REPAIR_NBSP,)\n"
     "    return text, ()",
     "    return text.replace(NBSP, \" \"), (REPAIR_NBSP,)"),
    ("a file that already parses is repaired anyway", _R,
     "    if parses(text) or NBSP not in text:\n        return text, ()",
     "    if NBSP not in text:\n        return text, ()"),
    ("parsing stops requiring a statement", _R,
     "        return bool(ast.parse(text).body)", "        ast.parse(text)\n        return True"),

    # Names that collide across repositories.
    ("the recovered name drops the path again", _R,
     "            return relative.with_suffix(\"\").as_posix().replace(\"/\", \"__\") + \".recovered.py\"",
     "            return path.stem + \".recovered.py\""),

    # Corpus reading.
    ("the reader stops descending into lists", _R,
     "    elif isinstance(node, list):\n        for value in node:\n            yield from _strings(value)",
     "    elif isinstance(node, list):\n        return"),
    ("an html-encoded corpus is left encoded", _R,
     "    yield text\n    if _ENTITY.search(text):",
     "    yield text\n    if False:"),
    ("fenced blocks are no longer harvested", _R,
     "        for block in _FENCE.findall(variant):", "        for block in ():"),
    ("prose is harvested as code", _R,
     "    return (text.count(\"\\n\") >= MINIMUM_LINES\n"
     "            and any(marker in text for marker in _PYTHONISH))",
     "    return text.count(\"\\n\") >= MINIMUM_LINES"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_recover_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_recover_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(TESTS, _R, "MINIMUM_LINES = 3", "MINIMUM_LINES = 3")
    assert result.returncode == 0, result.stdout[-2000:]
