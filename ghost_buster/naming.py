"""Names that describe where the code came from instead of what it does.

Two questions here, and only two, because only two are decidable from the
code itself.

WHAT THIS DOES NOT ASK

Whether a name is GOOD. `route_call` versus `handle` versus `dispatch` is a
judgement about English and about a reader who is not present, and a
mechanical layer that renders judgements as CONFIRMED findings is lying
about what it knows. Measured 2026-09-10 across a 37-repository library, a
detector for "prose-shaped" identifiers returned 1,108 hits, of which 1,099
were test names in this shape:

    test_a_misspelled_event_type_cannot_launder_the_same_decision

which is a deliberate convention and a good one. The nine that remained
were mostly fine too. The check was not built.

WHAT IS DECIDABLE

  vestigial_domain_name  a module that sits below a domain seam, still
                         carrying the vocabulary of ONE domain in its
                         identifiers. Decidable because the seam declares
                         the domains, so "this word belongs to pediatrics
                         and not to the engine" is read off the cassettes
                         rather than guessed.

  placeholder_name       `tmp`, `_old`, `_v2`, `_final`. Names that were
                         meant to be temporary and were not, matched by
                         literal and never by shape.

Both are MINOR. A name is not a defect; it is a cost paid by whoever reads
the code next, and rating it alongside an executed f-string SQL query is how
a report teaches its reader to skim.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

from .schema import Category, Evidence, Finding, Layer, Severity, Status

VESTIGIAL_DETECTOR = "vestigial_domain_name"
PLACEHOLDER_DETECTOR = "placeholder_name"

# A cassette is a domain plugged into a domain-agnostic core. Two of them is
# the minimum that makes this decidable: with one, every word it uses looks
# domain-specific and the engine's own vocabulary is indistinguishable from
# the domain's.
MINIMUM_CASSETTES = 2

# Names that were always meant to be temporary. Matched as whole tokens or
# as a suffix, never as a substring: `template` is not `temp`, and
# `threshold` is not `old`.
_PLACEHOLDER_EXACT = frozenset({
    "tmp", "foo", "bar_baz", "baz", "qux", "asdf", "stuff", "junk",
    "data2", "test1", "thing1", "untitled",
})
_PLACEHOLDER_SUFFIX = ("_old", "_new", "_final", "_copy", "_tmp", "_bak",
                       "_v2", "_v3", "_2", "_3")
# DELIBERATELY ABSENT: `temp` and `bar`. Both are real domain words --
# temperature is a vital sign, and a bar is a unit of pressure that the
# industrial cassette uses. A placeholder list that flags a measurement is
# worse than no list.


# Words that survive the generic-Python filter only because this tool does
# not happen to use them, and which no domain owns. Every entry was observed
# as a false positive on 2026-09-10 against observe-perceive's two
# cassettes; none is here on suspicion. Adding to this list is a claim about
# a word, so it should cost a measurement.
_ORDINARY_ENGLISH = frozenset({
    "triggered",      # industrial cassette; also a core concept (triggered_rules)
    "faults",         # industrial cassette; also core (adversarial_sensor_faults)
    "rising",         # a direction, not a domain
    "ordered",        # a property of a sequence
    "unacceptable",   # ISO 10816 uses it; so does English
    "temp",           # a temporary, and also a temperature: owned by neither
    "reading",        # what every sensor produces, in every domain
})


def _identifiers(tree: ast.AST) -> Set[str]:
    """Every name a module defines, binds, takes as an argument, or reads
    as an attribute. Attributes are included because `self._patient_kalman`
    is exactly the kind of name this is looking for and it is never a
    Name node."""
    found: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            found.add(node.id)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


_SPLIT = re.compile(r"[_\W]+|(?<=[a-z0-9])(?=[A-Z])")


def _words(name: str) -> Set[str]:
    """snake_case and CamelCase both, lowercased, short fragments dropped."""
    return {w.lower() for w in _SPLIT.split(name) if len(w) > 2}


# Directory names that mean "these are tests". Compared WHOLE, never as a
# substring: `"test" in parent.name` also matches `latest/`, `attestation/`
# and -- found the moment this had tests of its own -- pytest's own tmp_path,
# which is named after the test using it. A skip rule that swallows the
# fixture directory makes every test of the detector vacuous.
_TEST_DIRS = frozenset({"test", "tests"})


def _is_test(path: Path) -> bool:
    return path.name.startswith("test_") or path.parent.name.lower() in _TEST_DIRS


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return None


def _vocabulary(paths: Sequence[Path]) -> Counter:
    counts: Counter = Counter()
    for path in paths:
        tree = _parse(path)
        if tree is None:
            continue
        for name in _identifiers(tree):
            counts.update(_words(name))
    return counts


def _generic_vocabulary() -> Set[str]:
    """Words that are just Python, taken from this tool's own source.

    A reference corpus has to be unrelated to whatever is being scanned, and
    ghost_buster is unrelated to every domain it will ever look at. Measured
    2026-09-10: this filter cut the finding count from 78 to 31 by removing
    `critical`, `map`, `min`, `load`, `add` and `addHandler` -- generic words
    that happened to appear in one cassette and not the other.

    Scanning ghost_buster ITSELF makes this vacuous, since every word is
    then generic and nothing is reported. That is the safe direction to
    fail, and it is why this is not the only signal.
    """
    here = Path(__file__).resolve().parent
    return set(_vocabulary(sorted(here.glob("*.py"))))


def find_cassettes(files: Sequence[Path]) -> Tuple[List[Path], Path | None]:
    """(cassette modules, the contract they implement).

    The convention this reads is `<domain>_cassette.py` beside a
    `cassette.py`. It is a convention and not a law, so a tree that does not
    use it produces no cassettes and the detector abstains rather than
    inventing a seam.
    """
    cassettes = sorted(p for p in files if p.name.endswith("_cassette.py"))
    contract = next((p for p in files if p.name == "cassette.py"), None)
    return cassettes, contract


def domain_vocabularies(cassettes: Sequence[Path], contract: Path | None) -> Dict[str, Set[str]]:
    """The words that belong to ONE domain and to nothing else.

    A word qualifies when it appears in exactly one cassette, is absent from
    the contract, and is absent from both generic Python and ordinary
    English.

    A FREQUENCY THRESHOLD WAS TRIED HERE AND REMOVED. Requiring a word to be
    used more than once in its cassette looked like the way to drop
    `triggered` and `faults`, and measurement killed it: `patient`,
    `pediatric`, `oxygen`, `respiratory`, `saturation` and `heart` each
    appear EXACTLY ONCE in the pediatric cassette -- a cassette names each
    channel once and moves on -- while `bearing` and `vibration` appear
    twice in the industrial one. The threshold removed every real pediatric
    term and kept the noise. Frequency does not separate a domain's
    vocabulary from a word it happens to use.
    """
    per_cassette = {p.stem: _vocabulary([p]) for p in cassettes}
    contract_words = set(_vocabulary([contract])) if contract else set()
    generic = _generic_vocabulary()

    seen_in = Counter()
    for words in per_cassette.values():
        seen_in.update(set(words))

    out: Dict[str, Set[str]] = {}
    for name, words in per_cassette.items():
        out[name] = {
            word for word, uses in words.items()
            if seen_in[word] == 1
            and word not in contract_words and word not in generic
            and word not in _ORDINARY_ENGLISH
        }
    return out


def detect_vestigial_domain_names(files: Sequence[Path]) -> List[Finding]:
    """Domain vocabulary surviving in code that claims to be domain-agnostic.

    Found by hand on 2026-09-10 in observe-perceive and recorded in its own
    commit as deferred work: `_patient_kalman`, `_patient_policies` and
    `_touch_patient` in an engine whose domain had just been extracted into
    a cassette. The VALUES flowing through them come from the cassette, so
    the behaviour is right and only the name is wrong -- which is precisely
    why nothing else catches it.

    ABSTAINS, rather than guessing, when there is no seam: fewer than two
    cassettes means domain words cannot be told from the engine's own.
    """
    files = [Path(f) for f in files]
    cassettes, contract = find_cassettes(files)
    if len(cassettes) < MINIMUM_CASSETTES:
        return []

    vocab = domain_vocabularies(cassettes, contract)
    if not any(vocab.values()):
        return []

    cassette_names = {p.name for p in cassettes}
    findings: List[Finding] = []
    for path in files:
        if path.name in cassette_names or path.name == "cassette.py":
            continue
        if _is_test(path):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        by_domain: Dict[str, Set[str]] = {}
        for name in _identifiers(tree):
            words = _words(name)
            for domain, terms in vocab.items():
                overlap = words & terms
                if overlap:
                    by_domain.setdefault(domain, set()).add(name)
        for domain, names in sorted(by_domain.items()):
            shown = ", ".join(sorted(names)[:6])
            more = f" (+{len(names) - 6} more)" if len(names) > 6 else ""
            label = domain.replace("_cassette", "")
            findings.append(Finding(
                detector=VESTIGIAL_DETECTOR,
                category=Category.NAMING,
                layer=Layer.MECHANICAL,
                severity=Severity.MINOR,
                status=Status.CONFIRMED,
                summary=(f"{path.name} carries `{label}` vocabulary in "
                         f"{len(names)} identifier(s), below a cassette seam"),
                detail=(
                    f"{shown}{more}.\n"
                    f"These words appear in the `{label}` cassette and in no "
                    "other, in neither the cassette contract nor generic "
                    "Python. The values flowing through these names come from "
                    "whichever cassette is installed, so the behaviour is "
                    "domain-agnostic and only the naming is not -- which is "
                    "why no test catches it and why it is MINOR rather than a "
                    "defect. Renaming touches call sites; it is a change of "
                    "its own, not a drive-by."
                ),
                evidence=Evidence(file=str(path)),
            ))
    return findings


def detect_placeholder_names(files: Sequence[Path]) -> List[Finding]:
    """Names that were meant to be temporary and were not.

    Matched by literal and by suffix, never by substring: `template` is not
    `temp`, `threshold` is not `old`. `temp` and `bar` are deliberately not
    on the list -- temperature is a vital sign and a bar is a unit of
    pressure, and a check that flags a measurement is worse than no check.
    """
    findings: List[Finding] = []
    for path in (Path(f) for f in files):
        if _is_test(path):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        hits: Set[str] = set()
        for name in _identifiers(tree):
            lowered = name.lower()
            if lowered in _PLACEHOLDER_EXACT or lowered.endswith(_PLACEHOLDER_SUFFIX):
                hits.add(name)
        if not hits:
            continue
        shown = ", ".join(sorted(hits)[:8])
        more = f" (+{len(hits) - 8} more)" if len(hits) > 8 else ""
        findings.append(Finding(
            detector=PLACEHOLDER_DETECTOR,
            category=Category.NAMING,
            layer=Layer.MECHANICAL,
            severity=Severity.MINOR,
            status=Status.CONFIRMED,
            summary=f"{path.name} holds {len(hits)} placeholder or versioned name(s)",
            detail=(
                f"{shown}{more}.\n"
                "An `_old` beside a `_new` is two implementations sharing a "
                "scope, and a `_v2` is a decision nobody came back to. Neither "
                "is wrong on its own, which is why this is MINOR: it names "
                "where the code remembers being written rather than what it "
                "does."
            ),
            evidence=Evidence(file=str(path)),
        ))
    return findings
