"""cli.py -- `python -m ghost_writer.cli report <findings.json>`.

v0.1 scope: wires up report.py (pure templating, no API key needed).
correct.py's LLM-backed proposal mode is available as a library but not
wired into this CLI yet -- same reasoning as ghost_buster's CLI: a mode
that costs real money per call should never be the default path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from ghost_buster.schema import FindingSet

from .report import render_ghost_report


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="ghost_writer")
    parser.add_argument("findings", type=Path, help="a FindingSet JSON file (from ghost_buster --json)")
    parser.add_argument("--title", default="Known Structural Ghosts")
    parser.add_argument("--out", type=Path, default=None, help="write to a file instead of stdout")
    args = parser.parse_args(argv)

    if not args.findings.is_file():
        print(f"error: {args.findings} is not a file", file=sys.stderr)
        return 2

    fs = FindingSet.from_json(args.findings.read_text(encoding="utf-8"))
    report = render_ghost_report(list(fs), title=args.title)

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
