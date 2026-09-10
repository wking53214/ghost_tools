"""cli.py -- `python -m blackhole_extrapolator <path>`.

Scans a tree for the marks absences leave, groups them by the thing that is
missing, and prints the outline of each void.

Prints outlines. Never emits source. There is deliberately no `--generate`,
no `--stub`, and no `--fix`: a file that fills a hole while carrying the name
of what was lost is indistinguishable from a recovery and is not one, and the
moment this tool can write one, somebody will commit its output as though the
original had been found.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

from .detect import _declared_dependencies, false_absence_hints, scan
from .corpus import RootKind, classify_root
from .extrapolate import extrapolate, group_by_target
from .schema import NON_SEEDING_KINDS, EvidenceKind, VoidKind

_SKIP_DIRS = {".git", "__pycache__", "site-packages", ".venv", "venv",
              "node_modules", ".pytest_cache", ".ruff_cache", ".mypy_cache"}


def _kind_for(evidence) -> VoidKind:
    """How to classify the absence, from what kind of marks it left.

    An unparseable file is something that existed and was destroyed -- the
    bytes are still on disk. A name nothing defines may never have existed at
    all, and saying otherwise would assert a history nobody can check.
    """
    kinds = {item.kind for item in evidence}
    if kinds & {EvidenceKind.DESTROYED_RESIDUE, EvidenceKind.DEBRIS_STRUCTURE}:
        return VoidKind.DESTROYED
    if EvidenceKind.MISSING_MODULE in kinds:
        for item in evidence:
            if "FLATTENED" in item.detail or "does not parse" in item.detail:
                return VoidKind.DESTROYED
    return VoidKind.NEVER_BUILT


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="blackhole_extrapolator",
        description="Infer the shape of missing code from what surrounds it.",
    )
    parser.add_argument("path", type=Path, help="directory to scan")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable voids instead of outlines")
    parser.add_argument("--min-confidence", type=float, default=0.0,
                        help="hide voids whose shape is less pinned down than this")
    parser.add_argument(
        "--sibling", action="append", default=[], type=Path, metavar="DIR",
        help="another checkout that may provide what this tree imports "
             "(repeatable). Imports it satisfies are reported as wiring, "
             "not voids.",
    )
    parser.add_argument(
        "--ecosystem", action="store_true",
        help="treat PATH as a parent directory of checkouts: scan each one "
             "with every other as a sibling, and report only what nothing "
             "in the ecosystem provides.",
    )
    parser.add_argument("--all", action="store_true",
                        help="render every void, including those whose evidence "
                             "constrains no shape")
    parser.add_argument("--show-wiring", action="store_true",
                        help="also list imports that are provided elsewhere")
    args = parser.parse_args(argv)
    if not args.path.is_dir():
        print(f"not a directory: {args.path}", file=sys.stderr)
        return 2

    if args.ecosystem:
        repos = sorted(p for p in args.path.iterdir() if p.is_dir() and (p / ".git").exists())
        if not repos:
            print(f"no checkouts (directories with .git) under {args.path}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps({repo.name: _payload(*_analyse(repo, [r for r in repos if r != repo], args)[:3], args)
                              for repo in repos}, indent=2))
            return 0
        for repo in repos:
            print(f"=== {repo.name}")
            _report(repo, [r for r in repos if r != repo], args)
            print()
        return 0
    return _report(args.path, args.sibling, args)


def _payload(voids, wiring, evidence, args):
    if args.show_wiring:
        return {"voids": [v.as_dict() for v in voids], "wiring": [w.as_dict() for w in wiring]}
    return [v.as_dict() for v in voids]


def _analyse(root: Path, siblings: List[Path], args):
    """(voids, wiring, non-wiring evidence) for one tree."""
    evidence = [
        item for item in scan(root, siblings)
        if not (_SKIP_DIRS & set(Path(item.file).parts))
    ]
    wiring = [item for item in evidence if item.kind is EvidenceKind.WIRING]
    evidence = [item for item in evidence if item.kind is not EvidenceKind.WIRING]

    # An archive of code is not a system with holes in it. Its truncated
    # pastes are a statement about the extraction, and outlining them as
    # absences to be rebuilt is the tool answering a question nobody asked.
    classification = classify_root(root)

    voids = []
    for target, items in sorted(group_by_target(evidence).items()):
        # A group made only of non-seeding marks is not a void. Each of
        # those kinds has a reading under which nothing is missing at all,
        # and one of them alone cannot carry a claim that something is.
        if all(i.kind in NON_SEEDING_KINDS for i in items):
            continue
        files = sorted({Path(i.file) for i in items})
        void = extrapolate(
            summary=f"`{target}` is reached for and is not there",
            evidence=items,
            kind=_kind_for(items),
            target=target,
            sources=files,
            also_referenced_elsewhere=len(files) > 1,
        )
        if void.shape_confidence >= args.min_confidence:
            voids.append(void)
    return voids, wiring, evidence, classification


def _report(root: Path, siblings: List[Path], args) -> int:
    voids, wiring, evidence, classification = _analyse(root, siblings, args)
    if classification.is_archive:
        return _report_archive(classification, voids, evidence, args)
    if args.json:
        # Always JSON on --json, including the empty case: a pipeline that
        # parsed the output got prose the first time a clean tree was scanned.
        print(json.dumps(_payload(voids, wiring, evidence, args), indent=2))
        return 0
    if not evidence and not wiring:
        print("No negative-space evidence found. Nothing is reaching for "
              "something that is not there.")
        return 0
    unresolved = [e for e in evidence if e.kind is EvidenceKind.UNRESOLVED_IMPORT]
    missing_imports = [e for e in evidence if e.kind is EvidenceKind.MISSING_IMPORT]
    if not voids:
        # "Nothing is missing" is only true when nothing is outstanding. With
        # an unresolved import on the page it would be the tool contradicting
        # its own next paragraph.
        lead = ("Nothing is missing." if not unresolved and not missing_imports
                else "No voids.")
        print(f"{lead} {len(wiring)} import(s) are provided elsewhere"
              + (":" if args.show_wiring else " (use --show-wiring to list them)."))
        if args.show_wiring:
            _print_wiring(wiring)
        _print_unresolved(unresolved, missing_imports, root)
        _print_hints(root, siblings)
        return 0
    voids.sort(key=lambda v: v.shape_confidence, reverse=True)

    # A void whose INFERRED section is empty is half a Void: it carries the
    # UNDETERMINABLE list and nothing the evidence forced. Measured
    # 2026-09-10, those were 25% of the report by volume. They are counted
    # and named, not rendered, unless --all asks for them.
    #
    # The test is "constrains no shape", never a confidence threshold: after
    # the classification pass, shapeless voids sit at 0.35-0.40 alongside
    # fourteen that DO have a shape, so a numeric cutoff would hide real
    # ones to reach them.
    shaped = [v for v in voids if v.inferred_anything]
    shapeless = [v for v in voids if not v.inferred_anything]
    for void in (voids if args.all else shaped):
        print(void.render())
        print()
    if shapeless and not args.all:
        names = ", ".join(sorted(v.summary.split("`")[1] for v in shapeless
                                 if "`" in v.summary)[:6])
        print(f"{len(shapeless)} further absence(s) whose evidence constrains no "
              f"shape at all -- named, not outlined: {names}"
              + (", ..." if len(shapeless) > 6 else "")
              + "  (--all to render them)")
        print()
    print(f"{len(shaped)} outlined void(s)"
          + (f" and {len(shapeless)} shapeless" if shapeless else "")
          + f" from {len(evidence)} negative-space signals"
          + (f"; {len(wiring)} import(s) provided elsewhere" if wiring else "")
          + ("." if not wiring or args.show_wiring else " (use --show-wiring to list them)."))
    if wiring and args.show_wiring:
        _print_wiring(wiring)
    _print_unresolved(unresolved, missing_imports, root)
    _print_hints(root, siblings)
    return 0


def _report_archive(classification, voids, evidence, args) -> int:
    """What to say about a repository whose job is to preserve code.

    Everything found is still reported. What changes is the claim attached
    to it: a file that will not parse inside an export is a lossy
    extraction, and the useful question is how much of the archive is
    readable -- not which module somebody should go and rebuild.
    """
    if args.json:
        print(json.dumps({
            "root_kind": classification.kind.value,
            "reason": classification.reason,
            "archived_files": classification.archived_files,
            "total_files": classification.total_files,
            "extraction_fidelity": [e.as_dict() for e in evidence],
        }, indent=2))
        return 0
    damaged = sorted({e.file for e in evidence
                      if e.kind in (EvidenceKind.DESTROYED_RESIDUE,
                                    EvidenceKind.DEBRIS_STRUCTURE)})
    # Each kind is not-a-source-tree for a different reason, and the reader
    # needs the reason to know what to do next. Collapsing them into
    # "archive" would tell someone their deliberate fixtures were preserved
    # payloads, which is wrong in a way that costs trust.
    headline = {
        RootKind.CODE_ARCHIVE:
            "This is an archive of code, not a source tree",
        RootKind.SPECIMEN_CORPUS:
            "This is a specimen corpus: code kept broken on purpose so tools "
            "can be tested against it",
        RootKind.RETIRED:
            "This repository says it is retired",
    }[classification.kind]
    print(f"{headline}: {classification.reason}.")
    if classification.kind is RootKind.SPECIMEN_CORPUS:
        print("Its damaged files are the point of it. They are reported as "
              "fixtures, not as voids.")
    elif classification.kind is RootKind.RETIRED:
        target = classification.forwarding
        print("What looks lost here is somewhere else"
              + (f" -- scan {target}, which is where its content went."
                 if target else ", named in its own README."))
    else:
        print("Its absences are reported as extraction fidelity, not as voids.")
    print()
    print(f"  {classification.total_files} Python file(s); "
          f"{len(damaged)} did not survive extraction intact")
    print(f"  {len(evidence)} negative-space signal(s) in total")
    if damaged and args.show_wiring:
        for path in damaged:
            print(f"    {path}")
    elif damaged:
        print("  (use --show-wiring to list the damaged files)")
    print()
    print("Nothing here is missing from a running system. Scan the "
          "repository this code was extracted FROM to ask that question.")
    return 0


def _print_hints(root: Path, siblings) -> None:
    """Conditions of this scan that could make its absences false.

    Printed once per run rather than repeated on every void: they describe
    the scan and not the code, and a caveat stapled to each finding reads as
    noise by the third repetition.
    """
    hints = false_absence_hints(root, siblings)
    if not hints:
        return
    print(f"\nBefore treating any of the above as lost -- {len(hints)} thing(s) "
          "about THIS SCAN could produce an absence that is not one:")
    for hint in hints:
        print(f"  - {hint}")


def _print_unresolved(unresolved, missing_imports, root: Path) -> None:
    """Report what was demoted out of void-hood, never drop it.

    Downgrading a claim is not licence to stop making it. An import that
    resolves nowhere is a real thing to go and settle -- declare the
    dependency, or find out the module is gone -- and a report that
    silently stopped mentioning it would have traded a wrong answer for no
    answer, which is the worse of the two.
    """
    if missing_imports:
        names = sorted({e.detail.split("`")[1] for e in missing_imports if "`" in e.detail})
        print(f"\n{len(missing_imports)} missing import(s) -- a name the language "
              f"provides, used without importing it: {', '.join(names)}")
    if unresolved:
        by_module = {}
        for item in unresolved:
            name = item.detail.split("`")[1] if "`" in item.detail else item.detail
            by_module.setdefault(name, set()).add(Path(item.file).name)
        # Whether the project declares dependencies AT ALL decides what
        # these are. A populated manifest that omits them is a manifest bug
        # to fix today; no manifest at all cannot have omitted anything, and
        # saying "undeclared" of such a project would be an accusation the
        # evidence does not support.
        declares = bool(_declared_dependencies(root))
        verdict = ("The project declares dependencies and none of these is among "
                   "them -- either the manifest is short, or they are lost."
                   if declares else
                   "The project declares no dependencies anywhere, so nothing here "
                   "can say whether these were meant to come from outside.")
        print(f"\n{len(by_module)} import(s) resolve nowhere. Not outlined as "
              f"voids: nothing here can tell a lost module from a dependency "
              f"that was never declared. {verdict}")
        for name, files in sorted(by_module.items()):
            shown = ", ".join(sorted(files)[:3])
            more = f" +{len(files) - 3} more" if len(files) > 3 else ""
            print(f"  {name}  <- {shown}{more}")


def _print_wiring(wiring) -> None:
    by_provider = {}
    for item in wiring:
        provider = item.detail.split("provided by ", 1)[-1]
        by_provider.setdefault(provider, set()).add(
            item.detail.split("`")[1] if "`" in item.detail else item.detail)
    for provider, modules in sorted(by_provider.items()):
        print(f"  {provider}: {', '.join(sorted(modules))}")


if __name__ == "__main__":
    raise SystemExit(main())
