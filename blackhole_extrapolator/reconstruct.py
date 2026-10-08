"""A proposal for a flattened file, never a replacement for one.

WHAT A FLATTENED FILE IS

Python source whose newlines are gone. The bytes survive, the line breaks
do not, and with them go indentation and every statement boundary. See
detect.py for the full definition and for how it happens.

WHAT THIS CAN AND CANNOT GET BACK, MEASURED

Across the 34 flattened files in a 37-repository library on 2026-09-10:

    indentation pass only (deterministic)   2 of 34 parse
    plus a keyword-splitting heuristic      0 of 34 parse
    median lines recovered                  1 -> 135

Two facts in those numbers, and the design follows from both.

The first: the deterministic pass sometimes works. When a newline was
replaced by a single space and the indentation that followed it survived, a
run of (4n+1) spaces IS a line break, recoverably, with no guessing. Two
files come all the way back that way.

The second: the heuristic pass makes correctness WORSE while making the file
far more readable. Splitting before `import`, `def`, `class` and friends
takes the median from one line to 135 -- and breaks the two that parsed,
because it also splits inside strings, inside dict literals, and inside
argument lists where those words are just words.

So they are not two attempts at the same job. The first tries to recover a
program. The second produces something a person can edit. A file of 135
lines with real indentation is an afternoon's work to finish; the same
content as one line of 36,000 characters is not. This emits whichever it
achieved and says which, in the file, at the top.

WHAT IT WILL NOT DO

Write into the repository it scanned. Nothing in the toolkit modifies a file
it did not create unless a flag explicitly asks -- `--annotate-names` is the
only thing that does -- and that property is what lets someone aim it at
thirty-seven repositories overnight without reading the diff first. It is
checked rather than promised: Tests/test_tree_immutability.py snapshots the
scanned tree and compares it afterwards, for every entry point including
this one. A reconstruction goes to a directory the caller names, and nowhere
else.

Feed itself back into the analysis. Every downstream detector reports in
one voice; a finding computed against reconstructed code would arrive
looking exactly like a finding about code somebody wrote. Reconstructed
source becomes real the day a human reviews it and commits it, and the
next scan reads it as source because by then it is.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

# A newline became a single space and the indentation after it survived, so
# a run of one-plus-4n spaces is a break followed by its indent. Anchored on
# a following non-space so a run of trailing spaces is left alone.
_INDENT_RUN = re.compile(r" ( {4})+(?=\S)")

# Words that begin a statement far more often than they appear mid-line.
# "Far more often" is not "always", which is the whole reason this pass is
# reported separately and never claimed to have produced valid Python.
_STATEMENT_START = (
    r"(?:import |from |def |class |@|if |for |while |try:|except|else:|"
    r"elif |return |raise |with |assert |yield |pass$|break$|continue$)"
)
_SPLIT_BEFORE = re.compile(r"(?<=[\w\)\]\}\'\"]) (?=" + _STATEMENT_START + r")")

HEADER = "# RECONSTRUCTED BY blackhole_extrapolator -- NOT THE ORIGINAL"


@dataclass(frozen=True)
class Reconstruction:
    """What came back, and how much of it can be believed."""

    text: str
    lines: int
    parses: bool
    passes: List[str]
    source: str

    @property
    def is_program(self) -> bool:
        """True only when the deterministic pass alone produced valid Python.

        A reconstruction that parses is not thereby CORRECT -- the bodies,
        the nesting and which headers were live code are not recoverable
        from a flattened file at any effort. It means the structure is
        self-consistent, which is the most this can ever establish.
        """
        return self.parses and "heuristic-split" not in self.passes

    def render(self) -> str:
        verdict = (
            "This parses. The indentation was recoverable because the flattening\n"
            "# replaced each newline with a single space and left the indent intact.\n"
            "# It parsing does NOT mean it is what was there: the bodies, the nesting,\n"
            "# and which headers were live code rather than docstring examples are not\n"
            "# recoverable from a flattened file at any effort."
            if self.is_program else
            "This does NOT parse, and is not meant to. It is the same content with\n"
            "# line breaks put back where they could be inferred, so a person can\n"
            "# finish it by hand. One line of many thousand characters cannot be\n"
            "# edited; this can."
        )
        return (
            f"{HEADER}\n"
            f"# source:  {self.source}\n"
            f"# passes:  {', '.join(self.passes)}\n"
            f"# lines:   {self.lines}\n"
            f"# parses:  {self.parses}\n"
            f"#\n"
            f"# {verdict}\n"
            f"#\n"
            f"# Review it before trusting a line of it. Nothing here was analysed by\n"
            f"# any detector, deliberately: a finding computed against reconstructed\n"
            f"# code would read exactly like a finding about code somebody wrote.\n"
            f"\n{self.text}"
        )


def _parses(text: str) -> bool:
    """Valid Python that actually declares something.

    "Parses" alone is the wrong test, and measurement caught it: the two
    files in a 37-repository library that came back "recovered" were the
    SILENT flattening case. Their single line begins with `#`, so Python
    reads all of it as one comment -- zero top-level statements, zero
    definitions -- and reports success. This would have named the two worst
    files in the library as the only two fully recovered ones.

    detect.py's `_is_destroyed` already draws this line for the same reason.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    return bool(tree.body)


def reconstruct(text: str, source: str = "") -> Reconstruction:
    """Put the line breaks back as far as the evidence allows.

    The deterministic pass runs always. The heuristic pass runs only when
    the first did not yield valid Python AND actually recovers more lines --
    there is no reason to trade a program for a draft.
    """
    determined = _INDENT_RUN.sub(lambda m: "\n" + m.group(0)[1:], text)
    passes = ["indent-runs"]

    if _parses(determined):
        return Reconstruction(determined, determined.count("\n") + 1, True,
                              passes, source)

    split = _SPLIT_BEFORE.sub("\n", determined)
    if split.count("\n") > determined.count("\n"):
        passes.append("heuristic-split")
        return Reconstruction(split, split.count("\n") + 1, _parses(split),
                              passes, source)
    return Reconstruction(determined, determined.count("\n") + 1, False,
                          passes, source)


def write_proposal(path: Path, into: Path, text: str | None = None) -> Path:
    """Write one reconstruction under `into`, mirroring the source's name.

    Never writes beside the original and never overwrites: an existing
    proposal may already have been edited by hand, and silently replacing
    somebody's afternoon is a worse outcome than refusing.
    """
    path = Path(path)
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    body = path.read_text(errors="replace") if text is None else text
    result = reconstruct(body, source=str(path))
    target = into / (path.stem + ".reconstructed.py")
    if target.exists():
        raise FileExistsError(f"{target} exists; refusing to overwrite a proposal")
    target.write_text(result.render())
    return target
