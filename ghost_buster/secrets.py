"""secrets.py -- committed-secret detection: a repository-level check that
shells out to `gitleaks` against the project's git history.

WHY THIS IS A SEPARATE MODULE
------------------------------
Same reasoning as branches.py and testsuite.py: this check has no file
content to parse on its own terms, it has a repository's commit history,
so it takes a project root and shells out, rather than being a
`Callable[[List[Path]], List[Finding]]` detector in mechanical.py. It is
still deterministic -- the same history scanned twice yields the same
findings -- so it is still `Layer.MECHANICAL` / `Status.CONFIRMED` in
schema.py's sense.

WHY GITLEAKS, NOT A NEW ENTROPY DETECTOR
-------------------------------------------
Secret detection is a solved, adversarial problem: hundreds of credential
formats (cloud provider keys, private keys, database URLs with embedded
passwords, webhook tokens), each with its own shape, false-positive traps,
and the entropy math to catch the generic case none of those formats cover.
gitleaks is a mature, actively maintained open-source scanner that already
carries that rule set. Every other repository-level check in this project
shells out to an existing tool rather than reimplementing it where one
already exists correctly (branches.py to `git`, mutation.py and
testsuite.py to `pytest`); this is the same choice, applied to secrets.

WHY GIT HISTORY, NOT JUST THE WORKING TREE
---------------------------------------------
A secret "removed" in a later commit is still sitting in the repository's
history, readable by anyone who can clone it or already has. Only
rewriting history (and force-pushing, and rotating the credential) removes
it. Scanning current file content -- what every mechanical.py detector
already does -- would pass a repository clean that leaked a key three
commits ago and "fixed" it by deleting the line. `gitleaks detect`'s
default mode scans the checked-out branch's own git log diffs, which is
exactly this history; it is not asked to scan `--no-git` (working-tree
content only), because that would silently drop exactly the case this
module exists to catch.

Only the checked-out branch's own history is scanned -- gitleaks' default,
not `--log-opts=--all`. A secret sitting only on a branch this checkout
has not fetched, or an unmerged branch never checked out here, will not be
seen until that branch's own history is scanned directly. This is the same
category of blind spot branches.py discloses for its own git-plumbing
scope, not something this module tries to work around.

THE SECRET VALUE IS NEVER IN A FINDING
------------------------------------------
gitleaks is invoked with `--redact`, confirmed directly: its `Secret` and
`Match` fields come back as the literal text `REDACTED`, never the actual
credential. This module goes one step further and does not read either
field at all, redacted or not -- only `RuleID`, `Description`, `File`,
`StartLine`/`EndLine`, `StartColumn`, `Commit`, `Author`, `Date`, `Message`,
and `Fingerprint` ever reach a `Finding`. This is not a minor nicety: a
`Finding` is written into `.ghost_baseline.json` the moment someone runs
`--accept`, and that file is meant to be committed. If the secret text ever
reached a finding's summary or detail, accepting the finding would commit
the leak a second time, inside the exact file whose purpose is to make
findings inert.

WHY A NON-GIT DIRECTORY IS A HARD STOP, NOT A CLEAN SCAN
-------------------------------------------------------------
Measured directly, and the whole reason this module checks its own
precondition instead of trusting gitleaks' exit code: given a directory
with no `.git`, gitleaks logs an error to stderr ("not a git repository")
but still exits 0 and writes an empty JSON report -- indistinguishable, by
exit code or report content alone, from a real, clean scan. Reporting "no
secrets found" for a directory gitleaks never actually looked at is a
false negative, the same failure class `branches.py`'s non-UTF-8-diff
history exists to avoid. This module runs `git rev-parse --git-dir` itself
before ever invoking gitleaks, and reports `ran=False` for anything that
fails it, so a wrong path or a directory that lost its `.git` cannot read
as clean.

Real gitleaks failures -- a bad path, a bad flag, an unwritable report
path -- were confirmed separately to still exit non-zero even with
`--exit-code 0` (which only overrides the "leaks were found" case); any
non-zero exit is treated as `ran=False` with gitleaks' own stderr as the
reason, never as zero findings.

WHAT THIS DOES NOT DO
-------------------------
- Never installs gitleaks. If it is not on PATH (or at the path given by
  `--secrets-binary`), the scan reports `ran=False` with an install
  pointer; nothing here fetches a binary from the network. Consistent
  with testsuite.py's `--tests`: report what is missing, let the reader
  decide whether to provide it.
- Never rewrites history, rotates a credential, deletes a file, or writes
  anything into the target repository. A committed secret remains exactly
  as exposed after this scan as before it -- visible only to whoever could
  already read the repository's history.
- Adds no suppression logic beyond the shared baseline every other
  detector already uses. If the target repository has its own
  `.gitleaksignore` or `.gitleaks.toml`, gitleaks honors them itself
  (confirmed directly: a fingerprint listed in `.gitleaksignore` drops
  that finding from the report before this module ever sees it) exactly
  as it would running standalone.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "committed_secret"

_TIMEOUT_DEFAULT = 300.0
_GIT_CHECK_TIMEOUT = 15.0

# WHAT A RULE PROVES, AND WHAT IT ONLY SUGGESTS
#
# Most gitleaks rules match a provider-ISSUED prefix: sk-, ghp_, AKIA,
# xoxb-, or a PEM header. A provider mints those; they do not occur by
# accident. A match is a credential, and CRITICAL is the honest rating.
#
# A handful match SHAPE instead: a high-entropy string standing near a
# word like key, token or secret. That is a candidate, not a credential,
# and it fires on things that merely look the part.
#
# Measured 2026-09-10 across a 37-repository library: every one of the 32
# 'generic-api-key' hits was a false positive. Ten were the header
# {"x-api-key": "testkey-abc123"} in a test file. Eight were prose inside
# exported conversation logs. Six were a fake key fed to a redaction demo
# -- the detector found the bait the code exists to catch. Six were the
# English word "anthropomorphic". Not one was a credential.
#
# Rating those CRITICAL alongside a real leaked token is how a security
# check gets skimmed, and a skimmed check is worth less than no check:
# the next real one arrives in a list the reader has already learned to
# scroll past. So a shape-only match is reported, and reported as MAJOR.
#
# This is a severity judgement, not a filter. Nothing is suppressed, no
# file type is exempt, and a secret in a test file is still a secret --
# it is only rated by how much the rule established.
#
# 'curl-auth-header' is the same kind of rule, found the same way and
# missed the first time. It anchors on an authorization-style header
# inside a curl command and captures whatever value follows, so
#   curl -H "X-API-Key: prod_key_123" https://your-domain/process
# matches on the strength of the header name alone. Measured 2026-09-10,
# it fired four times across the same library and every hit was a
# placeholder in generated documentation -- prod_key_123 and
# customer_abc123, pointed at your-domain and your-platform.
#
# It was rated CRITICAL until now for one reason: the first pass listed
# the rules it had seen fire, and gitleaks had timed out on the only
# repository where this one fires. A fix scoped to the rules that showed
# up is scoped to the measurement, not to the problem.
#
# To extend: add a rule id here only if it matches entropy or proximity
# rather than an issued prefix.
_SHAPE_ONLY_RULES = frozenset({"curl-auth-header", "generic-api-key"})


@dataclass
class SecretsScanReport:
    ran: bool
    reason: str = ""
    leaks_found: int = 0
    gitleaks_version: str = ""


def _is_git_repo(root: Path) -> bool:
    """See the module docstring: gitleaks itself does not reliably refuse
    a non-git directory, so this is checked before gitleaks is ever run."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-dir"], cwd=root,
            capture_output=True, text=True, errors="replace", timeout=_GIT_CHECK_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False
    return proc.returncode == 0


