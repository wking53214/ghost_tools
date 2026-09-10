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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

from .schema import Category, Evidence, Finding, Layer, Severity, Status

DISAGREEMENT_DETECTOR = "name_disagreement"
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


def is_test_path(path: Path) -> bool:
    """Shared with deadend.py. Two detectors that each decide for themselves
    what a test file is will eventually disagree, and the disagreement will
    be invisible."""
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
        if is_test_path(path):
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
        if is_test_path(path):
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


# ------------------------------------------------------- one thing, two names

# A name that is a CONSTANT has a role of its own; renaming INGRESS_GUARDS to
# `dependencies` because it is passed as that argument would be wrong. A
# leading underscore is a statement about privacy that a public parameter
# name does not carry. And camelCase in a library that is otherwise
# snake_case means a third-party API, whose parameter names are not ours.
# Each exclusion was observed on 2026-09-10 as a false positive: the
# unfiltered pass reported 271 pairs, of which `dependencies <- INGRESS_GUARDS`,
# `create_fn <- _create` and `parse_all <- parseAll` (pyparsing) were typical.
_CAMEL = re.compile(r"[a-z][A-Z]")


def _renamable(param: str, arg: str) -> bool:
    if param == arg:
        return False
    if param.isupper() or arg.isupper():
        return False
    if param.startswith("_") != arg.startswith("_"):
        return False
    return not (_CAMEL.search(param) or _CAMEL.search(arg))


