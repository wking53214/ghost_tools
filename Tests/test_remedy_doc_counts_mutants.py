"""The proof that the second remedy's suite is not vacuous.

A remedy writes to somebody's repository, so most of it is refusals and
verifications. Each mutant below removes exactly one of them and asks
whether anything notices.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

_OP = "ghost_buster/operate.py"

DOCS = "Tests/test_remedy_doc_counts.py"

MUTANTS = [
    # (label, file, exact text to replace, replacement)
    ("the remedy is never registered, so nothing can heal", _OP,
     '    "doc_counts": _remedy_doc_counts,\n',
     ""),
    ("the detector's refusal is ignored and every claim is written", _OP,
     '        if finding.attributes.get("writable") != "yes":',
     "        if False:"),
    ("a report counts as a current-state document", "ghost_buster/mechanical.py",
     '    if filename.lower() not in WRITABLE_DOCUMENTS:\n'
     '        return "not a current-state document"\n',
     ""),
    ("a scoped claim reads as a whole-suite claim", "ghost_buster/mechanical.py",
     '    if _SCOPED_CLAIM.search(before + after):\n'
     '        return "scoped to a file, command or subset"\n',
     ""),
    ("a table row reads as prose", "ghost_buster/mechanical.py",
     '    if _TABULAR_CLAIM.search(before):\n'
     '        return "a table row or labelled list entry"\n',
     ""),
    ("a dated sentence reads as a live claim", "ghost_buster/mechanical.py",
     '    if _DATED_SENTENCE.search(before):\n'
     '        return "a dated or historical sentence"\n',
     ""),
    ("a claim that says nothing about the suite is written anyway",
     "ghost_buster/mechanical.py",
     '    if not _WHOLE_SUITE.search(before + after):\n'
     '        return "does not assert about the whole suite"\n',
     ""),
    ("the predicate refuses everything, including real claims",
     "ghost_buster/mechanical.py",
     '    if filename.lower() not in WRITABLE_DOCUMENTS:',
     "    if True:"),
    ("a suite that is not green is rewritten anyway", _OP,
     '        if passed != collected:\n'
     '            declined.append("a suite that is not green")\n'
     '            continue\n',
     ""),
    ("a delta or a quotation is overwritten with today's total", _OP,
     '        if claim_shape(claim_context(text, offset + match.start())) is not None:\n'
     '            declined.append("a claim that is not about this suite")\n'
     '            continue\n',
     ""),
    ("an ambiguous line is written into anyway", _OP,
     "        if len(here) != 1:",
     "        if len(here) < 1:"),
    ("the static lower bound is written instead of the measured count", _OP,
     '    claims = [f for f in findings if f.detector == "doc_count_contradicted_by_run"]',
     '    claims = [f for f in findings if f.detector.startswith("doc_")]'),
    ("the number is never checked after writing", _OP,
     "        if not any(m.group(1) == collected\n"
     "                   for m in _TEST_COUNT_CLAIM_RE.finditer(line_now)):",
     "        if False:"),
    ("the rest of the file is allowed to move", _OP,
     "        if written[:start] != text[:start] or written[start + len(collected):] != text[end:]:",
     "        if False:"),
    ("a count attributed to another project reads as ours", "ghost_buster/mechanical.py",
     "    named = _NAMED_OWNER.search(before)\n"
     "    if named and named.group(1).lower() not in _COUNT_LEAD_INS:\n"
     '        return "attributed to a named subject"\n',
     ""),
    ("every lead-in counts as a named subject, silencing real claims",
     "ghost_buster/mechanical.py",
     "    if named and named.group(1).lower() not in _COUNT_LEAD_INS:",
     "    if named:"),
    ("the claim's span is computed from the top of the file", _OP,
     "        offset = sum(len(line) for line in lines[:line_no - 1])",
     "        offset = 0"),
    ("a file outside the patient is written to", _OP,
     "            resolved.relative_to(root.resolve())\n",
     ""),
    ("the remedy describes a cut it did not make", _OP,
     "    if changed:\n        note = f\"{changed} documented test count(s)",
     "    if True:\n        note = f\"{changed} documented test count(s)"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    assert_killed(label, DOCS, run_tests_with_mutation(DOCS, rel, old, new))


def test_the_suite_passes_unmutated():
    anchor = "def _remedy_doc_counts("
    result = run_tests_with_mutation(DOCS, _OP, anchor, anchor)
    assert result.returncode == 0, result.stdout[-1500:]
