"""testsuite.py -- test-status detection: run the project's pytest suite,
identify every test that did not pass, and say why.

WHY THIS IS A SEPARATE MODULE, NOT A mechanical.py DETECTOR
-------------------------------------------------------------
Every detector in mechanical.py is a pure function of parsed file
content. This check has to execute the project's own tests, so its input
is the project root and an interpreter, like branches.py (git plumbing)
and mutation.py (pytest in scratch copies). It is deterministic in what
it reports for what it observed, and every finding is Status.CONFIRMED,
so it is still "mechanical" in schema.py's sense; it is a separate module
because it runs code, and for that reason it is opt-in (`--tests`) and
never part of the default scan.

WHAT "DID NOT PASS" IS TAKEN TO MEAN
--------------------------------------
A test suite reports four kinds of not-passing, and each hides a
different ghost:

- A test that FAILS every time it runs is a failing test. That is the
  ordinary case and it is MAJOR.
- A test that fails, then passes when rerun alone, is FLAKY. It is
  reported separately from a failing test because the fix is different
  (order dependence, shared state, timing), and it is MAJOR because a
  flaky test is one that nobody believes when it fails.
- A test that fails every time because the environment lacks something
  it needs (a service that refused the connection, a module that is not
  installed, an environment variable that is not set) is BLOCKED. It is
  MINOR, and the finding says what is missing: the right fix is usually
  a `skipif` naming that dependency, so the suite's failure count means
  "broken", not "not configured".
- A test that is SKIPPED has nothing to rerun; the skip IS the outcome.
  A skip whose reason names an external dependency is INFORMATIONAL: it
  is recorded so the count is visible, and nothing more. A skip with no
  reason, or a reason like "TODO" or "flaky" that names no dependency,
  is MAJOR: that is a test switched off, not a test waiting on
  something. A skip whose reason names a module or environment variable
  that IS present when the scan runs is a STALE skip, MAJOR: the
  dependency arrived and the test never came back.
- An `xfail` that unexpectedly passes is a stale expectation, MAJOR. An
  `xfail` that fails as expected is INFORMATIONAL -- reported, but
  quietly. It is a recorded decision, not an unexplained absence, so it
  is not MAJOR on day one. It is reported at all so that the ledger can
  see it: an expected failure standing for two hundred runs is
  indistinguishable from one added yesterday if nothing is ever emitted,
  and `persistent_finding` can only age what it is told about. Measured
  2026-09-10: five pediatric missed detections moved from bare skips to
  named xfails, correctly stopped being MAJOR, and vanished from the
  report entirely -- the same silence one level up.
- A test file that cannot be collected at all (an import at module level
  raised) is reported the same way as a failing test, or as blocked when
  the import error names a missing module.

THE RERUN LOOP
----------------
Each failing test that is not already classified as blocked is rerun
alone, in its own pytest process, up to `reruns` times (default 3),
stopping at the first pass. Rerunning alone is deliberate: a test that
fails in the suite and passes alone is order-dependent or polluted by
another test, which the isolated rerun separates from true intermittent
failure only in the sense that both are reported as flaky; the detail
says how many reruns it took. A blocked test is not rerun, because a
missing service does not appear between attempts. Nothing here ever
installs a package, starts a service, or sets a variable: the finding
says what is missing, and providing it is the reader's call.

HOW THE OUTCOMES ARE READ
---------------------------
pytest is run with a small plugin (written to a temporary directory and
loaded with `-p`) that records one JSON line per test phase: node id,
phase, outcome, location, and the skip reason or failure text. That is
the same hook pytest's own junit writer uses. Parsing the terminal
summary would be fragile across pytest versions and verbosity settings,
and the junit XML does not carry node ids, which the rerun needs. The
target project's interpreter is used (`--tests-python`, default: the one
running ghost_buster), so a project with its own virtualenv is run with
its own dependencies.

WHAT THIS CANNOT SEE, STATED PLAINLY
--------------------------------------
Whether a failure is "external" is a heuristic over the failure text
and skip reason (the patterns are `_REASON_PATTERNS` and
`_FAILURE_PATTERNS`, and every finding that relies on one says which
matched). A test that fails for
lack of a service but reports it as a bare assertion will be reported as
failing, and a genuine bug whose traceback happens to mention a socket
will be reported as blocked. The presence probe for a stale skip checks
only what it can check without network: whether a named module imports
in the target interpreter, and whether a named environment variable is
set in ghost_buster's own environment (which the pytest run inherits).
It cannot tell whether a named service is reachable, and does not try.
The target project's tests run with whatever side effects they have; the
scan itself writes nothing into the project (no cache, no bytecode).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "test_status"

_PLUGIN_MODULE = "ghost_status_plugin"
_PLUGIN_SOURCE = '''
import json, os

_OUT = os.environ["GHOST_TEST_STATUS_OUT"]


def _write(record):
    with open(_OUT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\\n")


def _longrepr(report):
    longrepr = getattr(report, "longrepr", None)
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    text = getattr(report, "longreprtext", None)
    if text is None and longrepr is not None:
        text = str(longrepr)
    return (text or "")[-4000:]


def pytest_runtest_logreport(report):
    location = getattr(report, "location", None)
    _write({
        "nodeid": report.nodeid,
        "when": report.when,
        "outcome": report.outcome,
        "wasxfail": hasattr(report, "wasxfail"),
        # The REASON, separately from the boolean above. pytest sets
        # wasxfail to "" for a bare xfail with no reason given, so the
        # two cannot be collapsed into one field without losing the
        # difference between "expected to fail, here is why" and
        # "expected to fail, no reason recorded".
        "xfail_reason": str(getattr(report, "wasxfail", "") or ""),
        "location": list(location) if location else None,
        "text": _longrepr(report),
    })


def pytest_collectreport(report):
    if report.failed:
        _write({
            "nodeid": report.nodeid,
            "when": "collect",
            "outcome": "failed",
            "wasxfail": False,
            "location": None,
            "text": _longrepr(report),
        })
'''

# Two pattern sets, applied to two different kinds of text.
#
# A skip reason is short and written by a person ("requires Postgres",
# "needs DATABASE_URL set"), so a broad vocabulary is right for it.
#
# A failure text is a traceback: file paths, source lines, local names. On
# that text the same vocabulary is wrong -- a genuine assertion failure in
# test_server.py mentions "server" on every line -- so failures are
# classified only from their error lines (pytest's `E   ` lines and the
# final `path:line: ExceptionType` line), against exception types and
# phrases that name a missing dependency and little else.
#
# Order matters within each set: the first match names the dependency.
# Environment-variable patterns are case-sensitive on purpose (an all-caps
# token), and come first so "requires DATABASE_URL" is an env probe, not a
# module probe.
_REASON_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("env", re.compile(
        r"(?:\$|\b[Ee]nv(?:ironment)?\b.*?|os\.environ\S*)\s*[\"'\[]*([A-Z][A-Z0-9_]{2,})")),
    ("env", re.compile(r"\b([A-Z][A-Z0-9]*_[A-Z0-9_]*[A-Z0-9])\b")),
    ("env", re.compile(
        r"\b([A-Z][A-Z0-9_]{3,})\b(?=.*\b(?:set|unset|missing|required|configured|defined)\b)")),
    ("service", re.compile(
        r"connection refused|could not connect|\boffline\b|\bnetwork\b|\binternet\b|"
        r"\bpostgres|\bpsql\b|\bredis\b|\bmysql\b|\bmongo|\brabbitmq\b|\bkafka\b|"
        r"\belasticsearch\b|\bdocker\b|\bdatabase\b|\bdaemon\b|\bserver\b|\bservice\b|"
        r"\bbroker\b|\bs3\b|\baws\b|\bgcp\b|\bazure\b|\bapi key\b|\bapi_key\b|"
        r"\bcredentials?\b|\btoken\b|\bsecret\b|\blive\b", re.IGNORECASE)),
    ("resource", re.compile(
        r"\b([\w.-]+)\s+(?:checkout|repo(?:sitory)?|clone|dataset|fixture|corpus|weights?|"
        r"snapshot|data\s?dir(?:ectory)?)\s+(?:is |are )?(?:not available|unavailable|not found|"
        r"missing|not present|absent)|\bnot available\b|\bunavailable\b", re.IGNORECASE)),
    ("module", re.compile(
        r"no module named '?([A-Za-z_][\w.]*)'?|could not import '?([A-Za-z_][\w.]*)'?|"
        r"(?:requires|needs|missing|without|no)\s+(?:the\s+)?([A-Za-z_][\w.-]*)\s*"
        r"(?:package|module|library|installed|extra|not installed)\b", re.IGNORECASE)),
    ("module", re.compile(r"(?:requires|needs)\s+([A-Za-z_][\w.-]*)\s*$", re.IGNORECASE)),
    ("tool", re.compile(
        r"(?:command not found|not (?:found )?(?:in|on) path|not installed|no such file or "
        r"directory:|executable|binary|\bcli\b)", re.IGNORECASE)),
    ("platform", re.compile(
        r"\bwindows\b|\bmacos\b|\bdarwin\b|\blinux\b|\bposix\b|sys\.platform|\bplatform\b|"
        r"\bgpu\b|\bcuda\b|\bhardware\b|\barm64\b|\bx86|\bpython 3\.\d+", re.IGNORECASE)),
]

_FAILURE_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("module", re.compile(r"ModuleNotFoundError: No module named '([A-Za-z_][\w.]*)'")),
    ("env", re.compile(
        r"KeyError: '([A-Z][A-Z0-9_]{2,})'|"
        r"[Ee]nvironment variable[s]? '?\$?([A-Z][A-Z0-9_]{2,})'?|"
        r"\b([A-Z][A-Z0-9_]{3,})\b (?:is )?(?:not set|unset|missing|is required|must be set)")),
    ("service", re.compile(
        r"ConnectionRefusedError|ConnectionResetError|ConnectionAbortedError|"
        r"\bConnectionError\b|OperationalError|InterfaceError|socket\.gaierror|"
        r"\bgaierror\b|NewConnectionError|MaxRetryError|ConnectTimeout|ReadTimeout|"
        r"[Cc]onnection refused|[Cc]ould not connect|Name or service not known|"
        r"Temporary failure in name resolution|No route to host|Network is unreachable|"
        r"redis\.exceptions|psycopg2?\.|asyncpg\.|pymongo\.errors|kafka\.errors|"
        r"botocore\.exceptions|NoCredentialsError|AuthenticationError|"
        r"[Mm]issing (?:API|api) key|API key (?:is )?(?:not set|missing|required)")),
    ("tool", re.compile(
        r"command not found|is not installed|executable not found|"
        r"FileNotFoundError: \[Errno 2\] No such file or directory: '([^']+)'|"
        r"ImportError: [^\n]*\.(?:so|dylib|dll)\b")),
]

_TOOL_DIRS = ("/bin/", "/sbin/", "/usr/", "/opt/", "/snap/", "/Library/")


def _missing_path_is_a_tool(path: str) -> bool:
    """A FileNotFoundError names a tool when the path is a bare command name
    or sits under a system executable directory (measured on sentinel_os:
    18 setup errors on '/usr/local/bin/twin_ensure_services'). A missing
    relative file -- a fixture the repository was supposed to carry -- is
    the repository's own defect and reads as a genuine failure."""
    if "/" not in path and "\\" not in path:
        return True
    return any(marker in path for marker in _TOOL_DIRS)


