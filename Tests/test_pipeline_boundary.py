"""Gathering evidence and presenting it are two jobs, and the seam holds.

WHY THIS FILE EXISTS (v1.6.0)

cli.py had grown to 795 lines around one 450-line `main()` that did
everything: parsed the command line, walked the tree, ran twenty
detectors, ran the repository checks, correlated, wrote the ledger,
diffed the baseline, chose the exit code and printed the report. The
tool's own long_function detector rated it MAJOR on its own source, and
the finding sat accepted in the self-scan baseline because nobody could
say what a smaller main() would look like.

The split answers that: ghost_buster/pipeline.py gathers, cli.py
presents. gather(args) returns an Evidence record and everything after
it in main() is interface.

Lifting 450 lines out of one module and into another is exactly the kind
of change that works on the happy path and breaks quietly elsewhere, so
each test here pins a specific way the lift could have gone wrong. Two
of them were written because the lift DID go wrong that way, caught by
running the old and new binaries against the same tree and diffing:

  * Receipts went to stdout. main() printed receipts with
    `print(..., file=sys.stderr)`; the mechanical conversion to `say(...)`
    dropped the keyword on three lines, which is invisible in a terminal
    where both channels land on the screen, and corrupts the output of
    `--json` piped to a file.

  * `profile_seconds` was unbound. It was only ever assigned inside
    `if args.profile:` -- safe while its only reader sat behind the same
    condition in the same function, and an UnboundLocalError on every
    run without --profile once the Evidence record read it at the end.
"""
from __future__ import annotations

import ast
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from ghost_buster import cli, pipeline
from ghost_buster.cli import _build_parser
from ghost_buster.pipeline import Evidence, gather
from ghost_buster.trust import check as trust_check

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def project(tmp_path):
    (tmp_path / "m.py").write_text(
        "def handler(payload):\n"
        "    result = payload  # TODO: actually handle it\n"
        "    return result\n"
    )
    return tmp_path


def _args(path, *extra):
    args = _build_parser().parse_args([
        str(path), "--single-repo", "--no-branches", "--no-tests",
        "--no-secrets", "--no-ledger", *extra,
    ])
    args.trusted = trust_check(args.path)
    return args


def test_gather_writes_nothing_to_stdout(project):
    """Every receipt goes through `say`. stdout belongs to the report --
    and to --json, which is machine-read and must not carry prose."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        gather(_args(project), say=lambda message: None)
    assert buffer.getvalue() == ""


def test_the_caller_owns_the_receipt_channel(project):
    """`say` is injectable, and it is the ONLY way out. Anything the
    scan wants to tell the operator arrives in this list."""
    said = []
    gather(_args(project), say=said.append)
    assert any("scanning" in line for line in said)
    for check, flag in [("branch scan", "--no-branches"),
                        ("test status scan", "--no-tests"),
                        ("secrets scan", "--no-secrets")]:
        assert any(f"{check} SKIPPED at your request ({flag})" in line
                   for line in said), f"{check} left no receipt"


def test_gather_returns_evidence_without_profile(project):
    """No --profile still produces a complete record. profile_seconds is
    read unconditionally by the caller, so it must always be bound."""
    evidence = gather(_args(project), say=lambda message: None)
    assert isinstance(evidence, Evidence)
    assert evidence.profile is None
    assert evidence.profile_seconds == 0.0
    assert evidence.files and evidence.findings


def test_profile_seconds_is_measured_when_asked(project):
    evidence = gather(_args(project, "--profile"), say=lambda message: None)
    assert evidence.profile is not None
    assert evidence.profile_seconds > 0.0


def _defined_names(module_path):
    tree = ast.parse(module_path.read_text())
    return {node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))}


def test_neither_module_redefines_the_other_s_functions():
    """A lift that copies instead of moving leaves two implementations
    to drift apart. Exactly one definition of each name, across both."""
    shared = _defined_names(ROOT / "ghost_buster" / "cli.py") & \
        _defined_names(ROOT / "ghost_buster" / "pipeline.py")
    assert shared == set(), f"defined in both modules: {sorted(shared)}"


def test_the_cli_gathers_through_the_pipeline():
    """cli.py must not have kept its own copy of the walk. The only way
    it reaches the tree is gather()."""
    source = (ROOT / "ghost_buster" / "cli.py").read_text()
    assert "from .pipeline import" in source
    assert "gather(args)" in source
    for helper in ["_collect_files", "_run_repository_checks", "_resolve_join_mode"]:
        assert f"def {helper}" not in source


def test_the_dependency_runs_one_way():
    """pipeline.py knows nothing about cli.py. If it ever imports back,
    the split has become a circle and buys nothing."""
    source = (ROOT / "ghost_buster" / "pipeline.py").read_text()
    assert "import cli" not in source and "from .cli" not in source
    assert "cli" not in sys.modules or pipeline.__name__ != cli.__name__


def test_the_split_functions_clear_the_threshold_that_named_them():
    """The point of the split, measured by the detector that named it.
    long_function rates a function MAJOR past 80 lines; it rated main()
    at 285, and it rated the first draft of gather() at 182 -- the god
    object had moved modules rather than being taken apart.

    Asked here in the tool's own terms rather than with a line count of
    our own, so the test cannot pass a function the shipped detector
    would still flag.

    _build_parser is the one function in the package still over the
    threshold, and it is baselined with its reason in .ghost_casefile.json:
    it is the flag inventory, one add_argument per flag, and the README's
    own defaults test reads against that single table."""
    from ghost_buster.mechanical import run_all

    flagged = {
        f.summary.split("'")[1]
        for f in run_all([ROOT / "ghost_buster" / "cli.py",
                          ROOT / "ghost_buster" / "pipeline.py"])
        if f.detector == "long_function"
    }
    assert "main" not in flagged
    assert "gather" not in flagged
    assert flagged == {"_build_parser"}, f"unexpectedly long: {sorted(flagged)}"


def test_main_hands_the_presentation_to_present():
    """Presentation lives in _present(); main() decides and delegates.

    The line count used to hold this seam by accident. main() was 76 lines,
    so pasting the report back into it crossed long_function's 80 and the
    threshold test above failed. The #73 split took main() to 55, the same
    paste lands near 65, and the mutant 'main takes the presentation back'
    survived. Asked directly instead: main() calls _present() and never
    calls the report printer itself."""
    tree = ast.parse((ROOT / "ghost_buster" / "cli.py").read_text())
    main = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "main")
    called = {node.func.id for node in ast.walk(main)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "_present" in called
    assert "_print_report" not in called


def test_the_gathering_is_four_named_stages():
    """gather() reads as the order the checks run in. Each stage is a
    function with a name, so the order is still one readable sequence."""
    source = (ROOT / "ghost_buster" / "pipeline.py").read_text()
    for stage in ["_run_opt_in_analyses", "_run_model_checks", "_correlate",
                  "_run_repository_checks", "_record_in_ledger"]:
        assert f"def {stage}(" in source, f"{stage} is gone"
        assert f"{stage}(args" in source.split("def gather(")[1], \
            f"gather() no longer calls {stage}"


def test_no_stage_reports_without_the_receipt_channel():
    """Every stage takes `say`. A stage that printed directly would put
    prose on stdout, where --json is read."""
    tree = ast.parse((ROOT / "ghost_buster" / "pipeline.py").read_text())
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name in ("to_stderr", "_resolve_join_mode", "_state",
                         "_collect_files", "_head_commit"):
            continue
        names = [a.arg for a in node.args.args]
        assert "say" in names, f"{node.name} has no receipt channel"
