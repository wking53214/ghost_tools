"""A report that cannot be delivered is not a traceback, and not a clean run.

The round-5 audit: `ghost-buster DIR --no-tests --no-branches --single-repo | head -c0` printed a
BrokenPipeError traceback from `_print_report`, then "internal error, the scan did not complete", and exited 3,
while `| head -3` exited 0. The other five commands that print a report (ghost-writer, ghost-triage,
blackhole-extrapolator, stack-census, ghost-rank) ended in a raw traceback and Python's default exit 1, which is
also the number for "findings". A closed standard output vanished without a word and exited 0.

The rule, held here for all six commands against the real thing (a subprocess whose standard output is a pipe nobody
reads, a closed file descriptor 1, `/dev/full`):

  * the reader left (broken pipe): no traceback, one plain line on stderr, the exit code the run earned;
  * standard output closed or full: no traceback, one plain line on stderr, and a run that would have exited 0
    exits EXIT_OUTPUT (4); a run that already exits non-zero keeps its code;
  * a crashed scan never looks clean.

Safety: nothing here writes to a device by path. `/dev/full` is only opened for writing and handed to a child as its
standard output, the way a shell's `>` would; it is never an `--out`, and nothing is replaced.
"""
from __future__ import annotations

import errno
import io
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

from ghost_buster import cli as buster_cli
from ghost_buster import delivery
from ghost_buster.delivery import EXIT_OUTPUT, delivers

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

QUIET = ["--no-tests", "--no-branches", "--single-repo", "--no-secrets", "--no-ledger"]

#: (console script, module that holds its main) for the six commands that print a report.
COMMANDS = {
    "ghost-buster": "ghost_buster.cli",
    "ghost-writer": "ghost_writer.cli",
    "ghost-triage": "ghost_writer.triage",
    "blackhole-extrapolator": "blackhole_extrapolator.cli",
    "stack-census": "stack_census.cli",
    "ghost-rank": "ghost_buster.consequence",
}


def _code(module: str) -> str:
    return f"import sys; from {module} import main; sys.exit(main())"


def _env() -> dict:
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    env.pop("GHOST_TOOLS_LOG", None)
    return env


def _launch(module: str, args: List[str], how: str) -> subprocess.CompletedProcess:
    """Run one command the way its console script does, with standard output failing in way `how`."""
    cmd = [sys.executable, "-c", _code(module), *args]
    kw = dict(env=_env(), stderr=subprocess.PIPE, text=True, cwd=ROOT, timeout=300)
    if how == "healthy":
        return subprocess.run(cmd, stdout=subprocess.PIPE, **kw)
    if how == "reader left":
        # A pipe with no reader at all: the first write is EPIPE, as when `| head -c0` has exited.
        read_end, write_end = os.pipe()
        os.close(read_end)
        try:
            return subprocess.run(cmd, stdout=write_end, **kw)
        finally:
            os.close(write_end)
    if how == "closed":
        # File descriptor 1 is closed before the interpreter starts, so it has no sys.stdout. Done by exec-ing the
        # command after the close rather than with preexec_fn, which is unsafe in a process with threads.
        launcher = ("import os, sys; os.close(1); "
                    f"os.execv(sys.executable, [sys.executable, '-c', {_code(module)!r}] + sys.argv[1:])")
        return subprocess.run([sys.executable, "-c", launcher, *args], stdout=subprocess.PIPE, **kw)
    if how == "full":
        assert os.path.exists("/dev/full"), "this test needs /dev/full (Linux)"
        with open("/dev/full", "wb") as device:   # opened for writing, as a shell's `>` does; never replaced
            return subprocess.run(cmd, stdout=device, **kw)
    raise AssertionError(how)


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    base = tmp_path_factory.mktemp("delivery")
    tree = base / "tree"
    tree.mkdir()
    (tree / "m.py").write_text("X = 1\n", encoding="utf-8")
    broken = base / "broken"
    broken.mkdir()
    (broken / "m.py").write_text("def (:\n", encoding="utf-8")        # unparsable: a MAJOR finding, exit 1
    stack = base / "stack"
    for name in ("repoA", "repoB"):
        (stack / name).mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(stack / name)], check=True)
    found = _launch("ghost_buster.cli", [str(broken), *QUIET, "--json"], "healthy")
    assert found.returncode == 1, found.stderr
    report = base / "findings.json"
    report.write_text(found.stdout, encoding="utf-8")
    return {"tree": tree, "broken": broken, "stack": stack, "report": report}


