"""The proof that Tests/test_finding_identity.py is not vacuous.

Each mutant restores one way for a finding's identity to move while the
defect does not, or to collide while the defects differ. Both directions
matter and they fail in opposite ways, so both are here.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

DOCS = "Tests/test_finding_identity.py"

_SCHEMA = "ghost_buster/schema.py"
_MECH = "ghost_buster/mechanical.py"
_PROJ = "ghost_buster/project.py"
_CORR = "ghost_buster/correlate.py"

MUTANTS = [
    # (label, file, exact text to replace, replacement)
    ("the key is ignored and the summary decides again", _SCHEMA,
     "        self.id = _stable_id(self.detector, portable,\n"
     "                             self.summary if self.identity_key is None\n"
     "                             else self.identity_key)",
     "        self.id = _stable_id(self.detector, portable, self.summary)"),
    ("an empty key falls back to the summary, silently undoing it", _SCHEMA,
     "                             self.summary if self.identity_key is None",
     "                             self.summary if not self.identity_key"),
    ("the key replaces the whole id, so every file collides", _SCHEMA,
     "        self.id = _stable_id(self.detector, portable,\n"
     "                             self.summary if self.identity_key is None\n"
     "                             else self.identity_key)",
     "        self.id = _stable_id(self.summary if self.identity_key is None\n"
     "                             else self.identity_key)"),
    ("the drift finding puts the measured bound back in its identity", _MECH,
     '                identity_key=f"claims {documented} test(s), stale",\n',
     ""),
    ("the drift finding identifies only by document, losing the claim", _MECH,
     '                identity_key=f"claims {documented} test(s), stale",',
     '                identity_key="stale",'),
    ("the project finding counts affected files in its identity", _PROJ,
     "        identity_key=kind,\n",
     ""),
    ("the correlation puts the measurement back in its identity", _CORR,
     '            identity_key=f"claims {documented} test(s), contradicted by the run",\n',
     ""),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    assert_killed(label, DOCS, run_tests_with_mutation(DOCS, rel, old, new))


def test_the_suite_passes_unmutated():
    anchor = "    identity_key: Optional[str] = None"
    result = run_tests_with_mutation(DOCS, _SCHEMA, anchor, anchor)
    assert result.returncode == 0, result.stdout[-1500:]
