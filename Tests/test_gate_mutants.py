"""The proof that the quality-gate tests in test_ghost_writer.py are not
vacuous: break the gate one way at a time in a scratch copy of the project
and run only those tests. Every mutant must be killed.

ghost_buster --mutate finds candidates by shape (weak assertions, unread
results, guarded assertions, restated sets) and reported zero candidates in
test_ghost_writer.py, so it had nothing to mutate there. This file is the
hand-made complement for the one piece of logic whose failure mode is
"passes everything": each mutant below is a way the gate could be broken
while every existing test stays green, unless a test pins it.

A mutant that survives is a test-suite defect, reported here as a failure
with the mutant named. The working tree is never modified.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE_TESTS = "Tests/test_ghost_writer.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    ("correct: scoped empirical filter always passes", "ghost_writer/correct.py",
     "        return self._inner.passes(self._state.reasoning)\n",
     "        return True\n"),
    ("correct: empirical filter left unscoped", "ghost_writer/correct.py",
     "    pipeline.empirical_filter = _ReasoningScopedEmpiricalFilter(state)\n",
     ""),
    ("correct: reasoning withheld from the pronoun and speculation filters", "ghost_writer/correct.py",
     '        return f"{replacement}\\n{state.reasoning}"\n',
     '        return f"{replacement}"\n'),
    ("correct: reasoning recorded as a constant that passes", "ghost_writer/correct.py",
     '        state.reasoning = str(item.get("reasoning", ""))\n',
     '        state.reasoning = "evidence"\n'),
    ("correct: gate verdict ignored", "ghost_writer/correct.py",
     '    if result["execution_status"] != "SUCCESS":\n',
     "    if False:\n"),
    ("correct: attempt ceiling not passed through", "ghost_writer/correct.py",
     "        gateway, max_attempts=max_attempts, signing_key=_SIGNING_KEY,\n",
     "        gateway, signing_key=_SIGNING_KEY,\n"),
    ("pipeline: pronoun check forced true", "ghost_writer/polish/pipeline.py",
     "            pronoun_check = self.pronoun_filter.passes(normalized_response)\n",
     "            pronoun_check = True\n"),
    ("pipeline: speculation check forced true", "ghost_writer/polish/pipeline.py",
     "                self.speculation_filter.passes(normalized_response)\n",
     "                True\n"),
    ("pipeline: empirical check forced true", "ghost_writer/polish/pipeline.py",
     "            empirical_check = self.empirical_filter.passes(normalized_response)\n",
     "            empirical_check = True\n"),
    ("pipeline: retry loop runs once", "ghost_writer/polish/pipeline.py",
     "        for iteration in range(1, self.max_attempts + 1):\n",
     "        for iteration in range(1, 2):\n"),
    ("pipeline: feedback dropped from the retry prompt", "ghost_writer/polish/pipeline.py",
     '                f"{input_prompt}\\n\\n"\n                f"[RECALIBRATION FEEDBACK - Attempt {iteration}]:\\n"\n',
     '                f"{input_prompt}\\n\\n"\n'),
    ("filters: pronoun pattern matches nothing", "ghost_writer/polish/filters.py",
     'PRONOUNS = r"\\b(I|we|my|our|me|us)\\b"',
     'PRONOUNS = r"\\b(zzzz)\\b"'),
    ("filters: hedge pattern matches nothing", "ghost_writer/polish/filters.py",
     'HEDGES = r"\\b(might|may|could|seems|probably|perhaps|likely|i think|appears|arguably|suggest|may be)\\b"',
     'HEDGES = r"\\b(zzzz)\\b"'),
    ("filters: empirical contract inverted", "ghost_writer/polish/filters.py",
     "        return bool(re.search(self.EVIDENCE_MARKERS, text, re.IGNORECASE))\n",
     "        return not re.search(self.EVIDENCE_MARKERS, text, re.IGNORECASE)\n"),
]


def _run_gate_tests_with(rel: str, old: str, new: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        copy = pathlib.Path(tmp) / "ghost_tools"
        shutil.copytree(
            ROOT, copy,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv"),
        )
        target = copy / rel
        source = target.read_text()
        assert source.count(old) == 1, f"mutation site not found exactly once in {rel}: {old!r}"
        target.write_text(source.replace(old, new))
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", GATE_TESTS],
            cwd=copy, capture_output=True, text=True, timeout=120,
        )


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_gate_mutant_is_killed(label, rel, old, new):
    result = _run_gate_tests_with(rel, old, new)
    assert result.returncode != 0, (
        f"mutant survived: {label}\nevery test in {GATE_TESTS} passed with the gate broken\n"
        + result.stdout[-2000:]
    )
    assert "failed" in result.stdout, result.stdout[-2000:]


def test_gate_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = _run_gate_tests_with("ghost_writer/correct.py", "DEFAULT_MAX_ATTEMPTS = 3\n", "DEFAULT_MAX_ATTEMPTS = 3\n")
    assert result.returncode == 0, result.stdout[-2000:]
