"""Regenerate the self-scan baseline from a fresh scan of this tree.

Policy, held by Tests/test_self_scan.py: only MAJOR and CRITICAL findings
are baselined, each must have a reason recorded in .ghost_casefile.json,
and no entry may be stale. Run this after a change that moves a
baselined finding's id (a long function that got longer, a repeated
statement whose lines shifted); it refuses to baseline anything the case
file has no reason for, so a new MAJOR is a decision, never a reflex.

    python tools/self_baseline.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ghost_buster.baseline import Baseline  # noqa: E402
from ghost_buster.schema import FindingSet, Severity  # noqa: E402

FLAGS = ["--no-tests", "--no-branches", "--single-repo", "--no-ledger", "--no-correlate", "--json",
         "--baseline", str(ROOT / ".ghost_no_such_baseline.json")]


def main() -> int:
    out = subprocess.run([sys.executable, "-m", "ghost_buster.cli", str(ROOT), *FLAGS],
                         capture_output=True, text=True, cwd=ROOT).stdout
    findings = FindingSet.from_json(out).findings
    keep = [f for f in findings if f.severity in (Severity.MAJOR, Severity.CRITICAL)]
    cases = json.loads((ROOT / ".ghost_casefile.json").read_text())["cases"]
    reasoned = {c["detector"] for c in cases if c.get("note")}
    unreasoned = [f for f in keep if f.detector not in reasoned]
    if unreasoned:
        print("refusing: no reason in .ghost_casefile.json for", file=sys.stderr)
        for f in unreasoned:
            print(f"  {f.id}  {f.summary}", file=sys.stderr)
        print("record one with: ghost-triage findings.json --casefile .ghost_casefile.json --set ID=document:\"why\"",
              file=sys.stderr)
        return 1
    path = ROOT / ".ghost_baseline.json"
    if path.exists():
        path.unlink()
    Baseline(path).accept(keep)
    print(f"{path.name}: {len(keep)} entr{'y' if len(keep) == 1 else 'ies'}, "
          f"{len(findings) - len(keep)} MINOR/INFORMATIONAL left reported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