@dataclass
class Dependency:
    kind: str       # service | module | env | tool | platform | resource
    name: str       # what was named, or "" when only the kind is known
    matched: str    # the text fragment that matched, for the finding's detail


@dataclass
class TestOutcome:
    nodeid: str
    outcome: str                  # passed | failed | error | skipped | xfailed | xpassed
    xfail_reason: str = ""        # why, when the outcome is xfailed; "" if none given
    file: Optional[str] = None
    line: Optional[int] = None    # 1-based
    text: str = ""                # skip reason or failure text
    when: str = "call"


@dataclass
class TestStatusReport:
    ran: bool
    reason: str = ""
    python: str = ""
    collected: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0
    reruns_performed: int = 0
    flaky: int = 0
    # Every isolated rerun, in order: which test, which attempt, what it
    # did. The scan used to keep this only in a temporary directory that
    # was deleted with the runner, so a flaky test's name survived nowhere
    # but a finding that could be filtered out of view. Measured
    # 2026-09-11: a scan reported "2 flaky" and two reruns later nothing
    # could say which two. The record is part of the report now.
    reruns: List["RerunRecord"] = field(default_factory=list)
    blocked: int = 0
    stale_skips: int = 0
    unjustified_skips: int = 0
    dependency_skips: int = 0
    pytest_exit: Optional[int] = None
    findings: List[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class RerunRecord:
    """One isolated rerun of one test that failed in the suite."""

    nodeid: str
    attempt: int
    outcome: str          # pytest's word for what the rerun did, or "no report"


def flaky_tests(report: TestStatusReport) -> List[str]:
    """The tests whose isolated rerun passed, in the order they were rerun."""
    seen: List[str] = []
    for r in report.reruns:
        if r.outcome in ("passed", "xpassed") and r.nodeid not in seen:
            seen.append(r.nodeid)
    return seen


def rerun_summary(report: TestStatusReport) -> str:
    """One line naming what was rerun and how it went, for the status line."""
    if not report.reruns:
        return ""
    by_test: Dict[str, List[str]] = {}
    for r in report.reruns:
        by_test.setdefault(r.nodeid, []).append(r.outcome)
    return "; ".join(f"{nodeid}: {' then '.join(outcomes)} on rerun"
                     for nodeid, outcomes in by_test.items())


class _PytestRunner:
    """One temporary directory holding the plugin, reused for every
    invocation of one scan."""

    def __init__(self, root: Path, python: str, timeout: float):
        self.root = root
        self.python = python
        self.timeout = timeout
        self._tmp = tempfile.TemporaryDirectory(prefix="ghost_tests_")
        self.tmpdir = Path(self._tmp.name)
        (self.tmpdir / f"{_PLUGIN_MODULE}.py").write_text(_PLUGIN_SOURCE, encoding="utf-8")
        self._n = 0
        self._local_modules: Optional[Dict[str, str]] = None

    def close(self) -> None:
        self._tmp.cleanup()

    def local_module_path(self, name: str) -> Optional[str]:
        """Where a top-level module of that name lives inside the scanned
        project, relative to the root, or None. One walk per scan."""
        if self._local_modules is None:
            self._local_modules = _index_local_modules(self.root)
        return self._local_modules.get(name)

    def pytest_importable(self) -> bool:
        try:
            proc = subprocess.run(
                [self.python, "-c", "import pytest"], cwd=self.root,
                capture_output=True, text=True, errors="replace", timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return False
        return proc.returncode == 0

    def module_importable(self, name: str) -> bool:
        try:
            proc = subprocess.run(
                [self.python, "-c", f"import {name}"], cwd=self.root,
                capture_output=True, text=True, errors="replace", timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return False
        return proc.returncode == 0

    def run(self, nodeids: Optional[List[str]] = None) -> Tuple[Optional[int], List[dict], str]:
        """Run pytest (the whole suite, or only `nodeids`). Returns
        (exit code or None on timeout/launch failure, records, stderr tail)."""
        self._n += 1
        out = self.tmpdir / f"run{self._n}.jsonl"
        env = dict(os.environ)
        env["GHOST_TEST_STATUS_OUT"] = str(out)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(self.tmpdir) + (os.pathsep + existing if existing else "")
        # --continue-on-collection-errors: without it one uncollectable test
        # module aborts the whole run before any test executes, and the
        # scan would report that module alone as the suite's entire status.
        cmd = [self.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", _PLUGIN_MODULE,
               "--continue-on-collection-errors"]
        cmd.extend(nodeids or [])
        try:
            proc = subprocess.run(
                cmd, cwd=self.root, capture_output=True, text=True, errors="replace",
                timeout=self.timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            return None, _read_records(out), f"timed out after {self.timeout:.0f}s"
        except (OSError, ValueError) as e:
            return None, [], f"{type(e).__name__}: {e}"
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        return proc.returncode, _read_records(out), tail


_SKIPPED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "env", ".env", "node_modules",
                 "__pycache__", "site-packages", ".tox", ".nox", "build", "dist",
                 ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _index_local_modules(root: Path) -> Dict[str, str]:
    """Top-level importable names defined by files in the project: `x.py`
    and `x/__init__.py`, mapped to the first path found (shallowest wins).
    Used to tell "this dependency is not installed" from "this module is
    right here and not on the import path" -- measured on gsa-815: 17 of
    its 19 test modules could not be collected for want of modules that
    were all files in the same repository."""
    index: Dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in _SKIPPED_DIRS and not d.endswith(".egg-info"))
        here = Path(dirpath)
        for d in dirnames:
            if (here / d / "__init__.py").exists():
                index.setdefault(d, str((here / d).relative_to(root)))
        for name in filenames:
            if name.endswith(".py") and name != "__init__.py":
                index.setdefault(name[:-3], str((here / name).relative_to(root)))
    return index


def _read_records(path: Path) -> List[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def _aggregate(records: List[dict]) -> Dict[str, TestOutcome]:
    """Fold per-phase records into one outcome per node id. A failure in
    setup or teardown is an error; a skip in any phase is a skip; xfail
    and xpass are read from the call phase's wasxfail flag."""
    outcomes: Dict[str, TestOutcome] = {}
    for rec in records:
        nodeid = rec.get("nodeid") or "<collection>"
        when = rec.get("when", "call")
        outcome = rec.get("outcome", "")
        loc = rec.get("location") or [None, None, None]
        file = loc[0] if loc and loc[0] else None
        line = (loc[1] + 1) if loc and isinstance(loc[1], int) else None
        text = rec.get("text") or ""
        current = outcomes.get(nodeid)
        if current is None:
            current = TestOutcome(nodeid=nodeid, outcome="passed", file=file, line=line, when=when)
            outcomes[nodeid] = current
        if file and not current.file:
            current.file, current.line = file, line
        if when == "collect":
            current.outcome, current.text, current.when = "error", text, "collect"
            if not current.file:
                current.file = nodeid.split("::", 1)[0] or None
        elif outcome == "failed":
            if current.outcome in ("failed", "error"):
                continue
            current.outcome = "failed" if when == "call" else "error"
            current.text, current.when = text, when
        elif outcome == "skipped":
            if current.outcome in ("failed", "error"):
                continue
            if rec.get("wasxfail"):
                current.outcome, current.text = "xfailed", text
                current.xfail_reason = str(rec.get("xfail_reason") or "")
            else:
                current.outcome, current.text, current.when = "skipped", text, when
        elif outcome == "passed" and when == "call" and rec.get("wasxfail"):
            if current.outcome == "passed":
                current.outcome, current.text = "xpassed", text
    return outcomes


def _strip_prefix(reason: str) -> str:
    reason = reason.strip()
    for prefix in ("Skipped: ", "skipped: ", "XFAIL ", "[XPASS(strict)] "):
        if reason.startswith(prefix):
            reason = reason[len(prefix):]
    return reason.strip()


def _error_lines(text: str) -> str:
    """pytest's `E   ` lines plus the final line of a longrepr: the part of
    a traceback that names the exception, without the source it walked."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    picked = [ln[1:].strip() for ln in lines if ln.startswith("E ")]
    picked.append(lines[-1])
    return "\n".join(picked)


def classify_dependency(text: str, *, failure: bool = False) -> Optional[Dependency]:
    """The external dependency a skip reason (or, with failure=True, a
    failure text) names, if any. Heuristic; see the module docstring."""
    if not text:
        return None
    if failure:
        text = _error_lines(text)
        patterns = _FAILURE_PATTERNS
    else:
        patterns = _REASON_PATTERNS
    for kind, pattern in patterns:
        m = pattern.search(text)
        if not m:
            continue
        name = next((g for g in m.groups() if g), "") if m.groups() else ""
        if kind == "tool" and "/" in name or "\\" in name:
            if not _missing_path_is_a_tool(name):
                continue
            name = name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        return Dependency(kind=kind, name=name, matched=m.group(0).strip())
    return None


def _is_unconditional_skip(reason: str) -> bool:
    """A skip with no reason, or one whose reason names nothing that could
    ever be provided."""
    if not reason or reason.lower() in ("unconditional skip", "skipped"):
        return True
    lowered = reason.lower()
    return any(word in lowered for word in (
        "todo", "fixme", "broken", "flaky", "wip", "later", "temporar", "not implemented",
        "not yet", "disabled", "hangs", "slow", "unfinished",
    ))


def _dependency_present(dep: Dependency, runner: _PytestRunner) -> bool:
    """Only what can be checked without network: a module imports in the
    target interpreter; an environment variable is set and non-empty."""
    if dep.kind == "module" and dep.name:
        top = dep.name.split(".")[0]
        return runner.module_importable(top)
    if dep.kind == "env" and dep.name:
        return bool(os.environ.get(dep.name))
    return False


def _evidence(root: Path, outcome: TestOutcome) -> Evidence:
    file = outcome.file or outcome.nodeid.split("::", 1)[0]
    path = Path(file)
    if not path.is_absolute():
        path = root / path
    return Evidence(file=str(path), line_start=outcome.line, line_end=outcome.line,
                    snippet=outcome.nodeid)


def _finding(root: Path, outcome: TestOutcome, kind: str, severity: Severity,  # ghost_buster: name-disagreement -- `summary` is `phase` at every call site
             summary: str, detail: str) -> Finding:
    return Finding(
        detector=DETECTOR,
        category=Category.TEST_STATUS,
        layer=Layer.MECHANICAL,
        severity=severity,
        status=Status.CONFIRMED,
        summary=f"{kind}: {outcome.nodeid} {summary}".rstrip(),
        detail=detail,
        # Join keys for correlate.py: `kind` is the classification this
        # module made ("failing test", "flaky test", ...), `phase` is which
        # pytest phase produced it -- "collect" is the one that means the
        # module could not even be imported, which is what a conflict
        # marker in that file looks like from here.
        attributes={
            "nodeid": outcome.nodeid,
            "kind": kind,
            "phase": outcome.when,
            "outcome": outcome.outcome,
        },
        evidence=_evidence(root, outcome),
    )


def _dependency_phrase(dep: Dependency) -> str:
    if dep.name:
        return f"{dep.kind} '{dep.name}'"
    return f"a {dep.kind} (matched {dep.matched!r})"


def _excerpt(text: str, limit: int = 600) -> str:
    text = text.strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def scan(root: Path, *, python: Optional[str] = None, reruns: int = 3,
         timeout: float = 900.0) -> Tuple[List[Finding], TestStatusReport]:
    """Run the project's pytest suite under `root` and report every test
    that did not pass, classified as described in the module docstring.

    Returns (findings, report). `report.ran` is False when the suite could
    not be run at all (no pytest for the interpreter, nothing collected,
    a usage error, a timeout), with the reason; that is never reported as
    a clean suite."""
    python = python or sys.executable
    root = Path(root)
    report = TestStatusReport(ran=False, python=python)
    runner = _PytestRunner(root, python, timeout)
    try:
        if not runner.pytest_importable():
            report.reason = f"pytest is not importable by {python}"
            return [], report

        exit_code, records, tail = runner.run()
        report.pytest_exit = exit_code
        if exit_code is None:
            report.reason = f"pytest did not finish: {tail}"
            return [], report
        if exit_code == 5:
            report.reason = "no tests collected"
            return [], report
        outcomes = _aggregate(records)
        if not outcomes:
            report.reason = (f"pytest exited {exit_code} without reporting any test "
                             f"(usage or internal error): {tail.strip()[-300:]}")
            return [], report

        report.ran = True
        findings: List[Finding] = []
        for outcome in outcomes.values():
            if outcome.when == "collect":
                report.errored += 1
            else:
                report.collected += 1
            counter = {"passed": "passed", "failed": "failed", "error": "errored",
                       "skipped": "skipped", "xfailed": "xfailed", "xpassed": "xpassed"}[outcome.outcome]
            if outcome.when != "collect":
                setattr(report, counter, getattr(report, counter) + 1)

            if outcome.outcome in ("failed", "error"):
                findings.append(_classify_failure(root, outcome, runner, reruns, report))
            elif outcome.outcome == "skipped":
                findings.append(_classify_skip(root, outcome, runner, report))
            elif outcome.outcome == "xfailed":
                findings.append(_finding(
                    root, outcome, "expected failure", Severity.INFORMATIONAL,
                    "fails as expected" + (
                        f" ({outcome.xfail_reason.strip()})" if outcome.xfail_reason.strip()
                        else ", with no reason recorded"),
                    "Not a problem today: somebody wrote down that this fails and why, "
                    "which is what an xfail is for and is strictly better than a skip. "
                    "It is emitted so that it can AGE. An expected failure carries no "
                    "clock of its own, so without a finding to track, one standing for "
                    "two hundred runs looks exactly like one added yesterday. With this, "
                    "the ledger raises persistent_finding once it has gone ten runs with "
                    "no decision recorded, and reports it as a regression if it is ever "
                    "closed and comes back.",
                ))
            elif outcome.outcome == "xpassed":
                findings.append(_finding(
                    root, outcome, "stale xfail", Severity.MAJOR, "passes",
                    "This test is marked xfail but passed. The expectation is stale: "
                    "either the bug it documented is fixed and the mark should go, or "
                    "the test no longer exercises it.",
                ))
        report.findings = findings
        return findings, report
    finally:
        runner.close()


def _classify_failure(root: Path, outcome: TestOutcome, runner: _PytestRunner,
                      reruns: int, report: TestStatusReport) -> Finding:
    phase = {"call": "fails", "setup": "errors in setup", "teardown": "errors in teardown",
             "collect": "cannot be collected"}.get(outcome.when, "fails")
    dep = classify_dependency(outcome.text, failure=True)
    local = runner.local_module_path(dep.name.split(".")[0]) if dep and dep.kind == "module" else None
    if dep is not None and dep.kind == "module" and local is not None:
        # Not a missing dependency: the module is a file in this repository
        # and the test cannot see it. A path or packaging defect, MAJOR.
        return _finding(
            root, outcome, "failing test", Severity.MAJOR,
            f"{phase}: module '{dep.name}' is in this repository but not on the import path",
            f"The failure names module '{dep.name}', and that module is at {local} inside the "
            "scanned project. Nothing is missing from the environment; the test's working "
            "directory or the package layout does not make it importable (a conftest.py, a "
            "PYTHONPATH entry, or an installable package usually is the fix). Not rerun: a path "
            "problem is not intermittent.\n\n" + _excerpt(outcome.text),
        )
    if dep is not None:
        report.blocked += 1
        return _finding(
            root, outcome, "blocked test", Severity.MINOR,
            f"{phase} for lack of {_dependency_phrase(dep)}",
            f"The failure text names {_dependency_phrase(dep)} (matched {dep.matched!r}). "
            "It was not rerun: a missing dependency does not appear between attempts. "
            "If the dependency is genuinely optional in this environment, a skipif that "
            "names it turns this from a failure into a documented skip; if it is required, "
            "provide it and rerun. Nothing was installed or started by this scan.\n\n"
            + _excerpt(outcome.text),
        )
    if outcome.when == "collect":
        return _finding(  # ghost_buster: name-disagreement -- `phase` is `summary` in the signature
            root, outcome, "failing test", Severity.MAJOR, phase,
            "The test module raised during collection, so none of its tests ran. "
            "Not rerun: a collection error is not intermittent.\n\n" + _excerpt(outcome.text),
        )
    attempts = 0
    for attempt in range(1, reruns + 1):
        attempts = attempt
        report.reruns_performed += 1
        exit_code, records, _ = runner.run([outcome.nodeid])
        again = _aggregate(records).get(outcome.nodeid)
        report.reruns.append(RerunRecord(outcome.nodeid, attempt,
                                         again.outcome if again is not None else "no report"))
        if exit_code == 0 and again is not None and again.outcome in ("passed", "xpassed"):
            report.flaky += 1
            return _finding(
                root, outcome, "flaky test", Severity.MAJOR,
                f"{phase} in the suite, passes when rerun alone",
                f"Failed in the full run, then passed on isolated rerun {attempt} of {reruns}. "
                "A test that fails in the suite and passes alone depends on order or on state "
                "another test leaves behind; a test that passes only on a later attempt is "
                "intermittent. Either way its failures are not believed.\n\n"
                + _excerpt(outcome.text),
            )
    rerun_note = (f"Rerun alone {attempts} time(s) and failed every time." if attempts
                  else "Not rerun (reruns=0).")
    return _finding(  # ghost_buster: name-disagreement -- `phase` is `summary` in the signature
        root, outcome, "failing test", Severity.MAJOR, phase,
        rerun_note + " The failure text names no external dependency, so this reads as a "
        "genuine failure.\n\n" + _excerpt(outcome.text),
    )


def _classify_skip(root: Path, outcome: TestOutcome, runner: _PytestRunner,
                   report: TestStatusReport) -> Finding:
    reason = _strip_prefix(outcome.text)
    if reason.lower() == "unconditional skip":
        # pytest's own wording for a bare @pytest.mark.skip; it is the
        # absence of a reason, not a reason.
        reason = ""
    dep = classify_dependency(reason)
    if dep is not None and _dependency_present(dep, runner):
        report.stale_skips += 1
        return _finding(
            root, outcome, "stale skip", Severity.MAJOR,
            f"is skipped for lack of {_dependency_phrase(dep)}, which is present",
            f"Skip reason: {reason!r}. The reason names {_dependency_phrase(dep)}, and that "
            + ("module imports in the interpreter that ran the suite."
               if dep.kind == "module" else "variable is set in the scan's environment.")
            + " The dependency arrived and the test never came back; the skip condition "
            "probably tests something other than what the reason says.",
        )
    if dep is not None:
        report.dependency_skips += 1
        return _finding(
            root, outcome, "skipped for a dependency", Severity.INFORMATIONAL,
            f"is skipped for lack of {_dependency_phrase(dep)}",
            f"Skip reason: {reason!r}. Recorded so the count is visible; the dependency "
            + ("was checked and is absent here." if dep.kind in ("module", "env")
               else "cannot be probed from here and was not.")
            + " Provide it and rerun to exercise this test.",
        )
    if _is_unconditional_skip(reason):
        report.unjustified_skips += 1
        return _finding(
            root, outcome, "skipped without a dependency reason", Severity.MAJOR,
            "is skipped" + (f" ({reason})" if reason else " with no reason"),
            f"Skip reason: {reason!r}. Nothing in the reason names a service, module, "
            "variable, tool, or platform that could be provided, so this is a test switched "
            "off rather than a test waiting on something. Either fix and unskip it, delete "
            "it, or give the skip a reason that names what it waits for.",
        )
    report.unjustified_skips += 1
    return _finding(
        root, outcome, "skipped without a dependency reason", Severity.MAJOR,
        f"is skipped ({reason})",
        f"Skip reason: {reason!r}. The reason does not name a dependency this scan "
        "recognizes (the patterns are in ghost_buster/testsuite.py). If it is waiting on "
        "something external, say what; if not, it is a test switched off.",
    )


def render_report(report: TestStatusReport) -> str:
    """One stderr line describing the run, in the style of the branch scan."""
    if not report.ran:
        return f"ghost_buster: test scan did not run: {report.reason}"
    parts = [f"{report.collected} collected", f"{report.passed} passed"]
    if report.failed:
        parts.append(f"{report.failed} failed")
    if report.errored:
        parts.append(f"{report.errored} errored")
    if report.skipped:
        parts.append(f"{report.skipped} skipped")
    if report.xfailed:
        parts.append(f"{report.xfailed} xfailed")
    if report.xpassed:
        parts.append(f"{report.xpassed} xpassed")
    classified = []
    if report.flaky:
        classified.append(f"{report.flaky} flaky: " + ", ".join(flaky_tests(report)))
    if report.blocked:
        classified.append(f"{report.blocked} blocked by a dependency")
    if report.stale_skips:
        classified.append(f"{report.stale_skips} stale skip(s)")
    if report.unjustified_skips:
        classified.append(f"{report.unjustified_skips} skip(s) naming no dependency")
    if report.dependency_skips:
        classified.append(f"{report.dependency_skips} skip(s) naming a dependency")
    line = f"ghost_buster: test scan ran {', '.join(parts)} ({report.reruns_performed} rerun(s))"
    if classified:
        line += "; " + ", ".join(classified)
    return line