def _gitleaks_version(binary: str) -> str:
    try:
        proc = subprocess.run(
            [binary, "version"], capture_output=True, text=True, errors="replace", timeout=15.0,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""
    return (proc.stdout or proc.stderr or "").strip()


def _short_message(message: str, limit: int = 90) -> str:
    if not message or not message.strip():
        return ""
    first_line = message.strip().splitlines()[0]
    return first_line if len(first_line) <= limit else first_line[: limit - 1] + "…"


def _finding(root: Path, entry: dict) -> Optional[Finding]:  # ghost_buster: name-disagreement -- `entry` is `e` at every call site
    file = entry.get("File")
    if not file:
        return None
    rule = entry.get("RuleID") or "unknown-rule"
    line = entry.get("StartLine")
    line = line if isinstance(line, int) else None
    end_line = entry.get("EndLine")
    end_line = end_line if isinstance(end_line, int) else None
    column = entry.get("StartColumn")
    commit = (entry.get("Commit") or "").strip()
    commit_short = commit[:12] if commit else "unknown commit"
    fingerprint = entry.get("Fingerprint") or f"{commit}:{file}:{rule}:{line}"

    file_path = Path(file)
    rel = file_path.as_posix()
    location = f"{rel}:{line}" if line is not None else rel
    if column is not None:
        location += f":{column}"
    summary = f"a '{rule}' secret is committed in {location} (commit {commit_short})"

    intro = f"Introduced in commit {commit_short}"
    who = entry.get("Author")
    if who:
        intro += f" by {who}"
    when = entry.get("Date")
    if when:
        intro += f" on {when}"
    message = _short_message(entry.get("Message", ""))
    if message:
        intro += f": {message!r}"
    intro += "."

    description = (entry.get("Description") or "").strip()
    detail_lines = [
        f"gitleaks rule '{rule}'" + (f": {description}" if description else "."),
        intro,
    ]
    if rule in _SHAPE_ONLY_RULES:
        detail_lines.append(
            "VERIFY THIS ONE BEFORE ROTATING ANYTHING. This rule matches the "
            "SHAPE of a credential -- a high-entropy string near a word like "
            "key, token or secret -- not a prefix any provider issues. It "
            "cannot tell a live key from a test fixture, a hash quoted in "
            "prose, or a deliberately fake value in a redaction demo. Read the "
            "line first; rotate only if it is real."
        )
    detail_lines += [
        "The secret value itself is never included in this report, and is not "
        "reproduced if this finding is accepted into a baseline.",
        "Still readable by anyone who can read this repository's history, even "
        "though it may no longer be present in the current files -- removing it "
        "from a later commit does not remove it from history. "
        + ("If it is real, treat it as compromised and rotate it first"
           if rule in _SHAPE_ONLY_RULES else
           "Treat the credential as compromised and rotate it first")
        + "; only rewriting history "
        "(git filter-repo or BFG Repo-Cleaner) and force-pushing, with "
        "collaborators re-cloning afterward, removes it from the repository "
        "itself. A false positive (a placeholder or already-rotated test value) "
        "can be silenced at the source with a `.gitleaksignore` entry for this "
        "fingerprint, which gitleaks will honor on the next scan.",
        f"gitleaks fingerprint: {fingerprint}",
    ]

    absolute = root / file_path if not file_path.is_absolute() else file_path
    return Finding(
        detector=DETECTOR,
        category=Category.COMMITTED_SECRET,
        layer=Layer.MECHANICAL,
        severity=Severity.MAJOR if rule in _SHAPE_ONLY_RULES else Severity.CRITICAL,
        status=Status.CONFIRMED,
        summary=summary,
        detail="\n".join(detail_lines),
        # Join keys for correlate.py. The fingerprint is gitleaks' own
        # identifier for one leak (commit:file:rule:line) and is what makes
        # "the same leak, in two repositories" a exact match rather than a
        # guess from prose. None of these is the secret itself.
        attributes={
            "fingerprint": fingerprint,
            "rule": rule,
            "commit": commit,
        },
        evidence=Evidence(
            file=str(absolute), line_start=line, line_end=end_line, snippet=rule,
        ),
    )


def scan(root: Path, *, gitleaks_path: Optional[str] = None,
         timeout: float = _TIMEOUT_DEFAULT) -> Tuple[List[Finding], SecretsScanReport]:
    """Scan `root`'s checked-out branch history for committed secrets with
    gitleaks. Returns (findings, report); `report.ran` is False -- never
    reported as a clean scan -- when the directory is not a git repository,
    gitleaks is not available, the run times out, or gitleaks itself fails.
    """
    # Resolved once, up front: gitleaks is given `--source str(root)` below
    # with no `cwd` set (it needs none -- `--source` alone fully specifies
    # the target). A relative root combined with a `cwd` pointed at that
    # same relative root used to resolve twice (root/root); resolving here
    # once removes the whole class of bug rather than papering over one
    # call site.
    root = Path(root).resolve()
    report = SecretsScanReport(ran=False)

    if not _is_git_repo(root):
        report.reason = f"{root} is not a git repository"
        return [], report

    binary = gitleaks_path or shutil.which("gitleaks")
    if not binary:
        report.reason = (
            "gitleaks is not installed (or not on PATH). Install it "
            "(https://github.com/gitleaks/gitleaks#installing) and rerun with "
            "--secrets, or point --secrets-binary at an existing install. "
            "Nothing here installs it automatically."
        )
        return [], report

    report.gitleaks_version = _gitleaks_version(binary)

    with tempfile.TemporaryDirectory(prefix="ghost_secrets_") as tmp:
        report_path = Path(tmp) / "report.json"
        cmd = [
            binary, "detect", "--source", str(root), "--no-banner",
            "--report-format", "json", "--report-path", str(report_path),
            "--redact", "--exit-code", "0",
        ]
        try:
            # No cwd: --source above is already absolute and is gitleaks'
            # only source of the target path, deliberately not doubled up
            # with cwd (see the resolve() comment above).
            proc = subprocess.run(
                cmd, capture_output=True, text=True, errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            report.reason = f"gitleaks did not finish within {timeout:.0f}s"
            return [], report
        except (OSError, ValueError) as e:
            report.reason = f"gitleaks could not be run: {type(e).__name__}: {e}"
            return [], report

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "no output").strip()
            report.reason = f"gitleaks exited {proc.returncode}: {tail[-500:]}"
            return [], report

        if not report_path.exists():
            report.reason = "gitleaks exited 0 but produced no report file"
            return [], report

        raw = report_path.read_text(encoding="utf-8", errors="replace")

    try:
        entries = json.loads(raw) if raw.strip() else []
    except ValueError as e:
        report.reason = f"gitleaks report was not valid JSON: {e}"
        return [], report

    if not isinstance(entries, list):
        report.reason = "gitleaks report was not a JSON array"
        return [], report

    findings = [f for f in (_finding(root, e) for e in entries if isinstance(e, dict)) if f]  # ghost_buster: name-disagreement -- `e` is `entry` in the signature
    report.ran = True
    report.leaks_found = len(findings)
    return findings, report


def render_report(report: SecretsScanReport) -> str:
    if not report.ran:
        return f"ghost_buster: secrets scan did not run: {report.reason}"
    plural = "" if report.leaks_found == 1 else "s"
    version = f" ({report.gitleaks_version})" if report.gitleaks_version else ""
    return f"ghost_buster: secrets scan{version} found {report.leaks_found} committed secret{plural}"
