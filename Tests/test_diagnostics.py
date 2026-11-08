"""Diagnostics go through the stdlib `logging` module and the contracts hold.

What must not change: stdout is the report or the one JSON document, stderr
carries the same bare lines it always did at the default level, exit codes
are the same. What is new: `--verbose` and `GHOST_TOOLS_LOG` turn on debug
records, an embedding program can route the `ghost_tools` logger, and no
package file writes a diagnostic with a bare `print(..., file=sys.stderr)`.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import logging
import pathlib

import pytest

from ghost_buster import cli as buster_cli
from ghost_buster import diagnostics

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGES = ("ghost_buster", "ghost_writer", "blackhole_extrapolator", "stack_census")

BASE = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
        "--no-correlate", "--no-structure", "--single-repo"]


@pytest.fixture(autouse=True)
def _level_restored(monkeypatch):
    monkeypatch.delenv(diagnostics.ENV_LEVEL, raising=False)
    root = logging.getLogger(diagnostics.ROOT_LOGGER)
    before = root.level
    yield
    root.setLevel(before)


def _tree(tmp_path):
    root = tmp_path / "tgt"
    root.mkdir()
    (root / "m.py").write_text("def orphan_one():\n    return 1\n")
    return root


def _stable(document):
    """The document without the one field that is the time of the run."""
    for finding in document.get("findings", []):
        finding.pop("first_seen", None)
    return document


def _run(root, extra, capsys):
    rc = buster_cli.main([str(root), *BASE, *extra])
    out, err = capsys.readouterr()
    return rc, out, err


def test_no_package_file_prints_a_diagnostic_to_stderr_directly():
    """The only `file=sys.stderr` left is the logging handler itself and the
    interactive prompt in pipeline.py (a prompt is not a diagnostic)."""
    offenders = []
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"):
                    continue
                for kw in node.keywords:
                    if kw.arg == "file" and ast.unparse(kw.value) == "sys.stderr":
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    allowed = {"ghost_buster/pipeline.py",       # the single-repo prompt and its newline
               "ghost_buster/diagnostics.py"}    # the handler: the one place that writes
    unexpected = [o for o in offenders if o.split(":")[0] not in allowed]
    assert not unexpected, f"print(..., file=sys.stderr) in a package file: {unexpected}"
    assert len(offenders) <= 4, f"more direct stderr writes than the prompt and handler need: {offenders}"


def test_default_stderr_is_the_bare_receipt_lines_and_stdout_is_the_json(tmp_path, capsys):
    rc, out, err = _run(_tree(tmp_path), ["--json"], capsys)
    assert rc in (0, 1)
    document = json.loads(out)          # stdout is exactly one JSON document
    assert document["status"] in ("ok", "incomplete")
    lines = err.splitlines()
    assert any(line.startswith("ghost_buster: scanning 1 file(s) under ") for line in lines), err
    assert not any("debug" in line for line in lines), err
    assert not any(line.startswith(("INFO", "WARNING", "DEBUG")) for line in lines), err


def test_verbose_adds_debug_lines_to_stderr_and_changes_nothing_else(tmp_path, capsys):
    root = _tree(tmp_path)
    rc_quiet, out_quiet, err_quiet = _run(root, ["--json"], capsys)
    rc_loud, out_loud, err_loud = _run(root, ["--json", "--verbose"], capsys)
    assert rc_loud == rc_quiet
    assert _stable(json.loads(out_loud)) == _stable(json.loads(out_quiet))
    debug = [line for line in err_loud.splitlines() if ": debug: " in line]
    assert debug, err_loud
    assert all(line.startswith("ghost_tools.") for line in debug)
    assert not any(": debug: " in line for line in err_quiet.splitlines())
    quiet_lines = set(err_quiet.splitlines())
    assert quiet_lines <= set(err_loud.splitlines()), "--verbose must only add lines"


def test_the_environment_sets_the_level_and_the_flag_wins(tmp_path, capsys, monkeypatch):
    root = _tree(tmp_path)
    monkeypatch.setenv(diagnostics.ENV_LEVEL, "DEBUG")
    _, _, err = _run(root, [], capsys)
    assert ": debug: " in err
    monkeypatch.setenv(diagnostics.ENV_LEVEL, "ERROR")
    _, _, err = _run(root, [], capsys)
    assert "scanning" not in err, "ERROR hides the INFO receipts, by the caller's own choice"
    _, _, err = _run(root, ["--verbose"], capsys)
    assert ": debug: " in err and "scanning" in err


def test_an_unusable_level_is_reported_not_swallowed(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(diagnostics.ENV_LEVEL, "LOUD")
    rc, out, err = _run(_tree(tmp_path), ["--json"], capsys)
    assert rc in (0, 1)
    assert f"{diagnostics.ENV_LEVEL}='LOUD' is not one of" in err
    assert "scanning" in err, "an unusable value falls back to INFO"
    json.loads(out)


@pytest.mark.parametrize("raw, level", [
    (None, logging.INFO), ("", logging.INFO), ("debug", logging.DEBUG), (" Warning ", logging.WARNING),
    ("ERROR", logging.ERROR)])
def test_level_from_environment(raw, level):
    env = {} if raw is None else {diagnostics.ENV_LEVEL: raw}
    assert diagnostics.level_from_environment(env) == (level, None)


def test_the_usage_error_still_says_why_on_stderr_with_exit_2(tmp_path, capsys):
    rc = buster_cli.main([str(tmp_path / "nope"), "--json"])
    out, err = capsys.readouterr()
    assert rc == 2
    assert f"error: {tmp_path / 'nope'} is not a directory" in err
    assert json.loads(out)["error"]["kind"] == "usage"


def test_records_reach_whatever_stderr_is_at_the_moment_of_writing():
    log = diagnostics.get_logger("tests.diag")
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        log.info("hello %s", "there")
        log.debug("not shown at INFO")
    assert buffer.getvalue() == "hello there\n"


def test_an_embedding_program_can_route_the_logger_and_nothing_prints_twice(capsys):
    log = diagnostics.get_logger("tests.embed")
    seen = []

    class Collect(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    handler = Collect()
    root = logging.getLogger(diagnostics.ROOT_LOGGER)
    root.addHandler(handler)
    logging.getLogger().addHandler(logging.StreamHandler(io.StringIO()))   # a configured application root
    try:
        log.warning("routed")
    finally:
        root.removeHandler(handler)
    assert seen == ["routed"]
    assert capsys.readouterr().err == "routed\n"       # ours is the only writer, once


def test_importing_twice_installs_one_handler():
    import importlib
    importlib.reload(diagnostics)
    importlib.reload(diagnostics)
    root = logging.getLogger(diagnostics.ROOT_LOGGER)
    ours = [h for h in root.handlers if getattr(h, "is_ghost_tools_handler", False)]
    assert len(ours) == 1


@pytest.mark.parametrize("module, argv", [
    ("ghost_writer.cli", ["{missing}"]),
    ("ghost_writer.triage", ["{missing}"]),
    ("stack_census.cli", ["{missing}"]),
    ("blackhole_extrapolator.cli", ["{missing}"]),
])
def test_every_command_line_reports_its_usage_error_through_the_logger(module, argv, tmp_path, capsys):
    import importlib
    main = importlib.import_module(module).main
    missing = str(tmp_path / "missing")
    rc = main([a.format(missing=missing) for a in argv])
    out, err = capsys.readouterr()
    assert rc == 2 and missing in err and out == ""


@pytest.mark.parametrize("module", ["ghost_writer.cli", "ghost_writer.triage", "stack_census.cli",
                                    "blackhole_extrapolator.cli"])
def test_every_command_line_accepts_verbose(module, tmp_path, capsys):
    import importlib
    main = importlib.import_module(module).main
    rc = main([str(tmp_path / "missing"), "--verbose"])
    assert rc == 2
