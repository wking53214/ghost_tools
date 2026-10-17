"""Diagnostics for every command line in this distribution, through the stdlib `logging` module.

WHAT IS A DIAGNOSTIC AND WHAT IS NOT

Everything these tools print to STDERR is a diagnostic: the receipt line that
says a check was declined, a warning that a baseline hid findings, the one
plain line that says why a scan did not start. They go through a logger named
`ghost_tools` (children: `ghost_tools.<module>`), so a program that embeds
them can route, filter or silence them the usual way.

Everything printed to STDOUT is the product: the report, or under `--json`
the one JSON document. Nothing here touches it. Exit codes are unchanged.

THE DEFAULT IS THE OLD BEHAVIOUR

The records are written to stderr as the bare message, one per line, with
no timestamp, level or logger name, at INFO and above. That is byte for byte
what `print(message, file=sys.stderr)` wrote, and the tests that read stderr
still hold. Two things change it, on purpose:

  * `--verbose` (a flag of each command) turns on DEBUG records: what was
    chosen and why, such as which ledger path is in use. Debug lines are
    prefixed `<logger>: debug: ` so they cannot be mistaken for a receipt.
  * `GHOST_TOOLS_LOG=DEBUG|INFO|WARNING|ERROR` sets the level for a run
    without changing the command line, for a CI job or a wrapper. `--verbose`
    wins over it. An unrecognised value is reported and INFO is used; a
    diagnostic switch that fails silently would be the defect this toolkit
    exists to find.

WARNING or ERROR in `GHOST_TOOLS_LOG` hides the INFO receipts ("check X was
declined"). That is the caller's explicit choice, and the exit code and the
stdout contract do not depend on it.

The handler looks up `sys.stderr` each time it writes, not once when it is
built, so a test that swaps stderr (pytest's capsys, `contextlib.
redirect_stderr`) sees the records, as it saw the prints.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Mapping, Optional

ROOT_LOGGER = "ghost_tools"
ENV_LEVEL = "GHOST_TOOLS_LOG"

_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR}


class _StderrHandler(logging.Handler):
    """Write each record to whatever `sys.stderr` is right now."""

    #: How `_install` recognises its own handler, including one made by an
    #: earlier copy of this module (a reload makes a new class, so isinstance
    #: against the class would miss it and add a second writer).
    is_ghost_tools_handler = True

    def emit(self, record: logging.LogRecord) -> None:
        try:
            print(self.format(record), file=sys.stderr)
        except Exception:  # noqa: BLE001 -- logging must never be the reason a scan fails
            self.handleError(record)


class _Formatter(logging.Formatter):
    """The bare message, except that debug records say what they are."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.levelno < logging.INFO:
            return f"{record.name}: debug: {message}"
        return message


def _install() -> logging.Logger:
    """The root logger of the distribution, with exactly one handler of ours.

    Installed at import, not by `configure`, so a program that calls into
    the library without ever running a command line still gets its receipts
    on stderr, as it did before there was a logger.
    """
    root = logging.getLogger(ROOT_LOGGER)
    if not any(getattr(h, "is_ghost_tools_handler", False) for h in root.handlers):
        handler = _StderrHandler()
        handler.setFormatter(_Formatter())
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        # Our handler is the only writer; without this a configured root
        # logger in the embedding program would print every line twice.
        root.propagate = False
    return root


_install()


def get_logger(name: str) -> logging.Logger:
    """A child of the distribution's logger. Pass `__name__` for a module."""
    if name == ROOT_LOGGER or name.startswith(ROOT_LOGGER + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")


def level_from_environment(environ: Optional[Mapping[str, str]] = None) -> tuple[int, Optional[str]]:
    """(level, problem). `problem` is a sentence when the variable held something unusable."""
    env = os.environ if environ is None else environ
    raw = env.get(ENV_LEVEL)
    if raw is None or not raw.strip():
        return logging.INFO, None
    level = _LEVELS.get(raw.strip().upper())
    if level is None:
        return logging.INFO, f"{ENV_LEVEL}={raw!r} is not one of {', '.join(_LEVELS)}; using INFO"
    return level, None


def add_verbose_argument(parser) -> None:
    """The `--verbose` flag, worded once for every command line."""
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="also write debug diagnostics to stderr. stdout, any JSON document and the exit code "
             f"are unchanged. {ENV_LEVEL}=DEBUG|INFO|WARNING|ERROR sets the level without the flag; "
             "the flag wins.")


def configure(verbose: bool = False, environ: Optional[Mapping[str, str]] = None) -> int:
    """Set the level for this run and return it. Call once, from a command line's `main`.

    `--verbose` means DEBUG whatever the environment says; otherwise the
    environment decides, and INFO is the default.
    """
    root = _install()
    if verbose:
        level, problem = logging.DEBUG, None
    else:
        level, problem = level_from_environment(environ)
    root.setLevel(level)
    if problem:
        root.warning("%s", problem)
    return level
