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

from .detect import scan
from .extrapolate import extrapolate, group_by_target
from .schema import EvidenceKind, VoidKind

_SKIP_DIRS = {".git", "__pycache__", "site-packages", ".venv", "venv",
              "node_modules", ".pytest_cache", ".ruff_cache", ".mypy_cache"}


def _kind_for(evidence) -> VoidKind:
    """How to classify the absence, from what kind of marks it left.

    An unparseable file is something that existed and was destroyed -- the
    bytes are still on disk. A name nothing defines may never have existed at
    all, and saying otherwise would assert a history nobody can check.
    """
    kinds = {item.kind for item in evidence}
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
        rc = 0
        for repo in repos:
            print(f"=== {repo.name}")
            rc = max(rc, _report(repo, [r for r in repos if r != repo], args))
            print()
        return rc
    return _report(args.path, args.sibling, args)


def _report(root: Path, siblings: List[Path], args) -> int:
    evidence = [
        item for item in scan(root, siblings)
        if not (_SKIP_DIRS & set(Path(item.file).parts))
    ]
    wiring = [item for item in evidence if item.kind is EvidenceKind.WIRING]
    evidence = [item for item in evidence if item.kind is not EvidenceKind.WIRING]
    if not evidence and not wiring:
        print("No negative-space evidence found. Nothing is reaching for "
              "something that is not there.")
        return 0
    if not evidence:
        print(f"Nothing is missing. {len(wiring)} import(s) are provided elsewhere"
              + (":" if args.show_wiring else " (use --show-wiring to list them)."))
        if args.show_wiring:
            _print_wiring(wiring)
        return 0

    voids = []
    for target, items in sorted(group_by_target(evidence).items()):
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

    if args.json:
        if args.show_wiring:
            print(json.dumps({"voids": [v.as_dict() for v in voids],
                              "wiring": [w.as_dict() for w in wiring]}, indent=2))
        else:
            print(json.dumps([v.as_dict() for v in voids], indent=2))
        return 0
    voids.sort(key=lambda v: v.shape_confidence, reverse=True)
    for void in voids:
        print(void.render())
        print()
    print(f"{len(voids)} void(s) from {len(evidence)} negative-space signals"
          + (f"; {len(wiring)} import(s) provided elsewhere" if wiring else "")
          + ("." if not wiring or args.show_wiring else " (use --show-wiring to list them)."))
    if wiring and args.show_wiring:
        _print_wiring(wiring)
    return 0


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
