"""stack-census -- a read-only census of every git repo one level down.

Reports what git, the manifests and the Graveyard already say. It writes
nothing: no file in any repo, and no CENSUS.md. `--entry` prints a draft for
you to paste, with the decision line left blank.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional

from . import render
from .census import build

DEFAULT_OWNER = "wking53214"
DEFAULT_GRAVEYARD = "Graveyard"
EXIT_USAGE = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stack-census", description="Read-only census of every git repo one level down.")
    parser.add_argument("parent", type=Path, help="folder holding all the clones")
    parser.add_argument("--owner", default=DEFAULT_OWNER,
                        help="GitHub owner whose repos count as yours when reading pins")
    parser.add_argument("--graveyard", default=DEFAULT_GRAVEYARD,
                        help="name of the Graveyard folder inside the parent")
    parser.add_argument("--date", type=date.fromisoformat, default=None,
                        help="census date, YYYY-MM-DD (default: today)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--entry", action="store_true",
                        help="print a draft CENSUS.md entry instead of the table")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if not args.parent.is_dir():
        print(f"stack-census: {args.parent} is not a folder", file=sys.stderr)
        return EXIT_USAGE
    census = build(args.parent, args.owner, args.graveyard, args.date or date.today())
    if args.json:
        print(render.as_json(census))
    elif args.entry:
        print(render.entry(census))
    else:
        print(render.text(census))
    return 0


if __name__ == "__main__":
    sys.exit(main())
