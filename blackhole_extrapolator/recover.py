"""The original itself, when it still exists somewhere, instead of a guess.

WHY THIS IS NOT reconstruct.py

`reconstruct` rebuilds a flattened file by reasoning about where the line
breaks probably went. It is honest about being a proposal, and across a
37-repository library it recovered a running program in 0 of 34 cases. It
gets you something editable, not something correct.

This module does something categorically different. Flattening is a
WHITESPACE-ONLY transform -- measured on 2026-09-10, the 37 flattened files
in that library fall into exactly two shapes, one where every newline became
a single space and the indentation survived (space runs of 4n+1), and one
where every whitespace run collapsed to a single space. Neither adds,
removes or reorders a single non-whitespace character.

That gives a test with no guesswork in it:

    collapse(x) = every whitespace run replaced by one space

collapse() is INVARIANT under flattening. So if some other text collapses to
exactly what the flattened file collapses to, that text is the original, up
to whitespace. Not the most likely original. The original.

Chat-history exports are where the originals usually still are. The raw
ChatGPT export checked on 2026-09-10 held 20,919 fenced code blocks, 14,185
of them carrying real newlines; the only 39 single-line blocks over 200
characters were Excel formulas, which genuinely are one line. The vendor
ships code with its newlines intact. The damage happens after the download,
at a paste.

FOUR VERDICTS, AND ONLY TWO OF THEM WRITE ANYTHING

  identical   a candidate collapses to exactly this file's collapse. It is
              the original. Recovered verbatim.

  contained   this file's collapse is a substring of a candidate's. The
              message holds the code plus the prose around it. The span is
              located in the candidate's REAL text -- through an index built
              alongside the collapse, so the recovered slice is the
              original's own bytes, not a re-derivation -- and recovered.

  related     high identifier overlap, no collapse match. A different draft
              of the same system, which is interesting and is NOT the
              original. Reported; never written. This is the verdict that
              keeps the module honest: 4 of the 37 files scored 100%
              identifier overlap against a message that was a different
              version of the same code.

  none        nothing in the corpus is close.

WHAT IT WILL NOT DO

Write into the scanned tree, or over an existing recovery. Add a header to
a recovered file: a reconstruction is annotated because it is a guess, and
annotating a byte-faithful original would make it stop being one. The
provenance goes in a manifest beside the files instead.

Recover a file whose collapse does not match. There is no partial credit
here and no threshold to tune -- either the bytes are the same modulo
whitespace or this module has nothing to say.
"""

from __future__ import annotations

import ast
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence, Tuple

IDENTICAL = "identical"
CONTAINED = "contained"
RELATED = "related"
NONE = "none"

# Identifier similarity at which a non-matching candidate is worth naming as
# a different draft of the same thing. It gates a REPORT, never a write, so
# it is a readability threshold and not a correctness one.
#
# SYMMETRIC (intersection over union), not "how much of this file the
# candidate covers". One-directional coverage rewards a candidate for being
# large: run against a real library on 2026-09-10, the derived `raw.csv`
# holding EVERY message in an export scored 100% against eight different
# files, because a blob containing everything contains everything. Union in
# the denominator prices that in.
RELATED_OVERLAP = 0.40

# What makes a string worth considering: real line breaks and something that
# looks like Python. A candidate with no newlines cannot be the original of
# anything, since the whole point is that the original had them.
MINIMUM_LINES = 3
_PYTHONISH = ("def ", "class ", "import ")
_FENCE = re.compile(r"```[A-Za-z]*\n(.*?)```", re.S)
# An HTML-rendered corpus stores `"""` as `&quot;&quot;&quot;`, which no
# amount of whitespace normalisation will turn back into a match. Decoding is
# lossless and unambiguous, and it only ADDS a candidate -- the raw form is
# still there, and a decoded candidate still has to pass the same exact
# collapse test as any other. Measured 2026-09-10: it moved files out of
# `related` and into recovered.
_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]{1,31}|#[0-9]{1,7}|#[Xx][0-9A-Fa-f]{1,6});")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]{4,}")
_WHITESPACE = re.compile(r"\s+")

# U+00A0. Gemini's Takeout export is HTML, and HTML writes an indent as
# `&nbsp;`, so the decoded text carries non-breaking spaces where the code
# had ordinary ones. Python rejects U+00A0 outside a string literal, so a
# byte-faithful recovery from that corpus does not parse -- measured
# 2026-09-10: 11 of 21 recoveries, 9 of them fixed by this one substitution.
#
# `\s` is Unicode-aware, so collapse() already treats U+00A0 as whitespace.
# That is WHY these files matched at all, and it is also why substituting
# cannot invalidate the collapse check that guards the write.
NBSP = "\u00a0"
REPAIR_NBSP = "nbsp-to-space"


