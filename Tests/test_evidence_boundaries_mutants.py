"""The proof that this pass's four suites are not vacuous.

Four claims: what the target silenced is named, a statement about findings
is not a measurement of the tree, an identity does not depend on its
siblings, and an edited record is visible.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

_SEC = "ghost_buster/secrets.py"
_SCH = "ghost_buster/schema.py"
_LED = "ghost_buster/ledger.py"
_TRJ = "ghost_buster/trajectory.py"
_ATT = "ghost_buster/attest.py"

DISCLOSURE = "Tests/test_secrets_disclosure.py"
DERIVED = "Tests/test_primary_and_derived.py"
CHAIN = "Tests/test_attest.py"

MUTANTS = [
    # (label, file, exact text to replace, replacement, which suite)
    ("suppression is found but never disclosed", _SEC, DISCLOSURE,
     '        said = ("the target repository configures suppression: " + ", ".join(parts)\n'
     '                if parts else "the target repository configures no suppression")\n',
     '        said = "the target repository configures no suppression"\n'),
    ("only one suppression file is looked for", _SEC, DISCLOSURE,
     'SUPPRESSION_FILES = (".gitleaksignore", ".gitleaks.toml", "gitleaks.toml")',
     'SUPPRESSION_FILES = (".gitleaksignore",)'),
    ("comments in an ignore list are counted as fingerprints", _SEC, DISCLOSURE,
     '    return sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))',
     "    return len(lines)"),
    ("the receipt drops the disclosure", _SEC, DISCLOSURE,
     '    return f"{line}\\n  {disclosure}" if disclosure else line',
     "    return line"),
    ("a correlation is counted as a measurement of the tree", _SCH, DERIVED,
     "    return [f for f in findings if not is_derived(f)]",
     "    return list(findings)"),
    ("the ledger stops counting primary separately", _LED, DERIVED,
     '            counts={"found": len(findings), "primary": len(primary(findings))},',
     '            counts={"found": len(findings)},'),
    ("the series counts derived findings again", _TRJ, DERIVED,
     '        counted = run.counts.get("primary", run.counts["found"])',
     '        counted = run.counts["found"]'),
    ("the chain is never closed", _LED, CHAIN,
     '        run.link = attest.link(self.runs[-1].link if self.runs else "", run.to_dict())\n',
     ""),
    ("each link forgets the one before it", _ATT, CHAIN,
     '    return digest({"previous": previous, "run": body})',
     "    return digest({\"run\": body})"),
    ("a broken link is reported as an old run", _ATT, CHAIN,
     '            breaks.append(Break(i, str(run.get("run_id", "")),\n'
     '                                f"link {recorded} does not match {expected} recomputed from this run "\n'
     '                                "and the one before it"))\n',
     '            pass\n'),
    ("verify trusts the recorded link instead of recomputing", _ATT, CHAIN,
     "        expected = link(previous, run)",
     "        expected = recorded"),
    ("a digest reads bytes, so re-indenting a baseline looks like tampering", _ATT, CHAIN,
     '    text = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)',
     '    text = json.dumps(data, default=str)'),
]


@pytest.mark.parametrize("label,rel,tests,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, tests, old, new):
    assert_killed(label, tests, run_tests_with_mutation(tests, rel, old, new))


def test_the_suites_pass_unmutated():
    for tests, rel, anchor in ((DISCLOSURE, _SEC, "def target_suppression("),
                               (DERIVED, _SCH, "def primary("),
                               (CHAIN, _ATT, "def verify(")):
        result = run_tests_with_mutation(tests, rel, anchor, anchor)
        assert result.returncode == 0, f"{tests}: {result.stdout[-1500:]}"
