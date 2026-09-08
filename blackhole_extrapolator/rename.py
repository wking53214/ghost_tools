"""rename.py -- a name nobody defines that something defines under another name.

Jon is looking for Sally. Sally now goes by Karen. Every detector in this
package keys on the literal identifier, so Jon's call is a never-built void
and Karen's definition is unrelated to it. Found on TOUCHSTONE, 2026-09-08:
three superseded specimens call `initialize_hybrid_cluster(node_count=3)`
and unpack three values from it; the flattened quorum file beside them
declares `initialize_network_cluster(node_count: int, ...)` returning a
three-tuple whose elements flow straight into the next call's parameters.

This compares how callers use an undefined name against every signature
the tree still has (parsing files, and the headers read back from
flattened ones) on dimensions that do not involve the name:

    keywords   a keyword the caller passes is a parameter of the candidate
    unpack     the caller unpacks N values and the candidate returns an N-tuple
    flow       an unpacked value is passed to another known signature whose
               parameter has the same annotation as the tuple element
    members    an attribute the caller uses on the result is a method the
               candidate class defines
    tokens     the two names share a word (`initialize`, `cluster`)

Arity compatibility is a gate, not a dimension: most functions take one
argument. A candidate is reported when at least two dimensions match and at
least one of them is not the name. It is reported as a candidate, in the
same void as the undefined name, and the void says the match is by shape.
Nothing is merged, because a match by shape is a hypothesis and merging it
would be the confident forgery this package exists to refuse.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .schema import EvidenceKind, NegativeEvidence

_SELF = ("self", "cls")
_TRIVIAL_TOKENS = {"get", "set", "run", "do", "make", "new", "the", "a", "of", "to"}


@dataclass
class Signature:
    name: str
    file: str
    params: list[tuple[str, str, bool]]      # (name, annotation, has_default)
    returns: str = ""
    is_class: bool = False
    members: set[str] = field(default_factory=set)
    variadic: bool = False

    @property
    def required(self) -> int:
        return sum(1 for _, _, has_default in self.params if not has_default)

    @property
    def return_elements(self) -> list[str]:
        m = re.match(r"^\s*(?:typing\.)?[Tt]uple\[(.*)\]\s*$", self.returns.strip())
        return [_norm(p) for p in _split_top(m.group(1))] if m else []

    def render(self) -> str:
        params = ", ".join(n + (f": {a}" if a else "") + (" = ..." if d else "")
                           for n, a, d in self.params)
        return f"{self.name}({params})" + (f" -> {self.returns}" if self.returns else "")


def _norm(text: str) -> str:
    return " ".join(text.split())


def _split_top(text: str) -> list[str]:
    """Split on commas outside brackets."""
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur))
    return [p.strip() for p in out]


def _parse_params(text: str) -> tuple[list[tuple[str, str, bool]], bool]:
    params: list[tuple[str, str, bool]] = []
    variadic = False
    for raw in _split_top(text):
        if not raw or raw in ("/", "*"):
            continue
        if raw.startswith("**"):
            continue
        if raw.startswith("*"):
            variadic = True
            continue
        has_default = "=" in _strip_brackets(raw)
        head = raw.split("=", 1)[0]
        name, _, annotation = head.partition(":")
        name = name.strip()
        if name in _SELF or not name:
            continue
        params.append((name, _norm(annotation), has_default))
    return params, variadic


def _strip_brackets(text: str) -> str:
    out, depth = [], 0
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


_DEBRIS_LINE = re.compile(r"^(?:class (\w+)|([\w.]+)\((.*)\)(?:\s*->\s*(.+))?)$")


def signatures_from_debris(evidence: Iterable[NegativeEvidence]) -> list[Signature]:
    """Signatures read back from DEBRIS_STRUCTURE detail lines."""
    sigs: dict[tuple[str, str], Signature] = {}
    for item in evidence:
        if item.kind is not EvidenceKind.DEBRIS_STRUCTURE:
            continue
        for line in item.detail.splitlines()[1:]:
            m = _DEBRIS_LINE.match(line.strip())
            if not m:
                continue
            if m.group(1):
                sigs.setdefault((item.file, m.group(1)),
                                Signature(m.group(1), item.file, [], is_class=True))
                continue
            qual, params_text, returns = m.group(2), m.group(3), m.group(4) or ""
            params, variadic = _parse_params(params_text)
            if "." in qual:
                owner, method = qual.rsplit(".", 1)
                cls = sigs.setdefault((item.file, owner),
                                      Signature(owner, item.file, [], is_class=True))
                cls.members.add(method)
                if method == "__init__":
                    cls.params, cls.variadic = params, variadic
                continue
            sigs.setdefault((item.file, qual),
                            Signature(qual, item.file, params, _norm(returns), variadic=variadic))
    return list(sigs.values())


def signatures_from_tree(path: Path, tree: ast.Module) -> list[Signature]:
    """Top-level functions and classes a parsing module defines."""
    out: list[Signature] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params, variadic = _params_from_args(node.args)
            out.append(Signature(node.name, str(path), params,
                                 _norm(ast.unparse(node.returns)) if node.returns else "",
                                 variadic=variadic))
        elif isinstance(node, ast.ClassDef):
            sig = Signature(node.name, str(path), [], is_class=True)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig.members.add(child.name)
                    if child.name == "__init__":
                        sig.params, sig.variadic = _params_from_args(child.args)
            out.append(sig)
    return out


def _params_from_args(args: ast.arguments) -> tuple[list[tuple[str, str, bool]], bool]:
    positional = list(args.posonlyargs) + list(args.args)
    defaults_start = len(positional) - len(args.defaults)
    params = []
    for i, a in enumerate(positional):
        if a.arg in _SELF and i == 0:
            continue
        params.append((a.arg, _norm(ast.unparse(a.annotation)) if a.annotation else "",
                       i >= defaults_start))
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        params.append((a.arg, _norm(ast.unparse(a.annotation)) if a.annotation else "", d is not None))
    return params, args.vararg is not None


@dataclass
class Usage:
    """How one module uses an undefined name."""
    name: str
    file: str
    line: int
    positional: int = 0
    keywords: list[str] = field(default_factory=list)
    unpacked: list[str] = field(default_factory=list)     # variables, in order
    flows: list[tuple[int, str, str]] = field(default_factory=list)  # (index, consumer, param or position)
    members: set[str] = field(default_factory=set)
    star_args: bool = False


def usage_of(tree: ast.Module, name: str, file: str, known: dict[str, Signature]) -> Usage | None:
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name]
    if not calls:
        return None
    call = calls[0]
    usage = Usage(name, file, call.lineno,
                  positional=sum(1 for a in call.args if not isinstance(a, ast.Starred)),
                  keywords=[k.arg for k in call.keywords if k.arg],
                  star_args=any(isinstance(a, ast.Starred) for a in call.args)
                  or any(k.arg is None for k in call.keywords))
    results: dict[str, int] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and node.value in calls and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if isinstance(target, ast.Tuple) and all(isinstance(e, ast.Name) for e in target.elts):
            usage.unpacked = [e.id for e in target.elts]
            results.update({e.id: i for i, e in enumerate(target.elts)})
        elif isinstance(target, ast.Name):
            results[target.id] = -1
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id in results and results[node.value.id] == -1:
            usage.members.add(node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in known:
            consumer = known[node.func.id]
            for pos, arg in enumerate(node.args):
                if isinstance(arg, ast.Name) and arg.id in results and pos < len(consumer.params):
                    usage.flows.append((results[arg.id], consumer.name, consumer.params[pos][0]))
            for kw in node.keywords:
                if isinstance(kw.value, ast.Name) and kw.value.id in results and kw.arg:
                    usage.flows.append((results[kw.value.id], consumer.name, kw.arg))
    return usage


def _tokens(name: str) -> set[str]:
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower().split("_")
    return {p for p in parts if len(p) >= 3 and p not in _TRIVIAL_TOKENS}


def match(usage: Usage, candidate: Signature, known: dict[str, Signature]) -> list[str]:
    """The dimensions on which `candidate` fits how `usage` calls the name."""
    given = usage.positional + len(usage.keywords)
    if not usage.star_args and not candidate.variadic:
        if given < candidate.required or given > len(candidate.params):
            return []
    if usage.star_args and given > len(candidate.params) and not candidate.variadic:
        return []
    names = {p for p, _, _ in candidate.params}
    reasons: list[str] = []
    hit = [k for k in usage.keywords if k in names]
    if hit:
        reasons.append(f"keyword{'s' if len(hit) > 1 else ''} {hit} are parameters")
    elements = candidate.return_elements
    if len(usage.unpacked) >= 2 and len(elements) == len(usage.unpacked):
        reasons.append(f"{len(usage.unpacked)} values unpacked and it returns a {len(elements)}-tuple")
    for index, consumer, param in usage.flows:
        if index < 0 or index >= len(elements):
            continue
        target = known.get(consumer)
        if not target:
            continue
        annotation = next((a for p, a, _ in target.params if p == param), "")
        if annotation and annotation == elements[index]:
            reasons.append(f"unpacked value {index} (`{elements[index]}`) is passed to "
                           f"`{consumer}` parameter `{param}` of that type")
    if candidate.is_class and usage.members:
        shared = sorted(usage.members & candidate.members)
        if shared:
            reasons.append(f"the result's {shared} are methods of the class")
    shared_tokens = sorted(_tokens(usage.name) & _tokens(candidate.name))
    if shared_tokens:
        reasons.append(f"names share {shared_tokens}")
    if len(reasons) < 2 or (len(reasons) == 1 and shared_tokens):
        return []
    return reasons


def detect_rename_candidates(sources: Sequence[Path], evidence: Sequence[NegativeEvidence],
                             *, max_candidates: int = 3) -> Iterator[NegativeEvidence]:
    """RENAME_CANDIDATE evidence for every dangling name some signature fits."""
    trees: dict[str, ast.Module] = {}
    known: dict[str, Signature] = {}
    for path in sources:
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except (SyntaxError, OSError):
            continue
        trees[str(path)] = tree
        for sig in signatures_from_tree(path, tree):
            known.setdefault(sig.name, sig)
    for sig in signatures_from_debris(evidence):
        known.setdefault(sig.name, sig)
    if not known:
        return

    seen: set[tuple[str, str]] = set()
    for item in evidence:
        if item.kind is not EvidenceKind.DANGLING_REFERENCE:
            continue
        found = re.match(r"`([A-Za-z_]\w*)`", item.detail)
        if not found or (item.file, found.group(1)) in seen:
            continue
        seen.add((item.file, found.group(1)))
        name = found.group(1)
        if name in known or item.file not in trees:
            continue
        usage = usage_of(trees[item.file], name, item.file, known)
        if usage is None:
            continue
        scored = []
        for candidate in known.values():
            reasons = match(usage, candidate, known)
            if reasons:
                scored.append((len(reasons), candidate, reasons))
        scored.sort(key=lambda s: (-s[0], s[1].name))
        for _, candidate, reasons in scored[:max_candidates]:
            yield NegativeEvidence(
                kind=EvidenceKind.RENAME_CANDIDATE,
                detail=(f"`{name}` may be `{candidate.render()}` from "
                        f"{Path(candidate.file).name}, matched by shape on "
                        f"{len(reasons)} dimension(s): " + "; ".join(reasons)
                        + ". Not by name: a coincidence of shape looks identical."),
                file=usage.file, line=usage.line,
            )
