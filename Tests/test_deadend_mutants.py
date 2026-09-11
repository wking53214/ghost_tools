"""The proof that Tests/test_deadend.py is not vacuous.

Ten of the eleven candidates in a real measurement were deliberate, so this
detector lives or dies on its silence. Most of these mutants remove one
exclusion and check that the suite notices the noise coming back; the rest
remove the evidence that makes it speak at all.

One of them is not hypothetical. The first version of the no-op name check
was a regex with re.IGNORECASE whose boundary class was `[A-Z_0-9]`, and
IGNORECASE makes that match lowercase too -- so the boundary did not exist
and `nullify_cache` was silently treated as a Null object.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_deadend.py"
_D = "ghost_buster/deadend.py"

MUTANTS = [
    # ---- the evidence that makes it speak
    ("an uncalled stub is reported too", _D,
     "            if h.name in index.called", "            if True"),
    ("a docstring counts as an implementation", _D,
     "        body = body[1:]\n        if not body:\n            return DOCSTRING_ONLY",
     "        body = body[1:]\n        if not body:\n            return None"),
    ("a body with real statements is called empty", _D,
     "    if not body or len(body) > 1:\n        return None",
     "    if not body:\n        return None"),
    ("a raise of anything counts as NotImplementedError", _D,
     '        if name == "NotImplementedError":\n            return RAISES',
     "        return RAISES"),

    # ---- the four ways a seam declares itself
    ("an abstract or Protocol base stops counting", _D,
     "    if hollow.owner in index.abstract_classes:",
     "    if False:"),
    ("@abstractmethod stops counting", _D,
     "    if hollow.qualified in index.abstract_methods:",
     "    if False:"),
    ("an implementing subclass stops counting", _D,
     "    for sub in subclasses.get(hollow.owner, []):\n"
     "        if hollow.name in index.real_methods.get(sub, ()):",
     "    for sub in ():\n"
     "        if hollow.name in index.real_methods.get(sub, ()):"),
    ("ancestry stops being walked past the immediate base", _D,
     "            if base and base not in seen:\n"
     "                seen.add(base)\n"
     "                self.ancestry(base, seen)",
     "            if base and base not in seen:\n"
     "                seen.add(base)"),
    ("a second real definition of a function stops counting", _D,
     "        if hollow.name in index.real_functions:",
     "        if False:"),

    # ---- an empty body that IS the implementation
    ("the Null Object and test-double convention is ignored", _D,
     "    return is_no_op_name(hollow.owner or hollow.name) or is_no_op_name(hollow.name)",
     "    return False"),
    ("the no-op prefix stops needing a word boundary", _D,
     "            if not rest or rest[0].isupper() or rest[0] == \"_\" or rest[0].isdigit():",
     "            if True:"),
    ("a stateless __init__ is a dead end again", _D,
     "def _deliberate_no_op(hollow: Hollow) -> bool:\n"
     "    if hollow.name in _EMPTY_IS_NORMAL:",
     "def _deliberate_no_op(hollow: Hollow) -> bool:\n"
     "    if False:"),

    # ---- test code
    ("a method stub defined in a test file is reported", _D,
     "                elif not test:\n"
     "                    self.hollows.append(Hollow(path, cls.name, node.name,",
     "                else:\n"
     "                    self.hollows.append(Hollow(path, cls.name, node.name,"),
    ("a function stub defined in a test file is reported", _D,
     "            elif not test:\n"
     "                self.hollows.append(Hollow(path, None, node.name, shape, node.lineno))",
     "            else:\n"
     "                self.hollows.append(Hollow(path, None, node.name, shape, node.lineno))"),
    ("a call from a test counts as live code", _D,
     "            if not test:\n                self._note_calls(tree)",
     "            if True:\n                self._note_calls(tree)"),

    # ---- the loud/silent distinction
    ("silence is rated no worse than a crash", _D,
     "            severity=Severity.MINOR if loud else Severity.MAJOR,",
     "            severity=Severity.MINOR,"),

    # ---- the honesty of the claim
    ("the finding starts claiming never", _D,
     '                  "scan was not pointed at would settle it; scan the siblings "\n'
     '                  "if the answer matters."',
     '                  "scan was not pointed at cannot exist. Nothing will ever "\n'
     '                  "provide one."'),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_deadend_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_deadend_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(TESTS, _D, 'DETECTOR = "dead_end_call"',
                                     'DETECTOR = "dead_end_call"')
    assert result.returncode == 0, result.stdout[-2000:]