def _args(name: str, inp: dict) -> List[str]:
    return {
        "ghost-buster": [str(inp["tree"]), *QUIET],
        "ghost-writer": [str(inp["report"]), "--mode", "triage"],
        "ghost-triage": [str(inp["report"]), "--list"],
        "blackhole-extrapolator": [str(inp["tree"])],
        "stack-census": [str(inp["stack"])],
        "ghost-rank": ["--stack", str(inp["stack"]), f"repoA={inp['report']}"],
    }[name]


def _ours(stderr: str) -> List[str]:
    return [line for line in stderr.splitlines() if "standard output" in line]


def _assert_plain(done: subprocess.CompletedProcess) -> None:
    assert "Traceback" not in done.stderr, done.stderr
    assert "Exception ignored" not in done.stderr, done.stderr
    assert "BrokenPipeError" not in done.stderr.replace("(BrokenPipeError: [Errno 32] Broken pipe)", ""), done.stderr
    assert len(_ours(done.stderr)) == 1, done.stderr


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_a_healthy_run_is_unchanged(name, inputs):
    done = _launch(COMMANDS[name], _args(name, inputs), "healthy")
    assert done.returncode == 0 and done.stdout.strip() != "", done.stderr
    assert _ours(done.stderr) == []


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_a_reader_that_left_is_one_plain_line_and_the_earned_exit_code(name, inputs):
    done = _launch(COMMANDS[name], _args(name, inputs), "reader left")
    _assert_plain(done)
    assert done.returncode == 0, done.stderr
    assert "went away" in _ours(done.stderr)[0]


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_a_closed_standard_output_is_one_plain_line_and_a_nonzero_exit(name, inputs):
    done = _launch(COMMANDS[name], _args(name, inputs), "closed")
    _assert_plain(done)
    assert done.returncode == EXIT_OUTPUT, done.stderr
    assert "closed" in _ours(done.stderr)[0]


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_a_full_device_is_one_plain_line_and_a_nonzero_exit(name, inputs):
    done = _launch(COMMANDS[name], _args(name, inputs), "full")
    _assert_plain(done)
    assert done.returncode == EXIT_OUTPUT, done.stderr
    assert "No space left on device" in _ours(done.stderr)[0]


def test_the_audit_probe_exits_with_the_earned_code_not_3(inputs):
    """`ghost-buster DIR --no-tests --no-branches --single-repo | head -c0`, as reported, through a real shell pipe."""
    piped = subprocess.run(
        f"{sys.executable} -c {_code('ghost_buster.cli')!r} {inputs['tree']} --no-tests --no-branches --single-repo "
        "| head -c0; exit ${PIPESTATUS[0]}",
        shell=True, executable="/bin/bash", env=_env(), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=300)
    assert piped.returncode == 0, piped.stderr
    assert "Traceback" not in piped.stderr and "internal error" not in piped.stderr


# --- the exit code stays honest ---------------------------------------------------------------------------------

@pytest.mark.parametrize("how", ["reader left", "closed", "full"])
def test_findings_keep_exit_1_whatever_happens_to_the_report(how, inputs):
    done = _launch("ghost_buster.cli", [str(inputs["broken"]), *QUIET], how)
    _assert_plain(done)
    assert done.returncode == 1, done.stderr


@pytest.mark.parametrize("how", ["reader left", "closed", "full"])
def test_a_usage_error_keeps_exit_2_whatever_happens_to_the_report(how, inputs, tmp_path):
    missing = tmp_path / "no-such-folder-for-this-test"
    assert not missing.exists()
    done = _launch("ghost_buster.cli", [str(missing), *QUIET, "--json"], how)
    assert done.returncode == 2, done.stderr
    assert "Traceback" not in done.stderr


