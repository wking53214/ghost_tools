"""The proof that Tests/test_statusclaim.py is not vacuous: break
ghost_buster/statusclaim.py one way at a time in a scratch copy and run only
that file. Every mutant here must be killed.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_statusclaim.py"
_S = "ghost_buster/statusclaim.py"

MUTANTS = [
    ("a negated claim is reported", _S,
     "            if _NEGATED.search(before) or _ATTRIBUTED.search(before) or _quoted(text, m.start(), m.end()):\n",
     "            if _ATTRIBUTED.search(before) or _quoted(text, m.start(), m.end()):\n"),
    ("an attributed claim is reported", _S,
     "            if _NEGATED.search(before) or _ATTRIBUTED.search(before) or _quoted(text, m.start(), m.end()):\n",
     "            if _NEGATED.search(before) or _quoted(text, m.start(), m.end()):\n"),
    ("a critic's note about a claim is reported as a claim", _S,
     "            if _DISCUSSED_AFTER.search(after):\n                continue\n",
     "            if False:\n                continue\n"),
    ("a phrase wrapped in its own quotes is reported", _S,
     "    return wrapped\n",
     "    return False\n"),
    ("the identity changes when the line moves", _S,
     "                identity_key=f\"{kind}: {phrase}\",\n",
     "                identity_key=None,\n"),
    ("a dressed-up claim slips past", _S,
     "    text = _as_read(_strip_code_spans(line))\n",
     "    text = _strip_code_spans(line)\n"),
    ("a claim inside backticks is reported", _S,
     "    text = _as_read(_strip_code_spans(line))\n",
     "    text = _as_read(line)\n"),
    ("a changelog is read as a live document", _S,
     "        if path.suffix.lower() != \".md\" or _is_history(path):\n",
     "        if path.suffix.lower() != \".md\":\n"),
    ("a fenced block is read as prose", _S,
     "        if fence is None and m:\n",
     "        if False:\n"),
    ("the test-file count is not measured", _S,
     "    test_files = sum(1 for p in paths if p.suffix == \".py\" and (is_test_path(p) or p.name.endswith(\"_test.py\")))\n",
     "    test_files = 0\n"),
]


@pytest.mark.parametrize("label, path, old, new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, path, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, path, old, new))
