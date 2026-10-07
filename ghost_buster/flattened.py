"""An unreadable file that is a copy of a readable one.

WHAT unassessable_file LEAVES OPEN

`unassessable_file` reports a `.py` file that will not parse, and says
honestly that every structural detector skipped it. What it cannot say is
whether anything was lost. Very often nothing was: the file is a flattened
copy (line breaks destroyed by a paste through a chat interface) of a file
that still exists, intact, somewhere else in the tree. `duplicate_file`
misses it because the bytes differ; `drifted_copy` misses it because one
side has no syntax tree to read names from.

TOUCHSTONE keeps the specimen: `reference/secure/artifact_1.py` is
`reference/wrapper/artifact_3.py` with every line break removed. MANIFEST
section 3.3: "the same content. A matcher that calls these two unrelated
has failed."

HOW IT MATCHES

Whitespace is exactly what flattening destroys, so the comparison ignores
it. Both files are cut into tokens (identifiers, numbers, single
punctuation characters) and compared as sequences. A pair is reported when
the token similarity is at least SIMILARITY. To keep the cost bounded, a
readable file is only compared if it shares at least SHARED_NAMES of its
distinctive identifiers (four characters or longer) with the unreadable one.

Only the best match per unreadable file is reported: it names the readable
copy to keep.

WHAT IT DOES NOT DO

Decide which copy is canonical by anything but readability, or report a
pair where both files parse (that is `duplicate_file` / `drifted_copy`).
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import corpus
from .schema import Category, Evidence, Finding, Layer, Severity, Status, _portable_path

DETECTOR = "flattened_copy"

#: Measured on TOUCHSTONE's pair: 0.99. Unrelated files sharing a framework
#: vocabulary sit far below; see the calibration record for the corpus.
SIMILARITY = 0.90
#: Fraction of the unreadable file's distinctive identifiers a candidate
#: must share before the (expensive) sequence comparison is run.
SHARED_NAMES = 0.6

_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?|[^\sA-Za-z_\d]")
_NAME = re.compile(r"[A-Za-z_]\w{3,}")


def _tokens(text: str) -> List[str]:
    return _TOKEN.findall(text)


def _names(text: str) -> Set[str]:
    return set(_NAME.findall(text))


def _ratio(a: List[str], b: List[str]) -> float:
    if not a or not b:
        return 0.0
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if matcher.real_quick_ratio() < SIMILARITY or matcher.quick_ratio() < SIMILARITY:
        return 0.0
    return matcher.ratio()


def detect_flattened_copies(files: List[Path]) -> List[Finding]:
    py = sorted(f for f in files if f.suffix == ".py")
    broken = [p for p in py if corpus.failure(p) is not None]
    if not broken:
        return []
    readable: List[Tuple[Path, str, Set[str]]] = []
    for p in py:
        if corpus.parse(p) is None:
            continue
        text = corpus.text(p)
        if text:
            readable.append((p, text, _names(text)))

    out: List[Finding] = []
    for path in broken:
        text = corpus.text(path)
        if not text or not text.strip():
            continue
        names = _names(text)
        if not names:
            continue
        tokens = _tokens(text)
        best: Optional[Tuple[float, Path]] = None
        for other, other_text, other_names in readable:
            if len(names & other_names) < SHARED_NAMES * len(names):
                continue
            r = _ratio(tokens, _tokens(other_text))
            if r >= SIMILARITY and (best is None or r > best[0]):
                best = (r, other)
        if best is None:
            continue
        ratio, twin = best
        out.append(Finding(
            detector=DETECTOR,
            category=Category.DUPLICATION,
            layer=Layer.MECHANICAL,
            severity=Severity.MAJOR,
            status=Status.CONFIRMED,
            summary=(f"{_portable_path(path)} cannot be parsed, and is a copy of "
                     f"{_portable_path(twin)}, which can ({ratio:.0%} of tokens match "
                     f"ignoring whitespace)"),
            evidence=Evidence(file=str(path), related_files=[str(twin)]),
            detail=(
                "The unreadable file is the same content as a readable one with "
                "its formatting destroyed, which is what a paste through a chat "
                "window does to line breaks. Nothing was lost: the readable copy "
                "is the one to keep, and the unreadable one is either a "
                "duplicate to remove or a specimen to keep on purpose."
            ),
            identity_key=_portable_path(twin),
            attributes={"twin": _portable_path(twin), "token_similarity": round(ratio, 3)},
        ))
    return out