def collapse(text: str) -> str:
    """Every whitespace run as one space. Invariant under flattening."""
    return _WHITESPACE.sub(" ", text).strip()


def collapse_with_index(text: str) -> Tuple[str, List[int]]:
    """`collapse(text)`, plus the position in `text` of each character in it.

    The index is what makes `contained` a recovery rather than another
    reconstruction: a span found in the collapsed form maps back to the
    original's own bytes, whitespace and all, instead of being rebuilt from
    the collapsed copy.
    """
    out: List[str] = []
    index: List[int] = []
    after_space = True
    for position, character in enumerate(text):
        if character.isspace():
            if not after_space:
                out.append(" ")
                index.append(position)
            after_space = True
        else:
            out.append(character)
            index.append(position)
            after_space = False
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def parses(text: str) -> bool:
    """Real Python with at least one statement in it.

    `bool(tree.body)` and not just "no SyntaxError": a file whose whole
    content is one comment parses cleanly and defines nothing, which is the
    silent half of what flattening does.
    """
    try:
        return bool(ast.parse(text).body)
    except (SyntaxError, ValueError):
        return False


def repair(text: str) -> Tuple[str, Tuple[str, ...]]:
    """Substitutions applied ONLY when they turn a file that does not parse
    into one that does.

    A repair that cannot demonstrate it helped is not applied. That keeps
    this from becoming a general cleanup pass over somebody's recovered
    source: two of the 21 recoveries measured on 2026-09-10 carry smart
    quotes and a truncated string, and both are left exactly as they came
    out of the corpus, reported as not parsing. Damage in the corpus is a
    fact about the corpus, and quietly patching it here would hide it.
    """
    if parses(text) or NBSP not in text:
        return text, ()
    candidate = text.replace(NBSP, " ")
    if parses(candidate):
        return candidate, (REPAIR_NBSP,)
    return text, ()


def identifiers(text: str) -> set:
    return set(_IDENTIFIER.findall(text))


@dataclass(frozen=True)
class Source:
    """One candidate original, and where it came from."""

    origin: str
    label: str
    text: str


@dataclass(frozen=True)
class Recovery:
    path: Path
    verdict: str
    text: str | None = None
    origin: str = ""
    label: str = ""
    overlap: float = 0.0
    repairs: Tuple[str, ...] = ()

    @property
    def parses(self) -> bool:
        return parses(self.text) if self.text else False

    @property
    def is_recovered(self) -> bool:
        return self.verdict in (IDENTICAL, CONTAINED) and self.text is not None

    @property
    def lines(self) -> int:
        return self.text.count("\n") + 1 if self.text else 0


# --------------------------------------------------------------- the corpus

def _strings(node: object) -> Iterator[str]:
    """Every string leaf in a decoded JSON document.

    Schema-agnostic on purpose. ChatGPT, Claude, Copilot and Gemini exports
    all nest their message text differently, and a reader that knows one
    shape silently returns nothing on the other three -- which reads exactly
    like "the original is not in there".
    """
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _worth_keeping(text: str) -> bool:
    return (text.count("\n") >= MINIMUM_LINES
            and any(marker in text for marker in _PYTHONISH))


def _variants(text: str) -> Iterator[str]:
    """The text as stored, and its HTML-decoded form when they differ."""
    yield text
    if _ENTITY.search(text):
        decoded = html.unescape(text)
        if decoded != text:
            yield decoded


def _candidates(text: str) -> Iterator[str]:
    """The string itself when it is Python-shaped, and every fenced block in
    it. Both, because a message is often prose wrapped around a code block:
    the fence gives an `identical` match where the whole message would only
    give a `contained` one."""
    for variant in _variants(text):
        if _worth_keeping(variant):
            yield variant
        for block in _FENCE.findall(variant):
            if _worth_keeping(block):
                yield block


def harvest(paths: Sequence[Path]) -> List[Source]:
    """Every candidate original under `paths`.

    Reads .json and .jsonl as data and everything else as text, so a
    directory of exported transcripts works as well as a raw export.
    """
    sources: List[Source] = []
    seen: set = set()
    for path in _files(paths):
        try:
            raw = path.read_text(errors="replace")
        except OSError:
            continue
        for text in _payloads(path, raw):
            for candidate in _candidates(text):
                key = hash(candidate)
                if key in seen:
                    continue
                seen.add(key)
                sources.append(Source(origin=path.name,
                                      label=_label(candidate), text=candidate))
    return sources


