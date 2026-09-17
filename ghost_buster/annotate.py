"""Writing a name disagreement down in the two places somebody will look.

WHY THIS MODULE IS DIFFERENT FROM EVERY OTHER ONE

ghost_buster reads. It has never, on its own account, modified a file it
was pointed at, and that restraint is most of why it can be run against a
37-repository library without anyone reading the diff first. This module is
the exception, and it is fenced accordingly:

  * it runs only under an explicit `--annotate-names`, never by default;
  * it writes COMMENTS and a MARKDOWN TABLE, never code -- nothing it does
    can change what a program means;
  * and that last claim is not a promise, it is CHECKED. Every source edit
    is parsed before and after and the two syntax trees compared. If they
    differ by so much as a node, the edit is discarded and the file is left
    exactly as it was. A backslash continuation, a line that turns out to
    be inside a triple-quoted string, a file this module simply got wrong:
    all of them fail closed.

WHY A TRAILING COMMENT AND NOT A LINE OF ITS OWN

Inserting a line shifts every line number below it, which means a second
disagreement's recorded line is wrong before it is written, and a re-run
cannot find what the last run wrote. A comment appended to the end of an
existing line changes no line's number, so the notes can be stripped and
rewritten from scratch on every run -- which is what makes this idempotent
and what makes it follow a rename instead of accumulating behind one.

WHY BOTH PLACES

The README table is for tracking: it is one list, sorted, countable, and it
survives being read by somebody who is not in the code. The inline note is
for the moment the question actually occurs to a reader, which is while
they are looking at the signature or the call and wondering whether
`cust_pub` is the same thing as `recipient_pub`. Neither substitutes for
the other. Both are regenerated whole, and neither carries a timestamp, so
a run that finds nothing new produces no diff at all.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from .naming import Disagreement, find_name_disagreements

MARKER = "ghost_buster: name-disagreement"
BEGIN = "<!-- ghost_buster:name-disagreements:begin -->"
END = "<!-- ghost_buster:name-disagreements:end -->"

# A marker counts only on a line of its own. Found the first time this ran
# against a README that DOCUMENTS the feature: the prose naming the marker
# was matched as the marker, and the regenerated block was written over the
# documentation that explained it. Any file that describes this tool has
# the same shape, so this is the common case and not the exotic one.
_BEGIN_LINE = re.compile(r"^" + re.escape(BEGIN) + r"[ \t]*$", re.M)
_END_LINE = re.compile(r"^" + re.escape(END) + r"[ \t]*$", re.M)

# Anchored to the end of the line and to the marker, so a `#` inside a
# string literal is not a target. The AST comparison is what actually
# guarantees that; this only keeps the common case from needing it.
_TRAILING = re.compile(r"[ \t]*#[ \t]*" + re.escape(MARKER) + r"\b.*$")


def _same_program(before: str, after: str) -> bool:
    """Whether two texts are the same program.

    ast.dump ignores comments and formatting entirely, which is precisely
    the property wanted: a comment-only edit must compare equal, and
    anything else must not.
    """
    try:
        return ast.dump(ast.parse(before)) == ast.dump(ast.parse(after))
    except (SyntaxError, ValueError):
        return False


def _split(line: str) -> Tuple[str, str]:
    """(content, line ending). Keeps CRLF files CRLF and leaves a final
    line without a newline without one."""
    content = line.rstrip("\r\n")
    return content, line[len(content):]


def strip_notes(text: str) -> str:
    """Remove every note this module has written, line by line.

    Unverified on its own -- `annotate_source` is what checks each removal,
    because the marker can also appear inside a string literal, and did the
    first time this was run against a fixture containing one.
    """
    out = []
    for line in text.splitlines(keepends=True):
        content, ending = _split(line)
        out.append(_TRAILING.sub("", content) + ending)
    return "".join(out)


def annotate_source(text: str, notes: Dict[int, Sequence[str]]) -> str:
    """`text` with each note appended to the end of its 1-indexed line.

    Existing notes are removed first, so the result depends only on `notes`
    and running twice is the same as running once.

    ONE INVARIANT, CHECKED ON EVERY EDIT: the result is the same program as
    the input. Each removal and each insertion is tried on its own and kept
    only if the syntax tree is unchanged, so a line that cannot carry a
    comment -- a backslash continuation, a marker that is really part of a
    string -- costs that one line and not the file. An earlier version
    checked the whole strip at once, and a single fixture with the marker
    inside a string literal silently cost every annotation in the file.
    """
    lines = text.splitlines(keepends=True)

    def keep(candidate: List[str]) -> bool:
        return _same_program(text, "".join(candidate))

    for index, line in enumerate(lines):
        content, ending = _split(line)
        without = _TRAILING.sub("", content)
        if without == content:
            continue
        candidate = list(lines)
        candidate[index] = without + ending
        if keep(candidate):
            lines = candidate

    for number, bodies in sorted(notes.items()):
        if not 1 <= number <= len(lines):
            continue
        content, ending = _split(lines[number - 1])
        if not content.strip() or content.rstrip().endswith("\\"):
            # A blank line cannot be annotated, and a backslash
            # continuation must stay the last thing on its line.
            continue
        candidate = list(lines)
        # Sorted here rather than at the call site, so the output depends on
        # WHICH notes belong on a line and not on the order they were found.
        # Idempotence is the point: two runs must produce the same byte.
        note = "  # " + MARKER + " -- " + "; ".join(sorted(bodies))
        candidate[number - 1] = content + note + ending
        if keep(candidate):
            lines = candidate
    return "".join(lines)


def notes_for(disagreements: Iterable[Disagreement]) -> Dict[str, Dict[int, List[str]]]:
    """file -> line -> the notes belonging on it.

    A signature is told what its callers write; a call is told what the
    signature calls it. Same fact from the side the reader is standing on.
    """
    out: Dict[str, Dict[int, List[str]]] = {}

    def add(path: str, line: int, body: str) -> None:
        out.setdefault(path, {}).setdefault(line, []).append(body)

    for d in disagreements:
        for path, line in d.definitions:
            add(path, line, f"`{d.param}` is `{d.arg}` at every call site")
        for path, line in d.call_sites:
            add(path, line, f"`{d.arg}` is `{d.param}` in the signature")
    return out


def annotate_files(disagreements: Iterable[Disagreement],
                   files: Iterable[Path] = (),
                   root: Path | None = None) -> List[Path]:
    """Write the notes. Returns the files actually changed.

    Every scanned file is visited, not only the ones with something to say,
    because the interesting case is the file that USED to have something to
    say. When a rename settles a disagreement it vanishes from the results,
    and a sweep driven by the results alone would never look at the file
    again -- leaving the note behind to describe a disagreement that no
    longer exists, which is worse than never having written it.
    """
    by_file = notes_for(disagreements)
    # Python only. The scan also carries .md files, and a markdown file that
    # does not parse as Python would be refused edit by edit anyway -- but
    # silently and at the cost of a parse per line.
    targets = sorted({str(f) for f in map(Path, files) if f.suffix == ".py"}
                     | set(by_file))
    changed: List[Path] = []
    for name in targets:
        notes = by_file.get(name, {})
        path = Path(name)
        if refuses(path, root) is not None:
            continue
        try:
            before = path.read_text()
        except OSError:
            continue
        after = annotate_source(before, notes)
        if after == before:
            continue
        try:
            path.write_text(after)
        except OSError:
            continue
        changed.append(path)
    return changed


def refuses(path: Path, root: Path | None) -> str | None:
    """Why this path must not be written, or None if it may be.

    THE HOLE THIS CLOSES

    Every other write in this tool resolves its target and checks that the
    result is inside the patient before touching it -- `operate._resolve`
    does exactly that for a finding's file, and declines rather than
    guessing when the answer is not inside. This module did not, because it
    does not take paths from findings: it composes `root / "README.md"` and
    walks the corpus, and both of those were assumed to be inside the tree
    by construction.

    A symlink breaks the assumption. A README that is a link to a file
    outside the repository is an ordinary thing for a repository to contain,
    and writing "the README" then writes somewhere else entirely -- outside
    the branch the operation opened, so outside anything the operation can
    revert, and outside the commit it then tries to make, which fails with
    nothing to commit and reports a symptom after the damage.

    So the check is here, at the write, rather than at each caller. Both
    callers reach this module by different routes (`--annotate-names` and
    `--operate`) and a guard on one of them is a guard on neither.

    Resolution follows symlinks on purpose: the question is not what the
    path is spelled, it is which file the bytes will land in.
    """
    if root is None:
        # Nothing to be inside of. The caller did not say where the patient
        # is, so there is no containment claim to check and none is made.
        return None
    try:
        target = Path(path).resolve()
        target.relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return f"{Path(path).name} resolves outside the repository"
    return None


def _relative(path: str, root: Path | None) -> str:
    if root is None:
        return Path(path).name
    try:
        return str(Path(path).resolve().relative_to(root.resolve()))
    except ValueError:
        return Path(path).name


def render_section(disagreements: Sequence[Disagreement], root: Path | None = None) -> str:
    """The README block, regenerated whole and carrying no timestamp."""
    rows = []
    for d in sorted(disagreements, key=lambda d: (d.param, d.arg)):
        files = ", ".join(f"`{_relative(f, root)}`" for f in d.files)
        rows.append(f"| `{d.param}` | `{d.arg}` | {len(d.call_sites)} | {files} |")

    body = "\n".join(rows) if rows else "| _none_ | | | |"
    count = (f"{len(rows)} disagreement(s)." if rows
             else "No disagreements. This block records that the check ran.")
    return "\n".join([
        BEGIN,
        "## Name disagreements",
        "",
        "One value carried under two names. Every row is a bijection: the",
        "parameter receives that variable and no other, and the variable reaches",
        "that parameter and no other. That is the only case where the two names",
        "provably denote one thing, and the only case where substituting one for",
        "the other cannot capture a name that is legitimately in use elsewhere.",
        "",
        "Nothing here has been renamed. Which name should win is a judgement:",
        "the parameter is the contract, the variable is the caller's local, and",
        "neither is automatically right.",
        "",
        "| parameter | variable | call sites | files |",
        "| --- | --- | --- | --- |",
        body,
        "",
        count,
        "",
        "Regenerated by `ghost_buster <path> --annotate-names`, which also writes",
        "the same note inline on each signature and each call. Edit the code, not",
        "this block: it is rewritten whole every run and contains no timestamp, so",
        "a run that changes nothing produces no diff.",
        END,
        "",
    ])


def update_readme(path: Path, disagreements: Sequence[Disagreement],
                  root: Path | None = None) -> bool:
    """Replace the marked block, or append one. True if the file changed.

    Refuses two things, both of them additions nobody asked for.

    A path that resolves outside the repository. See `refuses`.

    A section recording nothing, in a document that never had one. The
    count-block remedy states the principle and declines to write its own
    markers for it: "a scanner that inserts its own markup into somebody's
    README uninvited has decided something that was not its to decide."
    That argument does not stop being true one module over. An existing
    block is different -- the repository opted in by carrying it, and
    "no disagreements, this block records that the check ran" is then a
    fact somebody asked to be told.
    """
    if refuses(path, root) is not None:
        return False

    section = render_section(disagreements, root)
    try:
        before = path.read_text()
    except OSError:
        before = ""

    opened, closed = _BEGIN_LINE.search(before), _END_LINE.search(before)
    if opened and closed and closed.start() > opened.start():
        after = (before[:opened.start()] + section
                 + before[closed.end():].lstrip("\n"))
    elif not disagreements:
        return False
    else:
        prefix = before if not before or before.endswith("\n") else before + "\n"
        after = prefix + ("\n" if prefix else "") + section

    if after == before:
        return False
    path.write_text(after)
    return True


def annotate(files: Sequence[Path], readme: Path,
             root: Path | None = None) -> Tuple[List[Disagreement], List[Path], bool]:
    """Find the disagreements, write both records, say what happened."""
    disagreements = find_name_disagreements(files)
    changed = annotate_files(disagreements, files, root=root)
    wrote_readme = update_readme(readme, disagreements, root)
    return disagreements, changed, wrote_readme
