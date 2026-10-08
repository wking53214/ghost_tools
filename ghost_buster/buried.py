"""A module whose code is all inside comments.

THE FAILURE THIS CATCHES

A Python file that imports without error, raises nothing, and defines
nothing, because every line of its code sits behind a `#`. The usual cause
is a paste through a chat window that destroyed every line break: if the
first character of the surviving single line happens to be `#`, the whole
file becomes one comment. ASSAY keeps the canonical specimen
(`specimens/pairs/governance_os_security_source.py`, 11,700 bytes, one line,
zero names) and its MANIFEST answer is REFUSE.

Every other flattened file fails loudly with a SyntaxError, and
`unassessable_file` reports it. This one parses, so it is not unassessable,
and every structural detector looks at an empty module and finds nothing
wrong with it. An importability check calls it healthy. That is the silent
pass: something satisfies its check without doing its job.

WHAT COUNTS

A `.py` file that
  - parses,
  - has no statements beyond an optional docstring (so it defines nothing,
    imports nothing, runs nothing), and
  - carries at least MINIMUM_SIGNATURES `def name(` / `class Name` shapes in
    its comments.

The third condition is the whole difference between a buried module and an
ordinary empty `__init__.py` with a licence header: a header does not
contain function signatures.

WHAT IT DOES NOT DO

Report commented-out code inside a module that also has live code. That is
a tidiness question with a different answer, and a module with one live
function and twenty commented-out ones is not silent: it does something.
This detector is about the file that does nothing while looking like it
should.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path
from typing import List

from . import corpus
from .schema import Category, Evidence, Finding, Layer, Severity, Status, _portable_path

DETECTOR = "commented_out_module"

#: One signature in a comment is a note ("see def foo(") or an example. Two
#: is the smallest count that stops a docstring-style usage hint from firing.
MINIMUM_SIGNATURES = 2

_SIGNATURE = re.compile(r"\b(?:def\s+[A-Za-z_]\w*\s*\(|class\s+[A-Z]\w*\s*[(:])")


def _is_empty_module(tree: ast.Module) -> bool:
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None),
                                                               ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return not body


def _comment_text(source: str) -> str:
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                out.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return ""
    return "\n".join(out)


def detect_commented_out_modules(files: List[Path]) -> List[Finding]:
    out: List[Finding] = []
    for path in sorted(f for f in files if f.suffix == ".py"):
        tree = corpus.parse(path)
        if tree is None or not _is_empty_module(tree):
            continue
        source = corpus.text(path) or ""
        if not source.strip():
            continue
        signatures = _SIGNATURE.findall(_comment_text(source))
        if len(signatures) < MINIMUM_SIGNATURES:
            continue
        lines = source.count("\n") + (0 if source.endswith("\n") else 1)
        out.append(Finding(
            detector=DETECTOR,
            category=Category.OTHER,
            layer=Layer.MECHANICAL,
            severity=Severity.MAJOR,
            status=Status.CONFIRMED,
            summary=(f"{_portable_path(path)} parses but defines nothing: its "
                     f"{len(signatures)} def/class signature(s) are all inside comments "
                     f"({len(source):,} bytes on {lines} line(s))"),
            evidence=Evidence(file=str(path), line_start=1,
                              snippet=source.lstrip()[:200]),
            detail=(
                "A silent pass. This file imports cleanly and raises nothing, so "
                "an importability check, and every structural detector, reports "
                "it as healthy. It is not: every definition in it is commented "
                "out, so importing it gives you an empty module.\n\n"
                "The usual cause is a copy-paste that destroyed the line breaks "
                "and left one enormous line beginning with `#`. If so, the code "
                "is recoverable by restoring the breaks; if a readable copy of "
                "the same content exists elsewhere, that copy is the one to keep."
            ),
            attributes={"signatures_in_comments": len(signatures), "bytes": len(source),
                        "lines": lines},
        ))
    return out