def _files(paths: Sequence[Path]) -> Iterator[Path]:
    for entry in (Path(p) for p in paths):
        if entry.is_dir():
            yield from (p for p in sorted(entry.rglob("*")) if p.is_file())
        elif entry.is_file():
            yield entry


def _payloads(path: Path, raw: str) -> Iterator[str]:
    if path.suffix == ".jsonl":
        for line in raw.splitlines():
            try:
                yield from _strings(json.loads(line))
            except ValueError:
                continue
    elif path.suffix == ".json":
        try:
            yield from _strings(json.loads(raw))
        except ValueError:
            yield raw
    else:
        yield raw


def _label(text: str) -> str:
    """A first line worth showing in a manifest."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:70]
    return ""


# -------------------------------------------------------------- the matching

class Corpus:
    """The candidates, prepared once.

    The collapsed form of every candidate is computed here and kept; the
    POSITION INDEX is not. Building the index for all of them would cost one
    integer per character -- measured against a real export, 3,235 candidates
    at roughly 180 MB -- to serve the handful of `contained` hits that
    actually need it. So the index is built for the one candidate that
    matches, at the moment it matches.

    Recomputing the collapse per file instead of once cost 114 seconds
    against that export. Sharing a Corpus across files is the whole reason
    this class exists.
    """

    def __init__(self, sources: Sequence[Source]) -> None:
        self.entries = [(s, collapse(s.text), identifiers(s.text)) for s in sources]

    def __len__(self) -> int:
        return len(self.entries)

    def match(self, path: Path, flattened: str) -> Recovery:
        """The best verdict available, not the first one found.

        An `identical` match anywhere in the corpus outranks a `contained`
        one, however early the contained hit appears. A message is usually
        prose wrapped around a code block, and both are harvested -- so the
        whole message matches as `contained` while the fence inside it
        matches as `identical`, and returning on the first hit would decide
        that by corpus order.
        """
        target = collapse(flattened)
        if not target:
            return Recovery(path=path, verdict=NONE)

        wanted = identifiers(flattened)
        contained: Tuple[Source, int] | None = None
        best_score, best_source = 0.0, None

        for source, collapsed, ids in self.entries:
            if collapsed == target:
                text, repairs = repair(source.text)
                return Recovery(path=path, verdict=IDENTICAL, text=text,
                                origin=source.origin, label=source.label,
                                overlap=1.0, repairs=repairs)
            if contained is None:
                start = bounded_find(collapsed, target)
                if start != -1:
                    contained = (source, start)
                elif wanted and ids:
                    score = len(wanted & ids) / len(wanted | ids)
                    if score > best_score:
                        best_score, best_source = score, source

        if contained is not None:
            source, start = contained
            text, repairs = repair(_span(source.text, target, start))
            return Recovery(path=path, verdict=CONTAINED, text=text,
                            origin=source.origin, label=source.label,
                            overlap=1.0, repairs=repairs)
        if best_source is not None and best_score >= RELATED_OVERLAP:
            return Recovery(path=path, verdict=RELATED, origin=best_source.origin,
                            label=best_source.label, overlap=best_score)
        return Recovery(path=path, verdict=NONE, overlap=best_score)


def bounded_find(collapsed: str, target: str) -> int:
    """Where `target` sits in `collapsed`, on token boundaries only.

    A plain `find` will happily match starting in the middle of a word: a
    file beginning `port os ...` is found inside `import os ...`, and the
    span recovered from it starts mid-identifier and is not the original of
    anything. Because collapse normalises every gap to one space, "on a
    boundary" is exactly "preceded and followed by a space or an end".
    """
    start = collapsed.find(target)
    while start != -1:
        after = start + len(target)
        if ((start == 0 or collapsed[start - 1] == " ")
                and (after == len(collapsed) or collapsed[after] == " ")):
            return start
        start = collapsed.find(target, start + 1)
    return -1


def _span(text: str, target: str, start: int) -> str:
    """The original's own bytes for a span located in its collapsed form."""
    _, index = collapse_with_index(text)
    return text[index[start]:index[start + len(target) - 1] + 1]


def recover_one(path: Path, flattened: str, sources: Sequence[Source]) -> Recovery:
    """One file against a corpus built on the spot. Convenient for a single
    lookup; for a whole tree use `recover`, which builds the Corpus once."""
    return Corpus(sources).match(Path(path), flattened)


def recover(files: Iterable[Path], sources: Sequence[Source] | Corpus) -> List[Recovery]:
    corpus = sources if isinstance(sources, Corpus) else Corpus(sources)
    out: List[Recovery] = []
    for path in files:
        try:
            text = Path(path).read_text(errors="replace")
        except OSError:
            continue
        out.append(corpus.match(Path(path), text))
    return out


