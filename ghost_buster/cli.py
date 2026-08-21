"""cli.py -- `python -m ghost_buster <path>`.

v0.1 scope: wires up Layer 1 (mechanical) end to end, always. Layer 2
(semantic) is available as a library (see semantic.py) but is NOT wired
into this CLI by default yet -- it needs a real API key, costs real
money per run, and (per this whole project's own "discovery before fix,
no silent scope creep" discipline) a tool that costs money should never
run by default without the caller explicitly asking for it. --semantic
opts in.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from .baseline import Baseline
from .mechanical import run_all
from .schema import Finding, FindingSet, Severity


def _collect_py_files(root: Path) -> List[Path]:
    return sorted(
        p for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and not p.name.startswith(".")
    )


def _print_report(new: List[Finding], known: List[Finding]) -> None:
    order = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2, Severity.INFORMATIONAL: 3}
    new_sorted = sorted(new, key=lambda f: order[f.severity])

    print(f"\nghost_buster: {len(new_sorted)} new finding(s), {len(known)} already in baseline\n")
    for f in new_sorted:
        loc = f.evidence.file
        if f.evidence.line_start:
            loc += f":{f.evidence.line_start}"
        print(f"  [{f.severity.value.upper():13s}] {f.detector:25s} {loc}")
        print(f"      {f.summary}")
        if f.detail:
            print(f"      {f.detail}")
        print(f"      id: {f.id}")
        print()

    if not new_sorted:
        print("  (nothing new)\n")


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="ghost_buster")
    parser.add_argument("path", type=Path, help="directory to scan")
    parser.add_argument(
        "--baseline", type=Path, default=None,
        help="baseline file for delta reporting (default: <path>/.ghost_baseline.json)",
    )
    parser.add_argument(
        "--accept", action="store_true",
        help="accept all current findings into the baseline (suppress them going forward)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="emit the full finding set as JSON instead of the human report",
    )
    args = parser.parse_args(argv)

    if not args.path.is_dir():
        print(f"error: {args.path} is not a directory", file=sys.stderr)
        return 2

    baseline_path = args.baseline or (args.path / ".ghost_baseline.json")
    files = _collect_py_files(args.path)
    findings = run_all(files)

    baseline = Baseline(baseline_path)

    if args.accept:
        baseline.accept(findings)
        print(f"accepted {len(findings)} finding(s) into {baseline_path}")
        return 0

    new, known = baseline.diff(findings)

    if args.json:
        print(FindingSet(new).to_json())
    else:
        _print_report(new, known)

    return 1 if any(f.severity in (Severity.CRITICAL, Severity.MAJOR) for f in new) else 0


if __name__ == "__main__":
    sys.exit(main())
