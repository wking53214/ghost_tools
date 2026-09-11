"""The proof that Tests/test_trust.py is not vacuous. The working tree is
never modified."""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TRUST_TESTS = "Tests/test_trust.py"
_T = "ghost_buster/trust.py"
_C = "ghost_buster/cli.py"

MUTANTS = [
    ("the test scan runs for an untrusted repository", _C,
     "    if args.tests and not args.trusted.trusted:\n",
     "    if False:\n"),
    ("the mutation scan runs for an untrusted repository", _C,
     "    if args.mutate and not args.trusted.trusted:\n",
     "    if False:\n"),
    ("--trust does not record anything", _C,
     "    args.trusted = trust_grant(args.path) if args.trust else trust_check(args.path)\n",
     "    args.trusted = trust_check(args.path)\n"),
    ("everything is trusted", _T,
     "    return Trust(False, ident, store, f\"{ident} is not in {store}\")\n",
     "    return Trust(True, ident, store, f\"{ident} is not in {store}\")\n"),
    ("the remote is not normalised, so a clone over ssh is a stranger", _T,
     "    return u.rstrip(\"/\").lower()\n",
     "    return url.strip()\n"),
    ("an empty or corrupt store trusts everything", _T,
     "    entry = _load(store).get(ident)\n",
     "    entry = _load(store).get(ident) if _load(store) else {\"granted\": \"\"}\n"),
    ("the env override is ignored", _T,
     "    if os.environ.get(ENV) == TRUST_ALL:\n",
     "    if False:\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_trust_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TRUST_TESTS, run_tests_with_mutation(TRUST_TESTS, rel, old, new))


def test_trust_tests_pass_unmutated():
    result = run_tests_with_mutation(TRUST_TESTS, _T, 'ENV = "GHOST_TOOLS_TRUST"', 'ENV = "GHOST_TOOLS_TRUST"')
    assert result.returncode == 0, result.stdout[-2000:]
