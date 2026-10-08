"""The hammer. Every file read once, parsed once, under one policy.

WHY THIS EXISTS

Measured 2026-09-11 against ghost_tools itself: a single `run_all` over 112
files called `ast.parse` 1,064 times -- 9.5 parses per file -- and spent 52%
of its wall clock inside the parser. Eighteen detectors each brought their
own mallet.

The speed is the smaller reason. The larger one is that there were SIX
implementations of "turn a file into a tree" and they disagreed. Three read
with `errors="replace"`, three with `encoding="utf-8"`. A file with one
invalid byte was therefore analysed by three detectors and invisible to
fifteen, and nothing in the report said so. `mechanical._parse` did not catch
OSError, so an unreadable file crashed the run there while the others
skipped it silently. That is not isolation; it is the tool quietly holding
two opinions about what its own corpus is.

The argument for one shared reading is the one already made for
`is_test_path`: two components that each decide for themselves what a thing
is will eventually disagree, and the disagreement will be invisible.

ONE POLICY, STATED

  * Bytes are read, not text. The encoding is whatever PEP 263 says it is --
    a coding cookie if present, UTF-8 otherwise -- detected with
    `tokenize.detect_encoding`, the same rule the interpreter uses. A file
    that is not valid in its declared encoding is not valid Python source,
    and is recorded as such rather than decoded with replacement characters
    and reasoned about as if it were.
  * The bytes are what gets parsed, so the cookie is honoured there too.
  * A file that cannot be read or parsed is a FACT about the scan, held
    here, reported once by `unassessable_file`, and skipped identically by
    every detector. Not visible to some and invisible to others.

FACTS, NOT CONCLUSIONS

This module hands out bytes, text and trees. It never hands out findings.
Sharing a fact means one truth; sharing a conclusion means one detector's
error becomes eighteen findings and nobody can tell which tool was wrong.

THE TREE IS SHARED, SO THE TREE IS READ-ONLY

A detector that mutates the tree it was handed corrupts every detector
after it. That is a contract, and it is CHECKED: Tests/test_corpus.py runs
every detector and then compares each cached tree against a fresh parse.
The one component that legitimately mutates trees -- the mutation engine --
asks for `fresh()` and gets an uncached copy of its own.

The cache is validated by (mtime_ns, size), so a file that changes between
scans is re-read, and `reset()` empties it between runs.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

Stamp = Tuple[int, int]


@dataclass(frozen=True)
class Source:
    """One file, as the scan will see it. Every field is evidence."""

    path: Path
    text: Optional[str]
    tree: Optional[ast.Module]
    failure: Optional[str]
    stamp: Optional[Stamp]

    @property
    def parsed(self) -> bool:
        return self.tree is not None


_CACHE: Dict[Path, Source] = {}
_STATS = {"reads": 0, "hits": 0}


def _stamp(path: Path) -> Optional[Stamp]:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _read(path: Path) -> Source:
    """The one policy. Every failure becomes a reason, never an exception."""
    stamp = _stamp(path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        return Source(path, None, None, f"{type(e).__name__}: {e}", stamp)

    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        text = raw.decode(encoding)
    except (SyntaxError, LookupError) as e:
        return Source(path, None, None, f"encoding: {e}", stamp)
    except UnicodeDecodeError as e:
        return Source(path, None, None,
                      f"UnicodeDecodeError: not valid {e.encoding} at byte {e.start}", stamp)

    try:
        tree = ast.parse(raw, filename=str(path))
    except SyntaxError as e:
        line = f" at line {e.lineno}" if e.lineno else ""
        return Source(path, text, None, f"SyntaxError{line}: {e.msg}", stamp)
    except ValueError as e:                  # null bytes
        return Source(path, text, None, f"ValueError: {e}", stamp)
    return Source(path, text, tree, None, stamp)


def read(path: Path) -> Source:
    """The file, from the cache if it has not changed since it was read."""
    path = Path(path)
    _STATS["reads"] += 1
    cached = _CACHE.get(path)
    if cached is not None and cached.stamp == _stamp(path):
        _STATS["hits"] += 1
        return cached
    source = _read(path)
    _CACHE[path] = source
    return source


def parse(path: Path) -> Optional[ast.Module]:
    """The tree, shared and read-only. None means the file could not be
    assessed -- see `failure` for why -- and never means it is clean."""
    return read(path).tree


def text(path: Path) -> Optional[str]:
    return read(path).text


def failure(path: Path) -> Optional[str]:
    return read(path).failure


def fresh(path: Path) -> Optional[ast.Module]:
    """An UNCACHED tree, for the one caller that will mutate it.

    Not a deepcopy of the cached tree: a fresh parse is cheaper than a deep
    copy of a large module and cannot inherit a mutation somebody else made
    by mistake."""
    return _read(path).tree


def unparsed(files: Iterable[Path]) -> List[Tuple[Path, str]]:
    """Every file in `files` the scan could not assess, with the reason.
    This is the blind-spot list, and it is the same list for every
    detector."""
    out = []
    for path in files:
        source = read(path)
        if source.failure is not None:
            out.append((source.path, source.failure))
    return out


def reset() -> None:
    _CACHE.clear()
    _STATS["reads"] = 0
    _STATS["hits"] = 0


def stats() -> Dict[str, int]:
    """How much work the cache saved. `hits / reads` is the share of parse
    requests that did not touch the parser."""
    return dict(_STATS, cached=len(_CACHE))
