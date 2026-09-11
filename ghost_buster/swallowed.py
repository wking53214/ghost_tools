"""A handler that catches something and does nothing with it.

THE SAME ARGUMENT dead_end_call MAKES, ONE LEVEL DOWN

`dead_end_call` reports a callable whose body does nothing while live code
calls it: the caller believes the work happened. This is the same failure
inside an exception handler. Something went wrong, something caught it, and
nothing happened -- so the operation reports success and the report says the
check passed.

    try:
        publish(decision)
    except Exception:
        pass

That is not error handling. It is the removal of error handling, written in
a shape that looks like error handling, and it survives review for exactly
that reason.

WHY BREADTH SETS THE SEVERITY

Swallowing is sometimes correct, and what separates the two is what is
caught, not whether the body is empty.

    except ImportError: pass        an optional dependency is absent. The
                                    handler IS the behaviour, and the class
                                    of failure it hides is one class.

    except Exception: pass          catches the optional dependency, and also
                                    the typo, the None, the failed write and
                                    the bug introduced next year. Nothing
                                    that goes wrong in that block can ever
                                    be seen again.

So a bare `except:` or `except Exception:` is MAJOR, and a named, narrow
exception is MINOR. Measured 2026-09-10 across 24 live repositories: 32
silent handlers in live code, 13 of them catching bare Exception, in ANVIL,
CCC, Ecology and AUGUR. A further 22 are in test files and are not reported,
for the same reason the naming and dead-end detectors skip tests: best-effort
cleanup in a teardown is ordinary, and `is_test_path` is shared so all three
agree on what a test file is.

SCOPE, DISCLOSED

Only `pass`. A handler whose body is `continue`, `return None` or a lone
`logger.debug(...)` swallows just as thoroughly, and each would need its own
measurement before it earned a place here -- a `continue` in a retry loop is
often exactly right, and rating it alongside `except Exception: pass` is how
a report teaches its reader to skim. `contextlib.suppress` is deliberately
not flagged at all: it says in its own name what it does, which is the
opposite of the defect.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from . import corpus
from .naming import is_test_path
from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "swallowed_exception"

BARE = "bare except"

# Catching one of these catches everything, including the bug that has not
# been written yet.
_CATCHES_EVERYTHING = frozenset({"Exception", "BaseException"})


def _caught(handler: ast.ExceptHandler) -> str:
    if handler.type is None:
        return BARE
    try:
        return ast.unparse(handler.type)
    except (AttributeError, ValueError):        # pragma: no cover
        return BARE


def _swallows(handler: ast.ExceptHandler) -> bool:
    """Whether the handler's entire body is `pass`.

    A docstring is stripped first, the same way it is in deadend.py: a
    handler documented at length and implemented not at all is still a
    handler that does nothing.
    """
    body = list(handler.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return len(body) == 1 and isinstance(body[0], ast.Pass)


@dataclass(frozen=True)
class Swallowed:
    path: Path
    line: int
    caught: str

    @property
    def catches_everything(self) -> bool:
        if self.caught == BARE:
            return True
        names = {n.strip(" ()") for n in self.caught.split(",")}
        return bool(names & _CATCHES_EVERYTHING)


def find_swallowed(files: Sequence[Path]) -> List[Swallowed]:
    out: List[Swallowed] = []
    for path in (Path(f) for f in files):
        if is_test_path(path):
            continue
        tree = corpus.parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _swallows(node):
                out.append(Swallowed(path, node.lineno, _caught(node)))
    return sorted(out, key=lambda s: (str(s.path), s.line))


def detect_swallowed_exceptions(files: Sequence[Path]) -> List[Finding]:
    findings: List[Finding] = []
    for swallowed in find_swallowed(files):
        broad = swallowed.catches_everything
        findings.append(Finding(
            detector=DETECTOR,
            category=Category.VACUOUS_CHECK,
            layer=Layer.MECHANICAL,
            severity=Severity.MAJOR if broad else Severity.MINOR,
            status=Status.CONFIRMED,
            summary=(f"`except {swallowed.caught}` at {swallowed.path.name}:"
                     f"{swallowed.line} does nothing with what it catches"),
            detail=(
                f"{swallowed.path}:{swallowed.line}\n"
                + ("This catches everything -- the missing dependency it was "
                   "probably written for, and also the typo, the None, the "
                   "failed write and the bug introduced next year. Nothing "
                   "that goes wrong in this block can be seen again, which is "
                   "why it is MAJOR.\n" if broad else
                   f"`{swallowed.caught}` is narrow, so the handler hides one "
                   "class of failure and may well be the intended behaviour "
                   "-- an absent optional dependency is the usual case. MINOR "
                   "for that reason, and worth a look rather than a fix.\n")
                + "The operation reports success either way. That is the same "
                  "failure `dead_end_call` reports one level up: the caller "
                  "believes the work happened.\n"
                  "`contextlib.suppress` is not flagged: it says in its own "
                  "name what it does."
            ),
            evidence=Evidence(file=str(swallowed.path), line_start=swallowed.line),
            attributes={"caught": swallowed.caught},
        ))
    return findings