def test_a_crashed_scan_with_a_dead_reader_still_exits_3(tmp_path, monkeypatch):
    class Gone(io.StringIO):
        def write(self, text):
            raise BrokenPipeError(errno.EPIPE, "Broken pipe")

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    tree = tmp_path / "t"
    tree.mkdir()
    (tree / "m.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.setattr(buster_cli, "gather", boom)
    monkeypatch.setattr(sys, "stdout", Gone())
    assert buster_cli.main([str(tree), *QUIET]) == buster_cli.EXIT_CRASH


# --- the guard itself, in process -------------------------------------------------------------------------------

class _Breaks(io.StringIO):
    """A standard output that fails with `error` on write, or only on flush (as a buffered pipe or file does)."""

    def __init__(self, error: BaseException, on: str = "write") -> None:
        super().__init__()
        self.error, self.on = error, on

    def write(self, text):
        if self.on == "write":
            raise self.error
        return super().write(text)

    def flush(self):
        if self.on == "flush":
            raise self.error


def _hello() -> int:
    print("report")
    return 0


def test_a_failure_that_only_shows_on_flush_is_still_a_delivery_failure(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _Breaks(OSError(errno.ENOSPC, "No space left on device"), on="flush"))
    assert delivers("prog")(_hello)() == EXIT_OUTPUT


def test_a_closed_stream_is_a_delivery_failure(monkeypatch):
    stream = io.StringIO()
    stream.close()
    monkeypatch.setattr(sys, "stdout", stream)
    assert delivers("prog")(_hello)() == EXIT_OUTPUT


def test_no_stdout_at_all_is_a_delivery_failure(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    assert delivers("prog")(_hello)() == EXIT_OUTPUT
    assert sys.stdout is None


def test_a_dead_reader_of_any_kind_keeps_the_earned_code(monkeypatch):
    for error in (BrokenPipeError(errno.EPIPE, "Broken pipe"), OSError(errno.EPIPE, "Broken pipe"),
                  ConnectionResetError(errno.ECONNRESET, "reset")):
        monkeypatch.setattr(sys, "stdout", _Breaks(error))
        assert delivers("prog")(_hello)() == 0


def test_a_run_that_already_failed_keeps_its_nonzero_code(monkeypatch):
    def findings() -> int:
        print("report")
        return 1

    monkeypatch.setattr(sys, "stdout", _Breaks(OSError(errno.ENOSPC, "No space left on device")))
    assert delivers("prog")(findings)() == 1


def test_stdout_is_put_back_and_later_writes_are_dropped_after_a_failure(monkeypatch):
    broken = _Breaks(OSError(errno.EIO, "I/O error"))
    monkeypatch.setattr(sys, "stdout", broken)
    seen = []

    def main() -> int:
        print("a")
        seen.append(isinstance(sys.stdout, delivery._GuardedStdout))
        print("b")
        return 0

    assert delivers("prog")(main)() == EXIT_OUTPUT
    assert seen == [True] and sys.stdout is broken


def test_an_exception_that_is_not_a_delivery_failure_still_propagates(monkeypatch):
    def crash() -> int:
        print("partial")
        raise RuntimeError("boom")

    monkeypatch.setattr(sys, "stdout", _Breaks(BrokenPipeError(errno.EPIPE, "Broken pipe")))
    with pytest.raises(RuntimeError, match="boom"):
        delivers("prog")(crash)()


def test_an_unencodable_report_is_not_mistaken_for_a_delivery_failure(monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="ascii"))

    def accented() -> int:
        print("café")
        return 0

    with pytest.raises(UnicodeEncodeError):
        delivers("prog")(accented)()


def test_a_nested_command_is_not_wrapped_twice(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _Breaks(OSError(errno.ENOSPC, "No space left on device")))
    inner = delivers("inner")(_hello)

    def outer() -> int:
        return inner()

    assert delivers("outer")(outer)() == EXIT_OUTPUT


@pytest.mark.parametrize("error, code", [(OSError(errno.ENOSPC, "No space left on device"), EXIT_OUTPUT),
                                         (BrokenPipeError(errno.EPIPE, "Broken pipe"), 0)])
def test_version_and_help_follow_the_same_rule(error, code, monkeypatch):
    monkeypatch.setattr(sys, "stdout", _Breaks(error))
    with pytest.raises(SystemExit) as stop:
        buster_cli.main(["--version"])
    assert stop.value.code == code


# --- the documentation says what the code does ------------------------------------------------------------------

def test_the_exit_code_is_four_and_differs_from_every_other():
    assert EXIT_OUTPUT == 4
    assert EXIT_OUTPUT not in {buster_cli.EXIT_CLEAN, buster_cli.EXIT_FINDINGS, buster_cli.EXIT_USAGE,
                               buster_cli.EXIT_CRASH, buster_cli.EXIT_INTERRUPTED}


def test_the_readme_exit_table_documents_the_delivery_code_and_the_broken_pipe_rule():
    text = README.read_text(encoding="utf-8")
    table = text.split("### Exit codes", 1)[1].split("###", 1)[0]
    assert re.search(r"^\| 4 \|", table, re.MULTILINE), table
    assert "broken pipe" in table.lower() and "earned" in table.lower()
    for command in COMMANDS:
        assert command in table, command
