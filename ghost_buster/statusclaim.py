"""A status label a reader will trust: "production ready", "battle-tested", "RL Ready".

THE FAILURE THIS NAMES

Documentation that says what a project IS, in words nobody has to back:
"production-ready", "enterprise-grade", "fully tested", "100% coverage", or a
capitalised "Something Ready" badge in a feature list. Recorded in this
project's own history: a README that claimed "RL Ready" and "Multi-AI
Orchestration Ready" for things that had not shipped, and docstrings in
marketing language the code behind them did not match. The reader takes the
label as a verdict somebody reached. Nobody did.

This detector does not decide whether the label is true. It cannot: "ready"
is a judgement about the world. What it can do, mechanically, is find every
such label and hand it over for independent re-verification, which is the
rule this project's own notes arrived at: anything labelled production ready
or hardened is re-verified, never taken.

WHAT IS REPORTED, AND WHAT IS NOT

Reported, in `.md` files, outside code fences and backticks:

    production[- ]ready / production[- ]grade / enterprise[- ]grade
    battle[- ]tested
    fully tested / fully validated / fully hardened / security[- ]hardened
    100% coverage / 100% test coverage
    <Title Case Words> Ready          "RL Ready", "Multi-AI Orchestration Ready"

Not reported:

    * a changelog, history or release notes file: it records what was said
      at the time, and a correction there would rewrite history;
    * a negated claim ("not production ready", "far from battle-tested",
      "without 100% coverage"): the sentence is honest about a limit;
    * a quoted, attributed or discussed claim ("claimed", "said", "reported",
      inside quotation marks, or followed by "claim not backed", "unsupported",
      "re-verify" and the like): the document is reporting someone's words, or
      a critic is naming the claim. Burnish's generated README section does
      exactly that, and a scanner that read the critic's note as a fresh claim
      would make every finish introduce a new finding;
    * a bare "hardened": "hardened against X" usually names a mechanism, and
      the first scan of this project's own notes found only that use.

The finding is CONFIRMED in what it states: the phrase is there, at that line.
Its detail says how many test files the scan saw beside the document, which
is the one piece of backing the tree can offer mechanically, and leaves the
verdict to a person. MINOR, because the label is not itself a defect; it is a
claim awaiting its evidence.

Measured 2026-10-14 on the seven circuit repositories: 1 candidate line, in a
changelog ("Every git command is hardened"), excluded on both rules.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Sequence

from .naming import is_test_path
from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "unverified_status_claim"

_CLAIMS = (
    ("production_ready", re.compile(r"\bproduction[- ](?:ready|grade)\b", re.IGNORECASE)),
    ("enterprise_grade", re.compile(r"\benterprise[- ]grade\b", re.IGNORECASE)),
    ("battle_tested", re.compile(r"\bbattle[- ]tested\b", re.IGNORECASE)),
    ("fully_tested", re.compile(r"\bfully[- ](?:tested|validated|hardened)\b|\bsecurity[- ]hardened\b",
                                re.IGNORECASE)),
    ("full_coverage", re.compile(r"\b100\s?%\s+(?:test\s+)?coverage\b", re.IGNORECASE)),
    ("ready_badge", re.compile(r"\b(?:[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*){0,3})\s+Ready\b")),
)
_NEGATED = re.compile(
    r"\b(?:not|never|isn't|aren't|wasn't|weren't|no|nor|neither|without|far from|nowhere near|"
    r"before (?:it is|being)|until|unless)\b[^.;:!?]{0,40}$", re.IGNORECASE)
_ATTRIBUTED = re.compile(r"\b(?:claimed|claims|said|says|reported|reports|described as|calls? itself)\b"
                         r"[^.;:!?]{0,40}$", re.IGNORECASE)
#: What follows a phrase that is being discussed rather than asserted: a critic's note, a review, a
#: finding. Burnish writes `'Production-ready': claim not backed by any measurement`; that is a report.
_DISCUSSED_AFTER = re.compile(r"^.{0,60}?\b(?:claim(?:ed|s)?\b|not backed|unsupported|unverified|unbacked|"
                              r"re-?verif|a status label|overclaim)", re.IGNORECASE)
_QUOTE_OPEN = "\"'“‘`"
_QUOTE_CLOSE = "\"'”’`"
_HISTORY = ("CHANGELOG", "HISTORY", "NEWS", "RELEASES")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def _is_history(path: Path) -> bool:
    return path.name.upper().startswith(_HISTORY)


def _strip_code_spans(line: str) -> str:
    """The line with backtick spans blanked, so a phrase inside code is not a claim."""
    return re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)


#: Characters that change how a line looks to a scanner and not to a reader: zero-width joiners
#: and spaces, the soft hyphen, the byte order mark; plus Markdown emphasis markers.
_INVISIBLE = re.compile("[​‌‍⁠﻿­*_]")


def _as_read(line: str) -> str:
    """The line as a reader sees it: compatibility-normalised (full-width letters, ligatures),
    invisible characters and emphasis markers removed, non-breaking spaces and hyphens made plain.

    Red-teamed 2026-10-14: `Produc­tion ready`, `Production ready`, `**Production** ready`
    and full-width letters all read as the claim and all slipped past the plain pattern."""
    text = unicodedata.normalize("NFKC", line)
    text = _INVISIBLE.sub("", text)
    return text.replace(" ", " ").replace("‑", "-").replace("‐", "-")


def _quoted(line: str, start: int, end: int) -> bool:
    """Inside double quotes, or a phrase wrapped in quotes of its own (`'Production-ready'`)."""
    before = line[:start]
    if (before.count('"') % 2 == 1) or (before.count("“") > before.count("”")):
        return True
    wrapped = start > 0 and line[start - 1] in _QUOTE_OPEN and end < len(line) and line[end] in _QUOTE_CLOSE
    return wrapped


def _claim_on(line: str) -> Optional[tuple]:
    """(kind, phrase, start) for the first reportable claim on a prose line, else None."""
    text = _as_read(_strip_code_spans(line))
    for kind, pattern in _CLAIMS:
        for m in pattern.finditer(text):
            before, after = text[:m.start()], text[m.end():]
            if _NEGATED.search(before) or _ATTRIBUTED.search(before) or _quoted(text, m.start(), m.end()):
                continue
            if _DISCUSSED_AFTER.search(after):
                continue
            if kind == "ready_badge" and m.group(0).strip().lower() in ("get ready", "be ready", "is ready",
                                                                         "are ready", "when ready", "ready"):
                continue
            return kind, m.group(0).strip(), m.start()
    return None


def _prose_lines(text: str):
    """(line number, line) for every line outside a fenced code block."""
    fence: Optional[str] = None
    for number, line in enumerate(text.splitlines(), 1):
        m = _FENCE.match(line)
        if fence is None and m:
            fence = m.group(1)[0]
            continue
        if fence is not None:
            if m and m.group(1)[0] == fence:
                fence = None
            continue
        yield number, line


def detect_status_claims(files: Sequence[Path]) -> List[Finding]:
    paths = [Path(f) for f in files]
    test_files = sum(1 for p in paths if p.suffix == ".py" and (is_test_path(p) or p.name.endswith("_test.py")))
    findings: List[Finding] = []
    for path in paths:
        if path.suffix.lower() != ".md" or _is_history(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in _prose_lines(text):
            hit = _claim_on(line)
            if hit is None:
                continue
            kind, phrase, _ = hit
            findings.append(Finding(
                detector=DETECTOR,
                category=Category.DOC_DRIFT,
                layer=Layer.MECHANICAL,
                severity=Severity.MINOR,
                status=Status.CONFIRMED,
                summary=f"{path.name}:{number} says \"{phrase}\", a status label nothing in the tree is read to back",
                detail=(
                    f"A reader takes \"{phrase}\" as a verdict somebody reached. This scan reads no evidence for "
                    f"it and does not decide whether it is true; it hands the label over to be re-verified "
                    f"independently. The one thing the tree offers mechanically: the scan saw {test_files} test "
                    f"file(s) beside this document. A label like this with no suite behind it is the shape "
                    f"recorded in this project's history (a README claiming readiness for things that had not "
                    f"shipped)."
                ),
                # The label is the defect; the line it sits on moves every time the document is edited
                # above it. Identity is the label, so a README edit elsewhere is not a new finding.
                identity_key=f"{kind}: {phrase}",
                evidence=Evidence(file=str(path), line_start=number, snippet=line.strip()[:200]),
                attributes={"kind": kind, "phrase": phrase, "test_files_seen": str(test_files)},
            ))
    return findings
