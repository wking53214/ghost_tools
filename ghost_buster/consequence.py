"""consequence.py -- a second key for a finding: does it matter here?

Ghost's severity says how bad a finding is, and the detector decides it from the code alone.
It cannot see where the code sits. This module adds an independent reading, taken from the
other repositories of a stack, and ranks findings by both. Nothing about a finding changes:
its id, status and severity are read, never written.

THE QUESTION AND THE RULE

  shared     the file is production code and another repository imports its package
  own-use    the file is production code and only its own repository uses the package
  repo-level the finding is about a non-Python file (a manifest, a requirements file)
  off-path   the file is a test, an example, a script, an archive or a fixture

  tier  1 FIX FIRST  serious and shared
        2 FIX        serious and own-use or repo-level
        3 DEFER      serious and off-path
        4 WATCH      not serious and shared
        5 BACKLOG    everything else
        0 SET ASIDE  a rejected or suppressed finding (not a live finding)

"Serious" is Ghost's own severity, major or critical. A `reasoned` finding keeps its tier and is
marked `verify`, because nobody has established it yet.

WHAT IT DOES NOT KNOW

  * An import is matched by top-level package name. A name two repositories both provide is
    ambiguous, so an importer that provides its own copy is not counted as a consumer.
  * An import shows that code depends on a package, not that it runs. Reachability from a deployed
    entry point is a stronger signal (sentinel_os/tools/wiring_verify), but it needs entry points
    declared per repository, and almost none are.
  * Dynamic imports (importlib, __import__ with a computed name) are invisible.
  * Whether a file is "production" is decided from its path alone.

Files are parsed, never imported or run. Symbolic links are not followed.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .diagnostics import add_verbose_argument, configure, get_logger

log = get_logger(__name__)

RULE = "ghost_buster.consequence/1"
MAX_FILE_BYTES = 5 * 1024 * 1024
SERIOUS = ("major", "critical")
SET_ASIDE_STATUSES = ("rejected", "suppressed")

SHARED, OWN_USE, REPO_LEVEL, OFF_PATH = "shared", "own-use", "repo-level", "off-path"

TIERS = {
    0: "SET ASIDE",
    1: "FIX FIRST",
    2: "FIX",
    3: "DEFER",
    4: "WATCH",
    5: "BACKLOG",
}

_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "target", "build", "dist", ".tox"}
_OFF_PATH = re.compile(
    r"(^|/)(tests?|archive|examples?|docs?|scripts?|tools|fixtures|specimens|testdata)(/|$)"
    r"|(^|/)conftest\.py$|(^|/)test_[^/]*\.py$|(^|/)[^/]*_test\.py$"
)


def is_off_path(relpath: str) -> bool:
    """A test, example, script, archive or fixture, judged from the path alone."""
    return bool(_OFF_PATH.search(relpath.replace(os.sep, "/")))


def package_of(relpath: str) -> str:
    """The top-level importable name a file belongs to ('src/dit/x.py' is 'dit')."""
    parts = relpath.replace(os.sep, "/").split("/")
    if parts[0] == "src" and len(parts) > 2:
        return parts[1]
    return parts[0] if len(parts) > 1 else os.path.splitext(parts[0])[0]


def _imports(tree: ast.AST) -> Set[str]:
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _python_files(root: Path) -> Iterable[Tuple[str, Path]]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not Path(dirpath, d).is_symlink()]
        for name in filenames:
            path = Path(dirpath, name)
            if name.endswith(".py") and not path.is_symlink():
                yield os.path.relpath(path, root), path


@dataclass(frozen=True)
class Stack:
    """What each repository provides and what its production code imports."""

    provides: Mapping[str, Set[str]]          # package name -> repositories that provide it
    imports: Mapping[str, Set[str]]           # repository -> names its production files import
    repos: Tuple[str, ...]

    def importers(self, repo: str, package: str) -> Tuple[str, ...]:
        """Other repositories whose production code imports `package` from `repo`."""
        providers = self.provides.get(package, set())
        out = []
        for other in self.repos:
            if other == repo or package not in self.imports.get(other, set()):
                continue
            if other in providers:      # it has its own copy of that name: not a consumer of this one
                continue
            out.append(other)
        return tuple(out)


def read_stack(stack_dir: Path) -> Stack:
    """Read every immediate subdirectory of `stack_dir` as one repository."""
    repos = tuple(sorted(d.name for d in Path(stack_dir).iterdir() if d.is_dir() and not d.is_symlink()
                         and d.name not in _SKIP_DIRS))
    provides: Dict[str, Set[str]] = {}
    imports: Dict[str, Set[str]] = {r: set() for r in repos}
    for repo in repos:
        root = Path(stack_dir, repo)
        for rel, path in _python_files(root):
            if is_off_path(rel):
                continue
            provides.setdefault(package_of(rel), set()).add(repo)
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, ValueError, OSError):
                continue
            imports[repo] |= _imports(tree)
    return Stack(provides=provides, imports=imports, repos=repos)


@dataclass(frozen=True)
class Consequence:
    kind: str
    package: str
    importers: Tuple[str, ...]


def consequence(stack: Stack, repo: str, relpath: str) -> Consequence:
    if not relpath.endswith(".py"):
        return Consequence(REPO_LEVEL, "", ())
    if is_off_path(relpath):
        return Consequence(OFF_PATH, package_of(relpath), ())
    package = package_of(relpath)
    found = stack.importers(repo, package)
    return Consequence(SHARED if found else OWN_USE, package, found)


def tier(status: str, severity: str, kind: str) -> int:
    """The tier the rule gives a finding. Pure: the same three words always give the same number."""
    if status in SET_ASIDE_STATUSES:
        return 0
    serious = severity in SERIOUS
    if serious:
        return {SHARED: 1, OFF_PATH: 3}.get(kind, 2)
    return 4 if kind == SHARED else 5


@dataclass(frozen=True)
class Ranked:
    repo: str
    id: str
    detector: str
    file: str
    severity: str
    status: str
    consequence: Consequence
    tier: int
    verify: bool

    def as_dict(self) -> Dict[str, object]:
        return {
            "rule": RULE, "repo": self.repo, "id": self.id, "detector": self.detector, "file": self.file,
            "severity": self.severity, "status": self.status, "tier": self.tier,
            "tier_name": TIERS[self.tier], "kind": self.consequence.kind,
            "package": self.consequence.package, "importers": list(self.consequence.importers),
            "verify": self.verify,
        }


def rank(stack: Stack, reports: Mapping[str, Mapping[str, Any]]) -> List[Ranked]:
    """Rank the findings of `ghost-buster --json` reports, keyed by repository name.

    Ordered by tier (FIX FIRST first, SET ASIDE last), then by how many repositories import the package,
    then by repository and file so the order is the same on every run.
    """
    out: List[Ranked] = []
    for repo, report in reports.items():
        for f in report.get("findings", []):
            status, severity = str(f["status"]).lower(), str(f["severity"]).lower()
            relpath = str(f["evidence"]["file"])
            c = consequence(stack, repo, relpath)
            out.append(Ranked(repo=repo, id=str(f["id"]), detector=str(f["detector"]), file=relpath,
                              severity=severity, status=status, consequence=c,
                              tier=tier(status, severity, c.kind), verify=status == "reasoned"))
    live = [r for r in out if r.tier != 0]
    aside = [r for r in out if r.tier == 0]

    def order(r: Ranked) -> Tuple[int, int, str, str, str]:
        return (r.tier, -len(r.consequence.importers), r.repo, r.file, r.id)

    return sorted(live, key=order) + sorted(aside, key=order)


def _report_name(spec: str) -> Tuple[str, Path]:
    name, sep, path = spec.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError("expected REPO=REPORT.json")
    return name, Path(path)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ghost-rank",
        description="Rank Ghost findings by severity and by whether other repositories depend on the code.")
    parser.add_argument("--stack", required=True, type=Path,
                        help="a folder whose subfolders are the repositories")
    parser.add_argument("reports", nargs="+", type=_report_name, metavar="REPO=REPORT.json",
                        help="the output of `ghost-buster --json`, one per repository")
    parser.add_argument("--json", action="store_true", help="print the ranking as JSON")
    parser.add_argument("--limit", type=int, default=40, help="rows to print in text mode (0 for all)")
    add_verbose_argument(parser)
    args = parser.parse_args(argv)
    configure(verbose=args.verbose)

    reports: Dict[str, Mapping[str, Any]] = {}
    for name, path in args.reports:
        try:
            reports[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.error("ghost-rank: cannot read %s: %s", path, exc)
            return 2
    stack = read_stack(args.stack)
    unknown = [n for n in reports if n not in stack.repos]
    if unknown:
        log.error("ghost-rank: not a folder under %s: %s", args.stack, ", ".join(unknown))
        return 2
    ranked = rank(stack, reports)
    if args.json:
        print(json.dumps([r.as_dict() for r in ranked], indent=2))
        return 0
    counts: Dict[int, int] = {}
    for r in ranked:
        counts[r.tier] = counts.get(r.tier, 0) + 1
    print(f"rule {RULE}: " + ", ".join(f"{TIERS[t]} {counts[t]}" for t in sorted(counts)))
    shown = ranked if args.limit == 0 else ranked[: args.limit]
    for r in shown:
        who = f"{len(r.consequence.importers)} repo(s)" if r.consequence.importers else r.consequence.kind
        print(f"{TIERS[r.tier]:<10} {r.severity:<13} {r.repo}/{r.file}  {r.detector}  [{who}]"
              + ("  VERIFY" if r.verify else ""))
    if len(shown) < len(ranked):
        print(f"... {len(ranked) - len(shown)} more (use --limit 0 or --json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
