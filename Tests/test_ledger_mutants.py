"""The proof that Tests/test_ledger.py is not vacuous.

A memory feature fails quietly in both directions: it can forget (and
nothing says so) or it can remember wrong (and confidently report a
regression that never happened). Worse, it can start subtracting -- the
one thing this module promises never to do. Every mutant below is one of
those three, broken one at a time in a scratch copy. All must be killed.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

LEDGER_TESTS = "Tests/test_ledger.py"
_L = "ghost_buster/ledger.py"
_C = "ghost_buster/cli.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- forgetting ---
    ("absence is never recorded, so nothing can ever be a regression", _L,
     "            hist.consecutive = 0\n            hist.absent_last_run = True\n",
     "            hist.consecutive = 0\n"),
    ("a return is not counted (a regression reads as business as usual)", _L,
     "                hist.returns += 1\n", "                pass\n"),
    ("the run counter stops advancing", _L,
     '        self.totals["runs"] = self.run_count + 1\n', "        pass\n"),
    ("a corrupt ledger silently starts over, erasing the record", _L,
     '            raise LedgerError(f"{self.path}: {type(e).__name__}: {e}") from e\n',
     "            return\n"),
    ("a ledger from a newer schema is read anyway", _L,
     "        if version != SCHEMA_VERSION:\n", "        if False:\n"),

    # --- remembering wrong ---
    ("the blind-spot streak counts non-consecutive absences", _L,
     "                if state is None or state == RAN:\n                    break\n",
     "                if state is None or state == RAN:\n                    continue\n"),
    ("every blind spot is MAJOR again (--mutate becomes permanent noise)", _L,
     "                severity=_BLIND_SPOT_SEVERITY.get(last, Severity.MINOR),\n",
     "                severity=Severity.MAJOR,\n"),
    ("a regression no longer outranks its own finding", _L,
     "                    'regressed_finding', _escalate(f.severity), f,\n".replace("'", '"'),
     '                    "regressed_finding", f.severity, f,\n'),
    ("escalation runs off the end of the ladder instead of capping", _L,
     "    return _SEVERITY_LADDER[min(i + 1, len(_SEVERITY_LADDER) - 1)]\n",
     "    return _SEVERITY_LADDER[i + 1]\n"),
    ("flapping is reported as an ordinary regression", _L,
     "            if hist.returns >= FLAPPING_AFTER:\n", "            if False:\n"),
    ("a dispositioned finding is still nagged about as persistent", _L,
     "            if (hist.consecutive >= PERSISTENT_AFTER and not hist.dispositions):\n",
     "            if hist.consecutive >= PERSISTENT_AFTER:\n"),
    ("the run cap drops runs from the count as well as the list", _L,
     "        if len(self.runs) > MAX_RUNS_KEPT:\n", "        if False:\n"),
    ("a failed write leaves its temp file behind", _L,
     "            os.replace(tmp, self.path)\n", "            pass\n"),

    # --- subtracting: the thing it must never do ---
    ("the ledger records its own output and compounds history on history", _L,
     "        findings = [f for f in findings if f.detector != DETECTOR]\n", ""),
    ("history findings replace the run's findings instead of adding to them", _C,
     "        findings.extend(history)\n", "        findings = list(history)\n"),
    ("the ledger runs after the baseline diff, so --accept erases memory", _C,
     "    if args.ledger:\n        ledger_path = args.ledger_path or (args.path / \".ghost_ledger.json\")\n",
     "    if args.ledger and not args.accept:\n        ledger_path = args.ledger_path or (args.path / \".ghost_ledger.json\")\n"),

    # --- the CLI contract ---
    ("the ledger silently returns to opt-in", _C,
     '        "--ledger", action=argparse.BooleanOptionalAction, default=True,\n',
     '        "--ledger", action=argparse.BooleanOptionalAction, default=False,\n'),
    ("declining the ledger leaves no receipt", _C,
     '        _skipped("ledger", "--no-ledger")\n', "        pass\n"),
    ("a corrupt ledger no longer fails the run", _C,
     '            print(f"error: ledger {e}", file=sys.stderr)\n            return 2\n',
     "            ledger = Ledger(ledger_path.with_suffix('.new'))\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_ledger_mutant_is_killed(label, rel, old, new):
    assert_killed(label, LEDGER_TESTS, run_tests_with_mutation(LEDGER_TESTS, rel, old, new))


def test_ledger_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        LEDGER_TESTS, _L, 'DETECTOR = "ledger"\n', 'DETECTOR = "ledger"\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