def _call_name(node: ast.Call) -> str | None:
    """The function a call names, when that is decidable from the call alone.

    `subprocess.run(cmd)` is NOT our `run`. An earlier version returned the
    attribute of any attribute call, and `subprocess.run(cmd, ...)` was
    matched against `PytestRunner.run(self, nodeids)` in another module --
    reported, on 2026-09-10, as `nodeids` and `cmd` being one value under
    two names. They are not the same function, let alone the same value.

    So: a bare name, or a method reached through `self`/`cls`, and nothing
    else. A method called on some other object could be anybody's, and the
    receiver's type is exactly what this layer does not know.
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    if (isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in ("self", "cls")):
        return node.func.attr
    return None


Site = Tuple[str, int]


@dataclass(frozen=True)
class Disagreement:
    """One value under two names, and every line where either name is
    written.

    The line numbers are what separates a report from an annotation. A
    finding says "these two names are one thing"; the annotator has to put
    that sentence on the exact line a reader will be looking at when the
    question occurs to them, which is the signature or the call.
    """

    param: str
    arg: str
    definitions: Tuple[Site, ...]
    call_sites: Tuple[Site, ...]

    @property
    def files(self) -> List[str]:
        return sorted({f for f, _ in self.definitions + self.call_sites})


class _Definitions:
    """Every function the scan saw, and which one a given call names.

    Kept apart from the pass that uses it because resolution is the whole
    correctness argument and deserves to be read on its own. Two rules,
    both measured:

    SAME FILE FIRST, because that is where Python looks.

    THEN THE WHOLE SCAN, but only if the name is defined exactly once in
    it. An earlier version kept the FIRST definition of each name and
    matched every call to it, so `run` in one module supplied the parameter
    names for `run` in another; running this against ghost_tools itself on
    2026-09-10 reported `nodeids` and `cmd` as one value under two names,
    on the strength of `subprocess.run(cmd)`. Ambiguity is not a tie to be
    broken -- it is a reason to say nothing.
    """

    def __init__(self, trees: Sequence[tuple]) -> None:
        self.everywhere: Dict[str, List[Tuple[str, List[str], int]]] = {}
        self.per_file: Dict[str, Dict[str, List[Tuple[List[str], int]]]] = {}
        for path, tree in trees:
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                params = [a.arg for a in node.args.args
                          if a.arg not in ("self", "cls")]
                self.everywhere.setdefault(node.name, []).append(
                    (str(path), params, node.lineno))
                self.per_file.setdefault(str(path), {}).setdefault(
                    node.name, []).append((params, node.lineno))

    def resolve(self, path: Path, name: str) -> Tuple[List[str], Site] | None:
        here = self.per_file.get(str(path), {}).get(name)
        if here is not None:
            if len(here) != 1:
                return None
            params, line = here[0]
            return params, (str(path), line)
        found = self.everywhere.get(name)
        if found is None or len(found) != 1:
            return None
        file, params, line = found[0]
        return params, (file, line)


def find_name_disagreements(files: Sequence[Path]) -> List[Disagreement]:
    """One value carried across a seam under two different names.

    The complaint this answers is the one every SQL join produces: a column
    called `customer_id` on one side and `recipient_id` on the other, the
    same key wearing two names, and nothing in either schema saying so.
    Measured on 2026-09-10 across a 37-repository library, the same thing
    happens between repositories: `log_odds_value` is only ever passed
    `raw_odds`, `obligation_ids` is only ever passed `needed_ids`. 63
    pairs, 21 of them spanning more than one repository.

    ONLY 1:1, WHICH IS THE WHOLE SAFETY ARGUMENT

    A parameter that receives several different variables is not a naming
    disagreement -- it is a parameter doing its job. A variable passed to
    several different parameters is the same. Renaming either would collide
    with a name that is legitimately in use elsewhere. A bijection is the
    one case where the two names provably denote one thing, and where
    substituting one for the other cannot capture anything.
    """
    files = [Path(f) for f in files]
    trees = [(p, t) for p in files if not is_test_path(p)
             for t in (_parse(p),) if t is not None]
    known = _Definitions(trees)

    to_arg: Dict[str, Counter] = {}
    to_param: Dict[str, Counter] = {}
    call_sites: Dict[tuple, Set[Site]] = {}
    declared: Dict[tuple, Set[Site]] = {}

    def note(param: str, arg: str, definition: Site, site: Site) -> None:
        to_arg.setdefault(param, Counter())[arg] += 1
        to_param.setdefault(arg, Counter())[param] += 1
        call_sites.setdefault((param, arg), set()).add(site)
        declared.setdefault((param, arg), set()).add(definition)

    for path, tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = _call_name(node)
            if not called:
                continue
            resolved = known.resolve(path, called)
            # A name this scan cannot pin to exactly one definition belongs
            # to somebody else, or to two of ours at once. Either way its
            # parameter names are not ours to reconcile.
            if resolved is None:
                continue
            params, definition = resolved
            site = (str(path), node.lineno)
            for kw in node.keywords:
                if kw.arg and isinstance(kw.value, ast.Name):
                    note(kw.arg, kw.value.id, definition, site)
            for index, arg in enumerate(node.args):
                if isinstance(arg, ast.Name) and index < len(params):
                    note(params[index], arg.id, definition, site)

    out: List[Disagreement] = []
    for param, args in sorted(to_arg.items()):
        if len(args) != 1:
            continue
        arg = next(iter(args))
        if not _renamable(param, arg) or len(to_param[arg]) != 1:
            continue
        key = (param, arg)
        out.append(Disagreement(
            param=param,
            arg=arg,
            definitions=tuple(sorted(declared[key])),
            call_sites=tuple(sorted(call_sites[key])),
        ))
    return out


def detect_name_disagreements(files: Sequence[Path]) -> List[Finding]:
    """The 1:1 disagreements above, as findings.

    Reports; does not rename. A cross-repository rename touches call sites
    and tests in trees this scan was never asked to write to.
    `--annotate-names` is the one path that writes into a scanned tree, it is
    opt-in, and it writes comments and a README table rather than code. That
    it is the ONLY one is checked, not asserted: see
    Tests/test_tree_immutability.py.
    """
    findings: List[Finding] = []
    for d in find_name_disagreements(files):
        where = sorted({f for f, _ in d.call_sites})
        sites = len(d.call_sites)
        findings.append(Finding(
            detector=DISAGREEMENT_DETECTOR,
            category=Category.NAMING,
            layer=Layer.MECHANICAL,
            severity=Severity.MINOR,
            status=Status.CONFIRMED,
            summary=(f"`{d.param}` and `{d.arg}` are one value under two names, "
                     f"across {len(where)} file(s)"),
            detail=(
                f"The parameter `{d.param}` is only ever passed a variable named "
                f"`{d.arg}`, and `{d.arg}` is only ever passed to `{d.param}` -- "
                f"{sites} call site(s) in {', '.join(Path(w).name for w in where[:4])}"
                + (f" (+{len(where) - 4} more)" if len(where) > 4 else "") + ".\n"
                "A one-to-one correspondence is the only case where two names "
                "provably denote the same thing: a parameter taking several "
                "variables is doing its job, and renaming it would collide with "
                "a name legitimately in use. Which of the two should win is "
                "yours to pick -- the parameter is the contract, the variable "
                "is the caller's local, and neither is automatically right."
            ),
            evidence=Evidence(
                file=(d.definitions[0][0] if d.definitions else where[0]),
                line_start=(d.definitions[0][1] if d.definitions else None),
                related_files=d.files,
            ),
        ))
    return findings
