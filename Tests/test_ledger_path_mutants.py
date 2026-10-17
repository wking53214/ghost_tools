"""The proof that Tests/test_ledger_path.py and Tests/test_diagnostics.py are not vacuous.
The working tree is never modified."""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

LEDGER_TESTS = "Tests/test_ledger_path.py"
DIAG_TESTS = "Tests/test_diagnostics.py"
_C = "ghost_buster/cli.py"
_L = "ghost_buster/ledger.py"
_P = "ghost_buster/pipeline.py"
_D = "ghost_buster/diagnostics.py"

MUTANTS = [
    ("a missing parent is created without the opt-in", LEDGER_TESTS, _C,
     "    if args.create_ledger_dir:\n        log.debug(\"ledger: %s (its folder %s does not exist",
     "    if True:\n        log.debug(\"ledger: %s (its folder %s does not exist"),
    ("--no-ledger no longer exempts the path from the check", LEDGER_TESTS, _C,
     "    if path is None or args.ledger is False:\n        return None\n",
     "    if path is None:\n        return None\n"),
    ("a ledger path that is a folder is accepted", LEDGER_TESTS, _C,
     "    if path.is_dir():\n        return _fail(",
     "    if False:\n        return _fail("),
    ("a parent that is a file is treated as a missing folder", LEDGER_TESTS, _C,
     "    if parent.exists():\n        return _fail(",
     "    if False:\n        return _fail("),
    ("an existing folder is refused", LEDGER_TESTS, _C,
     "    parent = path.parent\n    if parent.is_dir():\n",
     "    parent = path.parent\n    if False:\n"),
    ("the check runs nowhere", LEDGER_TESTS, _C,
     "    result = _validate_ledger_path(args)\n    if result is not None:\n        return result\n",
     "    result = None\n"),
    ("save always creates folders", LEDGER_TESTS, _L,
     "        if create_dirs:\n            self.path.parent.mkdir(parents=True, exist_ok=True)",
     "        if True:\n            self.path.parent.mkdir(parents=True, exist_ok=True)"),
    ("the scan always asks save to create folders", LEDGER_TESTS, _P,
     'ledger.save(create_dirs=bool(getattr(args, "create_ledger_dir", False)))',
     "ledger.save(create_dirs=True)"),
    ("--verbose no longer turns on debug records", DIAG_TESTS, _D,
     "    if verbose:\n        level, problem = logging.DEBUG, None",
     "    if False:\n        level, problem = logging.DEBUG, None"),
    ("the environment level is ignored", DIAG_TESTS, _D,
     "    level = _LEVELS.get(raw.strip().upper())",
     "    level = logging.INFO"),
    ("an unusable level is not reported", DIAG_TESTS, _D,
     "    if problem:\n        root.warning(\"%s\", problem)",
     "    if False:\n        root.warning(\"%s\", problem)"),
    ("debug records are not marked as debug", DIAG_TESTS, _D,
     "        if record.levelno < logging.INFO:\n            return f\"{record.name}: debug: {message}\"\n",
     "        if False:\n            return f\"{record.name}: debug: {message}\"\n"),
    ("the handler is bound to the stderr of import time", DIAG_TESTS, _D,
     "            print(self.format(record), file=sys.stderr)",
     "            print(self.format(record), file=sys.__stderr__)"),
]


@pytest.mark.parametrize("label,tests,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_ledger_path_and_diagnostics_mutant_is_killed(label, tests, rel, old, new):
    assert_killed(label, tests, run_tests_with_mutation(tests, rel, old, new))


def test_ledger_path_tests_pass_unmutated():
    for tests, rel in ((LEDGER_TESTS, _L), (DIAG_TESTS, _D)):
        result = run_tests_with_mutation(
            tests, rel, "from __future__ import annotations", "from __future__ import annotations")
        assert result.returncode == 0, result.stdout[-2000:]
