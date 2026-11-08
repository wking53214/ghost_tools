"""delivery.py -- what a command line does when its report cannot be delivered.

Every command that prints a report (ghost-buster, ghost-writer, ghost-triage,
blackhole-extrapolator, stack-census, ghost-rank) goes through `delivers`. The
three ways delivery fails, and what happens in each:

  * The reader went away (`ghost-buster DIR | head -3`, a closed pipe: EPIPE).
    The run finishes, nothing more is written, one plain line goes to stderr and
    the exit code is the one the run EARNED (0 clean, 1 findings, 2 usage). A
    reader that stopped listening is not a defect of the scan.
  * Standard output is closed (file descriptor 1 was closed before the command
    started, so Python has no `sys.stdout`) or is full (`/dev/full`, a disk with
    no room: ENOSPC) or fails in any other way. Nothing was delivered, so a run
    that would have exited 0 exits EXIT_OUTPUT instead, with one plain line on
    stderr. A run that already exits non-zero keeps its code: 1 still says
    "findings", 2 "did not start", 3 "crashed", 130 "interrupted".
  * Neither is a traceback, and neither makes a crashed scan look clean: only a
    delivery failure is absorbed here. Any other exception passes through to the
    command's own crash boundary untouched.

HOW. For the length of the run `sys.stdout` is a thin stream that passes every
write through and, on the first failure, remembers it and drops what follows
(the scan still runs to its end, so its side effects and its exit code are the
same as with a healthy pipe). The stream is flushed when the run ends, because a
pipe or a file buffers and the failure often surfaces only there. After a failure
on the process's real standard output, file descriptor 1 is pointed at the null
device so the flush Python does at interpreter exit cannot fail a second time
(that second failure is what turns an exit 0 into 120 and prints "Exception
ignored"); this is the recipe in the Python documentation.

A decorated command called again while one is already running (an embedding
program, a test) is not wrapped twice: the outer one owns the stream.
"""
from __future__ import annotations

import errno
import functools
import os
import sys
from typing import Any, Callable, Optional, TextIO, TypeVar, cast

from .diagnostics import get_logger

#: Exit code of a run whose report could not be delivered (standard output closed, full or failing) and which
#: would otherwise have exited 0. A reader that left (broken pipe) does not use it: that keeps the earned code.
EXIT_OUTPUT = 4

#: errno values that mean "the reader went away", as opposed to "the place the report goes is unusable".
_READER_LEFT = frozenset({errno.EPIPE, errno.ECONNRESET, getattr(errno, "ESHUTDOWN", errno.EPIPE)})

log = get_logger(__name__)


class _Failure:
    """The first delivery failure of a run."""

    def __init__(self, reader_left: bool, reason: str) -> None:
        self.reader_left = reader_left
        self.reason = reason


class _GuardedStdout:
    """Standard output for the length of one run: writes pass through until one fails."""

    def __init__(self, stream: Optional[TextIO]) -> None:
        self._stream = stream
        self.failure: Optional[_Failure] = None
        if stream is None:
            self.failure = _Failure(False, "standard output is closed")

    def _record(self, exc: BaseException) -> None:
        reader_left = isinstance(exc, BrokenPipeError) or getattr(exc, "errno", None) in _READER_LEFT
        self.failure = _Failure(reader_left, f"{type(exc).__name__}: {exc}")
        _silence_exit_flush(self._stream)

    def _absorbs(self, exc: BaseException) -> bool:
        """An OSError is a delivery failure. A ValueError is one only for a closed stream: a UnicodeEncodeError,
        which is also a ValueError, is the report not being encodable, a different defect that must stay loud."""
        if isinstance(exc, OSError):
            return True
        return (isinstance(exc, ValueError) and not isinstance(exc, UnicodeError)
                and getattr(self._stream, "closed", False))

    def write(self, text: str) -> int:
        if self.failure is not None:
            return len(text)
        assert self._stream is not None
        try:
            return self._stream.write(text)
        except (OSError, ValueError) as exc:
            if not self._absorbs(exc):
                raise
            self._record(exc)
            return len(text)

    def writelines(self, lines: Any) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        if self.failure is not None or self._stream is None:
            return
        try:
            self._stream.flush()
        except (OSError, ValueError) as exc:
            if not self._absorbs(exc):
                raise
            self._record(exc)

    def isatty(self) -> bool:
        return False if self._stream is None else self._stream.isatty()

    def __getattr__(self, name: str) -> Any:
        # encoding, errors, fileno, buffer and the rest: whatever the real stream says. A missing stream has none.
        if name.startswith("__") or self._stream is None:
            raise AttributeError(name)
        return getattr(self._stream, name)


def _silence_exit_flush(stream: Optional[TextIO]) -> None:
    """Point the process's real standard output at the null device after it failed.

    Only for the real `sys.__stdout__`: a stream someone else supplied (a test's capture, an embedding program's
    buffer) is theirs and is left alone. Opening the null device for writing is what every `> /dev/null` does;
    nothing is created, replaced or removed.
    """
    real = sys.__stdout__
    if real is None or stream is not real:
        return
    try:
        fd = real.fileno()
        null = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null, fd)
        finally:
            os.close(null)
    except (OSError, ValueError):
        pass


def _outcome(prog: str, guard: _GuardedStdout, code: int) -> int:
    """Say what went wrong, once, and return the code the process should exit with."""
    failure = guard.failure
    if failure is None:
        return code
    if failure.reader_left:
        log.error("%s: the reader of standard output went away (%s); the output is incomplete "
                  "and the exit code is the one the run earned", prog, failure.reason)
        return code
    if code == 0:
        log.error("%s: standard output could not be written (%s); the report was not delivered, exit %d",
                  prog, failure.reason, EXIT_OUTPUT)
        return EXIT_OUTPUT
    log.error("%s: standard output could not be written (%s); the report was not delivered", prog, failure.reason)
    return code


F = TypeVar("F", bound=Callable[..., int])


def delivers(prog: str) -> Callable[[F], F]:
    """Decorate a command's `main` so a report that cannot be delivered is handled as the module docstring says."""

    def decorate(main: F) -> F:
        @functools.wraps(main)
        def wrapper(*args: Any, **kwargs: Any) -> int:
            if isinstance(sys.stdout, _GuardedStdout):
                return main(*args, **kwargs)
            original = sys.stdout
            guard = _GuardedStdout(original)
            sys.stdout = cast(TextIO, guard)
            try:
                try:
                    code = main(*args, **kwargs)
                except SystemExit as exc:
                    # --help and --version print, then exit: the same rule applies to their code.
                    guard.flush()
                    if exc.code is None or isinstance(exc.code, int):
                        earned = 0 if exc.code is None else exc.code
                        final = _outcome(prog, guard, earned)
                        if final != earned:
                            raise SystemExit(final) from None
                    else:
                        _outcome(prog, guard, 1)
                    raise
                guard.flush()
            finally:
                sys.stdout = cast(TextIO, original)
            return _outcome(prog, guard, code)

        return cast(F, wrapper)

    return decorate