# --------------------------------------------------------------- the writing

def recovered_name(path: Path, root: Path | None = None) -> str:
    """A filename that survives a library where four repositories each hold
    an `artifact_1.py`.

    Measured 2026-09-10: naming a recovery after the stem alone refused 6 of
    27 recoveries as "a proposal already exists", when nothing was actually
    in conflict -- they were different files from different repositories
    that happened to share a name. The path is what distinguishes them, so
    the path is in the name.
    """
    path = Path(path)
    if root is not None:
        try:
            relative = path.resolve().relative_to(Path(root).resolve())
            return relative.with_suffix("").as_posix().replace("/", "__") + ".recovered.py"
        except ValueError:
            pass
    return path.stem + ".recovered.py"


def write_recovery(recovery: Recovery, into: Path, root: Path | None = None) -> Path:  # ghost_buster: name-disagreement -- `recovery` is `result` at every call site
    """Write one recovered original under `into`, verbatim.

    Checked before it is written, not asserted in a docstring: a recovery
    whose collapse does not match the flattened file's is refused. That is
    the same test the match was made on, run again against what is about to
    hit the disk.
    """
    if not recovery.is_recovered:
        raise ValueError(f"{recovery.path}: verdict {recovery.verdict} recovers nothing")
    original = Path(recovery.path).read_text(errors="replace")
    if collapse(recovery.text or "") != collapse(original):
        raise ValueError(
            f"{recovery.path}: the recovered text does not collapse to the "
            "flattened file; refusing to write it")
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    target = into / recovered_name(recovery.path, root)
    if target.exists():
        raise FileExistsError(f"{target} exists; refusing to overwrite a recovery")
    target.write_text(recovery.text or "")
    return target


MANIFEST = "RECOVERY.md"


def render_manifest(recoveries: Sequence[Recovery], root: Path | None = None) -> str:
    """Where each recovered file came from.

    Separate from the files because a recovered original is byte-faithful
    and a header comment would end that. The provenance has to live
    somewhere; it lives here.
    """
    def name(path: Path) -> str:
        try:
            return str(Path(path).resolve().relative_to(Path(root).resolve())) if root else Path(path).name
        except ValueError:
            return Path(path).name

    order = {IDENTICAL: 0, CONTAINED: 1, RELATED: 2, NONE: 3}
    rows = []
    for r in sorted(recoveries, key=lambda r: (order.get(r.verdict, 9), str(r.path))):
        detail = r.label or ""
        if r.verdict == RELATED:
            detail = f"{r.overlap:.0%} identifier overlap -- {detail}"
        source = f"`{r.origin}` {detail}".strip() if r.origin else "--"
        if not r.is_recovered:
            state = "--"
        elif r.parses:
            state = f"{r.lines} lines, parses"
            if r.repairs:
                state += " after " + ", ".join(r.repairs)
        else:
            state = f"{r.lines} lines, does NOT parse"
        rows.append("| `%s` | %s | %s | %s |"
                    % (name(r.path), r.verdict, state, source))

    counts = {v: sum(1 for r in recoveries if r.verdict == v)
              for v in (IDENTICAL, CONTAINED, RELATED, NONE)}
    return "\n".join([
        "# Recovered originals",
        "",
        "Flattening replaces whitespace and nothing else, so a text that",
        "collapses to exactly what a flattened file collapses to IS its",
        "original. `identical` and `contained` are that test passing; both are",
        "written out verbatim, with no header added, because a byte-faithful",
        "original stops being one the moment something is prepended to it.",
        "",
        "`related` is a different draft of the same system. It is named here",
        "and deliberately NOT written: high identifier overlap is not the same",
        "claim, and treating it as one is how a plausible file gets committed",
        "as a real one.",
        "",
        "A recovery that does not parse is reported as such and left alone.",
        "Damage in the corpus is a fact about the corpus, and patching it here",
        "would hide it. The one exception is `nbsp-to-space`, applied only when",
        "it turns a file that does not parse into one that does: an HTML export",
        "writes an indent as `&nbsp;`, which Python rejects outside a string.",
        "",
        "| flattened file | verdict | recovered | source |",
        "| --- | --- | --- | --- |",
        *rows,
        "",
        "%d identical, %d contained, %d related (not written), %d unmatched."
        % (counts[IDENTICAL], counts[CONTAINED], counts[RELATED], counts[NONE]),
        "",
    ])


def write_manifest(recoveries: Sequence[Recovery], into: Path,
                   root: Path | None = None) -> Path:
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    target = into / MANIFEST
    target.write_text(render_manifest(recoveries, root))
    return target
