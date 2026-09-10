"""mechanical.py -- Layer 1: deterministic, AST-based detectors.

Every detector here is a pure function of the files on disk: same input,
same output, every time. No API calls, no LLM, nothing probabilistic --
which is exactly why every finding this layer produces is Status.CONFIRMED
(see schema.py's module docstring for why that's enforced, not just a
convention).

Stdlib only (ast, hashlib) -- no third-party dependency for v0.1. This
intentionally does NOT try to out-do purpose-built tools like vulture,
radon, or jscpd; it exists to prove the detector-registry pattern end to
end with real, working, non-trivial detectors. Swapping in (or adding)
a real dedicated tool behind the same Finding-producing interface later
is a compatible change, not a rewrite.
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from .schema import Category, Evidence, Finding, Layer, Severity, Status, _portable_path

DetectorFn = Callable[[List[Path]], List[Finding]]

_REGISTRY: Dict[str, DetectorFn] = {}


def register(name: str):
    def decorator(fn: DetectorFn) -> DetectorFn:
        _REGISTRY[name] = fn
        return fn
    return decorator


def registered_detectors() -> Dict[str, DetectorFn]:
    return dict(_REGISTRY)


def _parse(path: Path):
    """None means THIS DETECTOR COULD NOT ASSESS THIS FILE. It does not mean
    the file is clean. See detect_unassessable_file below, which is the only
    reason that distinction is visible to anyone."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _parse_failure(path: Path):
    """The reason _parse would return None, or None if it would succeed."""
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return None
    except SyntaxError as e:
        line = f" at line {e.lineno}" if e.lineno else ""
        return f"SyntaxError{line}: {e.msg}"
    except UnicodeDecodeError as e:
        return f"UnicodeDecodeError: not valid {e.encoding} at byte {e.start}"
    except (OSError, ValueError) as e:
        return f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Detector: unauthenticated_route -- the handler somebody forgot.
#
# WHY THIS DOES NOT LOOK FOR "ROUTES WITH NO AUTH"
#
# The obvious version of this check reports every route handler with no
# authentication attached. It is unusable. A login endpoint has no auth by
# definition. So does a signup form, a health probe, a webhook receiver, a
# password reset, an OAuth callback, a public docs page, a static asset
# route, and every endpoint of every public API in existence. The check
# fires dozens of times per repository, is right maybe twice, and the two
# are indistinguishable from the rest.
#
# What is worth reporting is INCONSISTENCY. When a module has several route
# handlers and MOST of them carry an authentication marker, a sibling
# without one is a different kind of object: not a public endpoint, but a
# handler somebody forgot. The author already decided this router needs
# auth -- they said so, repeatedly, right there in the same file.
#
# This makes the check quiet by construction. A fully public module says
# nothing (no signal). A fully protected module says nothing (nothing
# missing). Only the mixed case speaks, and only when the majority is
# protected, which is exactly the shape of the mistake.
# ---------------------------------------------------------------------------

#: Decorator/parameter names that mean "this route is authenticated". Matched
#: on the trailing attribute, so `deps.require_user` and `require_user` both
#: count, as do the common third-party spellings.
_AUTH_MARKERS = frozenset({
    "login_required", "auth_required", "authenticated", "requires_auth",
    "require_auth", "require_user", "require_login", "current_user",
    "get_current_user", "jwt_required", "token_required", "permission_required",
    "requires_authentication", "protected", "authorize", "authorized",
    "require_scope", "require_role", "require_permission", "admin_required",
    "staff_member_required", "verify_token", "check_auth", "IsAuthenticated",
    "Security", "HTTPBearer", "OAuth2PasswordBearer", "Depends",
})

#: Decorator attributes that mark a function as an HTTP route.
_ROUTE_ATTRS = frozenset({
    "route", "get", "post", "put", "patch", "delete", "head", "options",
    "websocket", "api_route",
})

#: The fraction of a module's routes that must be protected before a
#: sibling without auth counts as an omission rather than a design.
#:
#: This single number is also the minimum-routes gate, which is why there
#: is no separate one. Two mutants proved a `_MIN_ROUTES = 3` constant
#: could not change any outcome and deleted it: with two routes the most
#: protected a module can be while still having an unprotected sibling is
#: one of two, and 0.5 is already below this threshold. Three routes is
#: therefore the arithmetic floor, and stating it twice only created a
#: guard that looked load-bearing and was not.
_PROTECTED_MAJORITY = 0.6


def _decorator_names(node) -> List[str]:
    out = []
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute):
            out.append(target.attr)
        elif isinstance(target, ast.Name):
            out.append(target.id)
    return out


def _is_route(node) -> bool:
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr in _ROUTE_ATTRS:
            return True
    return False


def _auth_names(node) -> List[str]:
    """Every way this handler says it needs a caller identity: a decorator,
    or a parameter default like `user = Depends(require_user)`."""
    found = [n for n in _decorator_names(node) if n in _AUTH_MARKERS]
    args = getattr(node, "args", None)
    if args is not None:
        for default in list(args.defaults) + [d for d in args.kw_defaults if d]:
            call = default.func if isinstance(default, ast.Call) else default
            name = call.attr if isinstance(call, ast.Attribute) else getattr(call, "id", "")
            if name in _AUTH_MARKERS:
                found.append(name)
            if isinstance(default, ast.Call):
                for a in default.args:
                    inner = a.attr if isinstance(a, ast.Attribute) else getattr(a, "id", "")
                    if inner in _AUTH_MARKERS:
                        found.append(inner)
    return found


@register("unauthenticated_route")
def detect_unauthenticated_route(files: List[Path]) -> List[Finding]:
    out = []
    for path in sorted(f for f in files if f.suffix == ".py"):
        if _looks_like_a_test(path):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        routes = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_route(n)
        ]
        if not routes:
            continue
        protected = [n for n in routes if _auth_names(n)]
        if len(protected) / len(routes) < _PROTECTED_MAJORITY:
            continue    # the module is not claiming to be a protected one
        for node in routes:
            if _auth_names(node):
                continue
            out.append(Finding(
                detector="unauthenticated_route",
                category=Category.ARCHITECTURE,
                layer=Layer.MECHANICAL,
                severity=Severity.MAJOR,
                status=Status.CONFIRMED,
                summary=(f"{_portable_path(path)}: route '{node.name}' has no "
                         f"authentication, while {len(protected)} of "
                         f"{len(routes)} routes in this module do"),
                evidence=Evidence(
                    file=str(path),
                    line_start=getattr(node, "lineno", None),
                    line_end=getattr(node, "end_lineno", None),
                ),
                detail=(
                    "Reported because of the INCONSISTENCY, not the absence. A "
                    "route with no authentication is usually fine -- a login "
                    "form, a health probe, a webhook, a public API. What is "
                    "reported here is a handler whose siblings in the same "
                    "module are nearly all protected: the author already "
                    "decided this router needs a caller identity and said so "
                    "repeatedly, and this one does not say it.\n\n"
                    "Confirm before acting: an intentionally public endpoint "
                    "inside an otherwise protected router is a real and common "
                    "design (a status endpoint on an admin API). If that is "
                    "what this is, accept it into the baseline so the reason "
                    "is recorded, rather than leaving the question open.\n\n"
                    "Scope limits: authentication applied by middleware, by a "
                    "router-level dependency, or by a decorator this list does "
                    "not know is invisible here, and would make every route in "
                    "the module look unprotected -- in which case the module "
                    "falls below the protected majority and nothing is "
                    "reported at all. This check fails quiet, deliberately."
                ),
                attributes={
                    "route": node.name,
                    "protected_siblings": str(len(protected)),
                    "routes_in_module": str(len(routes)),
                },
            ))
    return out


# ---------------------------------------------------------------------------
# Detector: insecure_default -- a framework left in ship-mode.
#
# The shape this catches is not a subtle vulnerability. It is a switch that
# exists to make local development pleasant and was never turned back off:
# DEBUG=True serving stack traces and a template-injection console to the
# public internet, a CORS policy that accepts every origin WITH credentials,
# ALLOWED_HOSTS accepting any Host header, TLS verification disabled.
#
# DELIBERATELY NARROW. Every rule here is a construct with essentially one
# meaning, and each is skipped inside test files, where a permissive setting
# is usually the point of the test. "Probably insecure" patterns -- binding
# 0.0.0.0, a hardcoded string that looks like a key, a missing timeout --
# are left out: they are ambiguous, they fire constantly, and a detector
# people learn to skim is worth less than no detector.
# ---------------------------------------------------------------------------

#: name -> (severity, what is wrong, what to do)
_INSECURE_ASSIGNMENTS = {
    "DEBUG": (
        Severity.CRITICAL,
        "DEBUG is enabled at module level",
        "In Django and Flask this serves a full traceback, local variables and "
        "settings to anyone who triggers an error, and Werkzeug's debugger "
        "offers an interactive console. Read it from the environment and "
        "default it to off, so that forgetting to set it fails safe.",
    ),
    "ALLOWED_HOSTS": (
        Severity.MAJOR,
        "ALLOWED_HOSTS accepts any Host header",
        "Django's Host-header validation is what stops an attacker-controlled "
        "Host from poisoning password-reset links and cache keys. '*' turns it "
        "off entirely. Name the hosts you actually serve.",
    ),
}


def _is_true(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_star_list(node) -> bool:
    """['*'] or ('*',) or a bare '*'."""
    if isinstance(node, ast.Constant):
        return node.value == "*"
    if isinstance(node, (ast.List, ast.Tuple)):
        return any(isinstance(e, ast.Constant) and e.value == "*" for e in node.elts)
    return False


def _kwarg(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _looks_like_a_test(path: Path) -> bool:
    """A permissive setting inside a test is usually the subject of the test.
    Matched on the path, not the content, so a fixture string mentioning
    DEBUG does not exempt a real settings module."""
    parts = {p.lower() for p in path.parts}
    return (
        path.name.startswith("test_") or path.name.endswith("_test.py")
        or path.name == "conftest.py"
        or bool(parts & {"tests", "test", "testing", "fixtures"})
    )


@register("insecure_default")
def detect_insecure_default(files: List[Path]) -> List[Finding]:
    out = []
    for path in sorted(f for f in files if f.suffix == ".py"):
        if _looks_like_a_test(path):
            continue
        tree = _parse(path)
        if tree is None:
            continue   # unassessable_file says so; see that detector
        for node in ast.walk(tree):
            for kind, severity, summary, detail in _insecure_nodes(node):
                out.append(Finding(
                    detector="insecure_default",
                    category=Category.STALE_FLAG,
                    layer=Layer.MECHANICAL,
                    severity=severity,
                    status=Status.CONFIRMED,
                    summary=f"{_portable_path(path)}: {summary}",
                    evidence=Evidence(
                        file=str(path),
                        line_start=getattr(node, "lineno", None),
                        line_end=getattr(node, "end_lineno", None),
                    ),
                    detail=detail + (
                        "\n\nSkipped inside test files, where a permissive "
                        "setting is usually the point. If this file is a "
                        "development-only settings module, say so by name in "
                        "the baseline rather than by hoping nobody imports it."
                    ),
                    attributes={"kind": kind},
                ))
    return out


def _insecure_nodes(node):
    """Yields (kind, severity, summary, detail) for one AST node."""
    # DEBUG = True / ALLOWED_HOSTS = ["*"], at any level: a settings module
    # inside a function is still a settings module.
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id not in _INSECURE_ASSIGNMENTS:
                continue
            severity, summary, detail = _INSECURE_ASSIGNMENTS[target.id]
            if target.id == "DEBUG" and _is_true(node.value):
                yield "debug enabled", severity, summary, detail
            elif target.id == "ALLOWED_HOSTS" and _is_star_list(node.value):
                yield "host check disabled", severity, summary, detail

    if not isinstance(node, ast.Call):
        return

    # app.run(debug=True)
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name == "run" and _is_true(_kwarg(node, "debug")):
        yield ("debug enabled", Severity.CRITICAL,
               "the development server is started with debug=True",
               "Werkzeug's debugger exposes an interactive Python console to "
               "anyone who can reach an error page. This is a development "
               "server in any case; in production it should be behind a real "
               "WSGI/ASGI server with debug off.")

    # CORS: any origin AND credentials. Either alone is defensible; together
    # they hand every site on the internet an authenticated session.
    origins = _kwarg(node, "allow_origins") or _kwarg(node, "origins")
    creds = _kwarg(node, "allow_credentials") or _kwarg(node, "supports_credentials")
    if origins is not None and _is_star_list(origins) and _is_true(creds):
        yield ("cors wide open with credentials", Severity.CRITICAL,
               "CORS allows every origin AND credentials",
               "Any origin plus credentials means any site a logged-in user "
               "visits can read authenticated responses from this API. "
               "Browsers reject the literal combination, which is why it is so "
               "often 'fixed' by reflecting the request's Origin header back -- "
               "the same hole with the warning removed. List the origins you "
               "actually serve.")

    # verify=False on a TLS call
    verify = _kwarg(node, "verify")
    if isinstance(verify, ast.Constant) and verify.value is False:
        yield ("tls verification disabled", Severity.MAJOR,
               "TLS certificate verification is disabled (verify=False)",
               "Every connection made this way is open to interception: the "
               "certificate is fetched and ignored. Usually added to get past "
               "one self-signed certificate in development. Point at the CA "
               "bundle for that host instead.")


# ---------------------------------------------------------------------------
# Detectors: sql_injection and destructive_sql.
#
# WHY THESE TWO SHARE A FILE
#
# Both start from the same question -- is this string a SQL statement --
# and answer opposite halves of what can go wrong with one. The first is
# about a statement built from untrusted parts; the second about a
# statement whose scope is unbounded.
#
# SQL injection is named first in every 2026 survey of AI-written code,
# for a reason that is structural rather than moral: a model reproduces
# the patterns in its training data, an f-string is by far the most
# common way SQL appears in that data, and "make it work" never asks for
# a parameterised query.
#
# The check is unusually clean because the safe form and the unsafe form
# are different AST shapes, not different values:
#
#     execute(f"SELECT * FROM t WHERE id = {uid}")   <- one argument, built
#     execute("SELECT * FROM t WHERE id = ?", (uid,)) <- two, parameterised
#
# No heuristic, no threshold, no guessing about intent. A literal with no
# interpolation is fine however it is written; interpolation into a
# statement is the finding.
# ---------------------------------------------------------------------------

_SQL_EXECUTORS = frozenset({
    "execute", "executemany", "executescript", "raw", "execute_query",
    "exec_driver_sql",
})

#: A string is treated as SQL only if it opens with a statement keyword.
#: Matching "select" anywhere would flag every sentence containing the word.
_SQL_START = re.compile(
    r"^\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|MERGE|WITH)\b",
    re.IGNORECASE)

_DELETE_NO_WHERE = re.compile(
    r"^\s*DELETE\s+FROM\s+[\w.\"`\[\]]+\s*(?:;|\Z)", re.IGNORECASE)
_UPDATE_NO_WHERE = re.compile(
    r"^\s*UPDATE\s+[\w.\"`\[\]]+\s+SET\b(?![\s\S]*\bWHERE\b)", re.IGNORECASE)
_TRUNCATE = re.compile(r"^\s*TRUNCATE\s+(?:TABLE\s+)?[\w.\"`\[\]]+", re.IGNORECASE)


def _static_sql(node) -> Optional[str]:
    """The statement text, if this node is a SQL string with no runtime
    parts. Returns None for anything interpolated -- those are the other
    detector's business and their scope cannot be read statically."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if _SQL_START.search(node.value) else None
    if isinstance(node, ast.JoinedStr):
        return None
    return None


def _interpolated_sql_parts(node):
    """(how it was built, the SQL text) when this node is a SQL statement
    assembled at runtime, else None."""
    if isinstance(node, ast.JoinedStr):
        literal = "".join(v.value for v in node.values
                          if isinstance(v, ast.Constant) and isinstance(v.value, str))
        has_expr = any(isinstance(v, ast.FormattedValue) for v in node.values)
        if has_expr and _SQL_START.search(literal):
            return "f-string", literal
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        # Walk to the leftmost operand. `"SELECT ..." + a + b` parses as
        # BinOp(BinOp(Constant, a), b), so checking node.left directly finds
        # a BinOp and misses the statement entirely -- which it did, on the
        # single most common way this bug is written by hand.
        left = node.left
        while isinstance(left, ast.BinOp) and isinstance(left.op, (ast.Add, ast.Mod)):
            left = left.left
        text = left.value if isinstance(left, ast.Constant) and isinstance(left.value, str) else ""
        if text and _SQL_START.search(text):
            return ("concatenation" if isinstance(node.op, ast.Add) else "%-formatting"), text
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in ("format", "join"):
        target = node.func.value
        if isinstance(target, ast.Constant) and isinstance(target.value, str) \
                and _SQL_START.search(target.value):
            return ".format()", target.value
    return None


def _sql_call_arguments(node: ast.Call):
    """Yields the argument nodes of a call that executes SQL."""
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name in _SQL_EXECUTORS and node.args:
        yield from node.args


@register("sql_injection")
def detect_sql_injection(files: List[Path]) -> List[Finding]:
    """A SQL statement assembled from runtime parts and handed to a driver.

    Not reported: a statement built at runtime and never executed here
    (it may be parameterised by the caller), and a parameterised call,
    however ugly the surrounding code. The finding is interpolation INTO
    a statement THAT IS EXECUTED.
    """
    out = []
    for path in sorted(f for f in files if f.suffix == ".py"):
        if _looks_like_a_test(path):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for arg in _sql_call_arguments(node):
                built = _interpolated_sql_parts(arg)
                if built is None:
                    continue
                how, text = built
                out.append(Finding(
                    detector="sql_injection", category=Category.OTHER,
                    layer=Layer.MECHANICAL, severity=Severity.CRITICAL,
                    status=Status.CONFIRMED,
                    summary=(f"{_portable_path(path)}: SQL built by {how} and then "
                             f"executed ({text.strip()[:60]!r})"),
                    evidence=Evidence(file=str(path),
                                      line_start=getattr(node, "lineno", None),
                                      line_end=getattr(node, "end_lineno", None)),
                    detail=(
                        "Whatever is interpolated becomes part of the statement, "
                        "not a value in it. A single quote in the interpolated "
                        "text ends the literal and everything after it is SQL.\n\n"
                        "The fix is the same length as the bug: pass the values as "
                        "the driver's second argument and let it bind them.\n\n"
                        "    execute(\"... WHERE id = ?\", (uid,))      # sqlite, mysql\n"
                        "    execute(\"... WHERE id = %s\", (uid,))     # psycopg\n\n"
                        "Scope limit: a value this detector cannot see may already "
                        "be validated or quoted upstream. That is a reason to check "
                        "before dismissing, not a reason to assume it is safe -- "
                        "upstream validation is one refactor away from being gone, "
                        "and the binding is not."
                    ),
                    attributes={"built_by": how, "statement": text.strip()[:120]},
                ))
    return out


@register("destructive_sql")
def detect_destructive_sql(files: List[Path]) -> List[Finding]:
    """DELETE or UPDATE with no WHERE clause, or TRUNCATE, in an executed
    statement. Every row, every time."""
    out = []
    for path in sorted(f for f in files if f.suffix == ".py"):
        if _looks_like_a_test(path):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for arg in _sql_call_arguments(node):
                text = _static_sql(arg)
                if text is None:
                    continue
                for pattern, kind, what in (
                    (_DELETE_NO_WHERE, "unbounded delete", "DELETE with no WHERE clause"),
                    (_UPDATE_NO_WHERE, "unbounded update", "UPDATE with no WHERE clause"),
                    (_TRUNCATE, "truncate", "TRUNCATE"),
                ):
                    if not pattern.search(text):
                        continue
                    out.append(Finding(
                        detector="destructive_sql", category=Category.OTHER,
                        layer=Layer.MECHANICAL, severity=Severity.MAJOR,
                        status=Status.CONFIRMED,
                        summary=(f"{_portable_path(path)}: {what} is executed here "
                                 f"({text.strip()[:60]!r})"),
                        evidence=Evidence(file=str(path),
                                          line_start=getattr(node, "lineno", None),
                                          line_end=getattr(node, "end_lineno", None)),
                        detail=(
                            "This affects every row in the table, every time it "
                            "runs. Nothing about the call site says so, which is "
                            "why it survives review: the statement reads as "
                            "ordinary maintenance until the day it runs against "
                            "production.\n\nSometimes that is exactly what is "
                            "wanted -- clearing a cache table, resetting a fixture "
                            "in a script. Then say so by accepting it into the "
                            "baseline, so the intent is recorded next to the "
                            "statement rather than living in somebody's memory."
                            "\n\nOnly reported for a literal statement: an "
                            "interpolated one may carry a WHERE clause this scan "
                            "cannot see, and sql_injection has more urgent things "
                            "to say about it anyway."
                        ),
                        attributes={"kind": kind, "statement": text.strip()[:120]},
                    ))
                    break
    return out


# ---------------------------------------------------------------------------
# Detector: unassessable_file -- a file every AST detector silently skipped.
#
# BORROWED, KNOWINGLY, FROM A PEDIATRIC SEPSIS ENGINE.
#
# observe-perceive's BayesianFusion carries this comment:
#
#     An engine that returns abstained=True is saying "I have no data to
#     assess this patient" -- which is fundamentally different from "this
#     patient looks stable." Previously, three low-confidence abstentions
#     could outvote a single high-confidence septic-shock detection.
#
# ghost_buster had exactly that bug in a different costume. _parse() returns
# None on a file it cannot read, every AST detector skips that file, and the
# run reports nothing about it. Measured 2026-09-10 on three files -- one
# clean, one with conflict markers, one with a syntax typo -- the typo file
# produced no findings whatsoever while the header still said "scanning 3
# file(s)". Its dead function was invisible. Silence read as all-clear.
#
# The clinical engine's fix is to make abstention explicit and refuse to fuse
# it into the verdict. This detector is the same fix: abstention becomes a
# finding rather than an absence. Every other detector still fails closed,
# which is correct -- what was wrong was that nobody was told.
#
# It matters most exactly when it fires. A file that will not parse is
# usually broken RIGHT NOW, which is the worst possible moment for every
# structural check to quietly look away.
# ---------------------------------------------------------------------------

@register("unassessable_file")
def detect_unassessable_file(files: List[Path]) -> List[Finding]:
    out = []
    for path in sorted(f for f in files if f.suffix == ".py"):
        reason = _parse_failure(path)
        if reason is None:
            continue
        out.append(Finding(
            detector="unassessable_file",
            category=Category.OTHER,
            layer=Layer.MECHANICAL,
            severity=Severity.MAJOR,
            status=Status.CONFIRMED,
            summary=(f"{_portable_path(path)} could not be parsed, so every "
                     f"structural detector skipped it ({reason})"),
            evidence=Evidence(file=str(path)),
            detail=(
                "This is an ABSTENTION, not a clean result. The file was counted "
                "in the scan total and contributed nothing to it: dead code, "
                "duplication, long functions and every other AST check silently "
                "passed over it, and without this finding the output would be "
                "identical to a file that was checked and found fine.\n\n"
                "Usual causes, in order: the file is genuinely broken right now "
                "(a syntax error, or conflict markers that also break parsing); "
                "it targets a different Python version than the interpreter "
                "running the scan; or it is a template with placeholders rather "
                "than real source. The first is urgent. The third is worth "
                "excluding by name so the abstention stops being reported."
            ),
            attributes={"reason": reason},
        ))
    return out


# ---------------------------------------------------------------------------
# Detector: dead_code -- module-level functions/classes defined but never
# referenced anywhere else in the scanned file set.
# ---------------------------------------------------------------------------

@register("dead_code")
def detect_dead_code(files: List[Path]) -> List[Finding]:
    """Flags a module-level def/class whose name never appears as an
    identifier anywhere else in the scanned set.

    DELIBERATELY CONSERVATIVE, false-negatives over false-positives:
    - dunder methods, test_* functions, and anything starting with
      leading underscore-free public names re-exported via __all__ are
      excluded from consideration as "never referenced" even if a
      naive scan would miss the reference (dynamic dispatch, string-based
      lookup, decorators, __all__ export).
    - CLASSES DECLARING Protocol OR ABC AS A BASE ARE EXCLUDED ENTIRELY
      (v0.1.1, added after a real false-positive run against ANVIL): an
      interface/Protocol class's whole purpose is often to have ZERO
      references within the file that defines it -- external implementers
      are the intended consumers, and this detector has no visibility
      into other repos. Flagging every Protocol/ABC as "dead" produced
      pure noise on real code (GovernanceModule(Protocol) in ANVIL.py,
      confirmed). Matched by simple base-expression name, not real type
      resolution -- this is an AST-only tool by design.
    - A STRING CONSTANT USED AS A SUBSCRIPT KEY counts as a reference too
      (v0.1.1, same ANVIL run): `registry["SomeName"]` is a real,
      extremely common dynamic-dispatch pattern (dict-based registries,
      plugin lookups, and -- the exact case found live -- a validation
      harness that loads a module via exec() into a dict and pulls names
      out by string key rather than a normal import). This does not
      attempt to trace exec()/importlib specifically; it generalizes past
      that one case to anything keying a lookup by a name-shaped string
      literal, which covers considerably more real dynamic-dispatch code
      than special-casing exec() alone would.
    - A name is "referenced" if it appears as an ast.Name/ast.Attribute,
      OR as a string-constant ast.Subscript key, ANYWHERE else in the
      corpus, including in the same file (covers self-reference,
      recursive helpers, internal use) -- this detector only flags things
      that look completely unreferenced, not merely privately-scoped.
    - Only module-level defs are considered (not methods) -- a method
      that's part of a class's public interface can be legitimately
      "unreferenced" in-repo (called by external consumers), and
      flagging every unused method would produce overwhelming noise for
      a v0.1. This is a real, disclosed scope limit, not an oversight.
    - Residual, still disclosed and not fixed by the above: getattr-by-
      string and decorator-based registration (this tool's own
      @register pattern is the concrete example -- it self-flags on
      ghost_buster's own codebase, see README) are still untraced.
    """
    definitions: Dict[str, List[Path]] = {}
    referenced_names: Set[str] = set()
    exported_names: Set[str] = set()

    def _is_protocol_or_abc(class_node: ast.ClassDef) -> bool:
        for base in class_node.bases:
            base_name = base.id if isinstance(base, ast.Name) else (
                base.attr if isinstance(base, ast.Attribute) else None
            )
            if base_name in ("Protocol", "ABC"):
                return True
        return False

    parsed = {}
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        parsed[path] = tree

    for path, tree in parsed.items():
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith("__") and node.name.endswith("__"):
                    continue
                if node.name.startswith("test_") or node.name.startswith("Test"):
                    continue
                if isinstance(node, ast.ClassDef) and _is_protocol_or_abc(node):
                    continue
                definitions.setdefault(node.name, []).append(path)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    exported_names.add(elt.value)

    for path, tree in parsed.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                referenced_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced_names.add(node.attr)
            elif isinstance(node, ast.Subscript):
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    referenced_names.add(key.value)

    findings: List[Finding] = []
    for name, def_paths in definitions.items():
        if name in exported_names:
            continue
        if name in referenced_names:
            continue
        for path in def_paths:
            findings.append(Finding(
                detector="dead_code",
                category=Category.DEAD_CODE,
                layer=Layer.MECHANICAL,
                severity=Severity.MINOR,
                status=Status.CONFIRMED,
                summary=f"'{name}' is defined but never referenced anywhere in the scanned set",
                detail=(
                    "No ast.Name, ast.Attribute, or string-subscript-key node "
                    "anywhere in the scanned files resolves to this identifier. "
                    "Scope limit: getattr-by-string and decorator-based "
                    "registration are still not traced, so this can false-"
                    "positive on names only reached that way -- confirm before "
                    "deleting."
                ),
                evidence=Evidence(file=str(path)),
            ))
    return findings


# ---------------------------------------------------------------------------
# Detector: long_function -- functions whose body exceeds a line-count
# threshold, a cheap, real proxy for the "Long Method" smell.
# ---------------------------------------------------------------------------

@register("long_function")
def detect_long_functions(files: List[Path], threshold: int = 80) -> List[Finding]:
    """Flags any function/method whose body spans more than `threshold`
    source lines (end_lineno - lineno). Not cyclomatic complexity (that
    needs control-flow-graph construction, out of scope for v0.1's
    stdlib-only constraint) -- line count is a cruder but real, honest
    proxy, and is disclosed as such in every finding's detail text.
    """
    findings: List[Finding] = []
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno is None:
                    continue
                length = node.end_lineno - node.lineno
                if length > threshold:
                    findings.append(Finding(
                        detector="long_function",
                        category=Category.COMPLEXITY,
                        layer=Layer.MECHANICAL,
                        severity=Severity.MINOR if length < threshold * 2 else Severity.MAJOR,
                        status=Status.CONFIRMED,
                        summary=f"'{node.name}' spans {length} lines (threshold {threshold})",
                        detail=(
                            "Line-count proxy for the 'Long Method' smell, not true "
                            "cyclomatic complexity -- a long function that's mostly "
                            "a flat sequence of simple statements is a weaker "
                            "signal than a short function with deep branching. "
                            "Treat as a prompt to look, not a verdict."
                        ),
                        evidence=Evidence(
                            file=str(path), line_start=node.lineno, line_end=node.end_lineno,
                        ),
                    ))
    return findings


# ---------------------------------------------------------------------------
# Detector: near_duplicate_function -- functions with structurally
# identical bodies (same AST shape modulo names/literals) in different
# locations.
# ---------------------------------------------------------------------------

def _shape(n: ast.AST):
    """AST shape of one node with Name/Constant/Attribute leaf values
    erased -- the single normalization both _structural_fingerprint
    (whole functions) and _block_fingerprint (statement runs within one
    function) build on, so there is exactly one definition of "same
    shape" in this file rather than two that could drift apart.
    """
    if isinstance(n, ast.Name):
        return ("Name",)
    if isinstance(n, ast.Constant):
        return ("Constant", type(n.value).__name__)
    if isinstance(n, ast.Attribute):
        return ("Attribute", _shape(n.value))
    fields = []
    for field_name, value in ast.iter_fields(n):
        if isinstance(value, ast.AST):
            fields.append(_shape(value))
        elif isinstance(value, list):
            fields.append(tuple(
                _shape(v) if isinstance(v, ast.AST) else v for v in value
            ))
        else:
            fields.append(value if isinstance(value, (int, float, bool, type(None))) else None)
    return (type(n).__name__, tuple(fields))


def _structural_fingerprint(node: ast.AST) -> str:
    """A hash of a function body's AST *shape*, with all Name/Constant/
    Attribute leaf values erased -- two functions with the same control
    flow and statement structure but different variable names or literal
    values fingerprint identically. This is deliberately coarser than a
    real clone-detection tool (no token-level near-miss handling, no
    minimum-size normalization) -- it catches the "copy-pasted then
    renamed" shape, which is the specific pattern the research flagged
    as the hard-to-find near-duplicate case, and nothing subtler.
    """
    return hashlib.sha256(repr(_shape(node)).encode("utf-8")).hexdigest()


def _block_fingerprint(stmts: List[ast.stmt]) -> str:
    """Same normalization as _structural_fingerprint, applied to a run of
    statements rather than a whole function -- see
    detect_intra_function_duplicate_blocks for why this exists."""
    return hashlib.sha256(
        repr(tuple(_shape(s) for s in stmts)).encode("utf-8")
    ).hexdigest()


def _is_test_file(path: Path) -> bool:
    """A test module by the same convention mutation.py uses, plus a
    tests/ or test/ directory component."""
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part.lower() in ("tests", "test") for part in path.parts[:-1])


def _identical_file_groups(files: List[Path]) -> List[Tuple[str, List[Path]]]:
    """(sha256, group) for every set of 2+ scanned files with byte-identical
    content. The digest is carried out so the finding can publish it as a
    join key -- correlate.py matches a leaked file against its twins on it. Measured on
    the first whole-library run (37 repositories): 31 such groups, almost
    all a module vendored verbatim from a sibling repo (sentinel_os and
    gsa-815 share queue_staffing_bayes_integration.py; sentinel_os and
    observe-perceive share perceive_consolidated.py). Every function in
    such a file fingerprinted identically to its twin, so one duplicated
    file was surfacing as N near_duplicate_function findings that said
    nothing about the real event -- the whole file is a copy."""
    by_hash: Dict[str, List[Path]] = {}
    for path in files:
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if not content:
            # Two empty __init__.py files are not a duplication; measured:
            # 4 of the first 35 groups on the library were exactly that.
            continue
        by_hash.setdefault(hashlib.sha256(content).hexdigest(), []).append(path)
    return [(digest, group) for digest, group in by_hash.items() if len(group) > 1]


@register("duplicate_file")
def detect_duplicate_files(files: List[Path]) -> List[Finding]:
    """One finding per group of byte-identical scanned files -- the
    signal near_duplicate_function was drowning in until v0.9 (see
    _identical_file_groups). A vendored verbatim copy of a sibling repo's
    module is the "parallel unreconciled implementation" risk in its
    purest form: two copies, one of which will be fixed and the other
    won't. MAJOR for that reason. A file that appears twice only because
    a symlinked directory was scanned twice is not this -- the CLI
    collects each real path once, so it never reaches here."""
    findings: List[Finding] = []
    for digest, group in _identical_file_groups(files):
        group = sorted(group)
        # Portable paths, not absolute: the summary is part of the finding
        # id, so an absolute path here made every duplicate_file id depend
        # on the checkout's location -- the same defect _portable_path was
        # written to fix for evidence.file.
        names = ", ".join(_portable_path(str(p)) for p in group)
        size = group[0].stat().st_size
        findings.append(Finding(
            detector="duplicate_file",
            category=Category.DUPLICATION,
            layer=Layer.MECHANICAL,
            severity=Severity.MAJOR,
            status=Status.CONFIRMED,
            summary=f"{len(group)} files are byte-identical ({size} bytes): {names}",
            detail=(
                "Same content, byte for byte. Typical real cause: a module copied "
                "verbatim from a sibling repository, or a whole directory duplicated "
                "instead of imported. Whichever copy gets the next fix, the other "
                "won't."
            ),
            attributes={
                "content_sha256": digest,
                "group_size": str(len(group)),
                "size_bytes": str(size),
            },
            evidence=Evidence(file=str(group[0]), related_files=[str(p) for p in group[1:]]),
        ))
    return findings


@register("near_duplicate_function")
def detect_near_duplicate_functions(files: List[Path], min_lines: int = 10) -> List[Finding]:
    """Groups functions by structural fingerprint; any group with 2+
    members is a near-duplicate cluster. min_lines guards against every
    trivial one-line getter/setter fingerprinting identically and
    burying real findings -- small functions are supposed to look alike;
    that's not a ghost.

    Three calibrations from the first whole-library run (37 repositories,
    v0.9), each measured before it was adopted:
      - files that are byte-identical to another scanned file are
        represented once here (duplicate_file reports the file itself):
        625 findings became 418;
      - min_lines 6 became 10: 418 became 248. Nothing in the dropped
        band, sampled by hand, was more than two short functions that
        happened to share a shape;
      - a cluster made only of test functions is INFORMATIONAL, never
        MAJOR: test functions sharing a setup/assert shape is what a test
        suite looks like, and the README had already disclosed it as the
        detector's dominant noise. MAJOR findings went from 42 to 27.
    """
    representatives: List[Path] = []
    seen_twins = set()
    for _digest, group in _identical_file_groups(files):
        for path in sorted(group)[1:]:
            seen_twins.add(path)
    representatives = [p for p in files if p not in seen_twins]

    by_fingerprint: Dict[str, List[tuple]] = {}
    for path in representatives:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno is None:
                    continue
                if (node.end_lineno - node.lineno) < min_lines:
                    continue
                fp = _structural_fingerprint(node)
                by_fingerprint.setdefault(fp, []).append((path, node))

    findings: List[Finding] = []
    for fp, occurrences in by_fingerprint.items():
        if len(occurrences) < 2:
            continue
        # One label per OCCURRENCE, not per unique (file, name) pair --
        # v0.1.2 bug fix, found via a real run against HERALD's own test
        # suite: two distinct nested functions both happened to be named
        # `thread_b` in the same file (a legitimate, common pattern --
        # multiple similarly-shaped test functions each defining their
        # own locally-scoped helper of the same name). The original
        # `{f"{p.name}:{n.name}"}` SET silently collapsed both into one
        # identical string, producing a finding that claimed "2 functions
        # share..." while naming only one -- correct occurrence count,
        # misleading/incomplete label. Line numbers make every label
        # unique by construction; a plain list (not a set) means no
        # future case can silently lose an occurrence this way again.
        names = [f"{p.name}:{n.lineno}:{n.name}" for p, n in occurrences]
        primary_path, primary_node = occurrences[0]
        if all(_is_test_file(p) for p, _ in occurrences):
            severity = Severity.INFORMATIONAL
        elif len(occurrences) > 2:
            severity = Severity.MAJOR
        else:
            severity = Severity.MINOR
        findings.append(Finding(
            detector="near_duplicate_function",
            category=Category.DUPLICATION,
            layer=Layer.MECHANICAL,
            severity=severity,
            status=Status.CONFIRMED,
            summary=(
                f"{len(occurrences)} functions share identical AST structure "
                f"(names/literals differ, control flow and shape don't): {', '.join(names)}"
            ),
            detail=(
                "Structural fingerprint match, not textual diff -- this is the "
                "'copy-pasted then renamed' shape specifically. Confirm these are "
                "actually solving the same problem before merging; some structural "
                "matches are coincidental (e.g. two unrelated simple validators)."
            ),
            evidence=Evidence(
                file=str(primary_path), line_start=primary_node.lineno,
                line_end=primary_node.end_lineno,
                related_files=[str(p) for p, _ in occurrences[1:]],
            ),
        ))
    return findings


# ---------------------------------------------------------------------------
# Detector: intra_function_duplicate_block -- v0.2, added for a real gap
# near_duplicate_function cannot see: repeated statement runs that live
# INSIDE one function (e.g. sibling if/elif branches that each hand-build
# the same shape of object) rather than being duplicated across two whole
# functions. near_duplicate_function fingerprints entire function bodies,
# so six near-identical ~9-line blocks inside one function's six verdict
# branches are invisible to it -- confirmed live: this exact pattern in
# HERALD's gate.py (six branches of submit(), each hand-constructing a
# GateDecision with the same authorization_mac=_sign_decision(...) call)
# was found by reading the code during triage, not by ghost_buster, and
# was flagged at the time as a v0.2 gap worth closing.
# ---------------------------------------------------------------------------

_BLOCK_FIELD_NAMES = ("body", "orelse", "finalbody")


def _stmt_blocks(func_node: ast.AST) -> Iterable[List[ast.stmt]]:
    """Every list-of-statements belonging to a function's OWN scope: its
    own body, plus the body/orelse/finalbody of every nested if/for/while/
    try/with inside it, plus each except-handler's body. Each is a
    candidate for "the same block repeated" -- a sibling if/elif branch is
    exactly one of these lists, which is the shape the gate.py case
    actually had.

    Recurses only through statement lists (body/orelse/finalbody/handler
    bodies), never through ast.walk -- ast.walk cannot be pruned, so using
    it here would still surface a nested function's inner blocks (they're
    descendants of func_node regardless of what a visitor does when it
    reaches the FunctionDef node itself). Recursing through the AST's own
    body/orelse/finalbody structure means a nested def/async def is simply
    never entered: it has no such field on the *statements around it* to
    recurse through, and is itself skipped explicitly below. That nested
    function is still analyzed -- as its own `func` in the caller's outer
    loop over the module -- just not folded into this function's set.

    Scope limit, not fixed here: constructs whose bodies aren't a plain
    list of statements (match-case bodies, comprehensions) are not
    descended into. Rare in practice and left as a known residual rather
    than adding a special case for every AST shape in a v0.2 detector.
    """
    def blocks_in(stmts: List[ast.stmt]) -> Iterable[List[ast.stmt]]:
        yield stmts
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for field_name in _BLOCK_FIELD_NAMES:
                value = getattr(stmt, field_name, None)
                if value:
                    yield from blocks_in(value)
            for handler in getattr(stmt, "handlers", []):
                if handler.body:
                    yield from blocks_in(handler.body)

    yield from blocks_in(func_node.body)


def _node_count(node: ast.AST) -> int:
    """Size of a statement's own subtree, in AST nodes -- the complexity
    signal _stmt_candidates uses instead of (or alongside) raw statement
    count. A single `return Decision(a=..., b=..., mac=sign(...))`
    statement can easily be 30-50 nodes; a bare `x = 1` is 3-4. Counting
    nodes catches "this one statement is doing a lot" in a way counting
    statements never can, since a statement count of 1 looks identical
    for both."""
    return 1 + sum(_node_count(c) for c in ast.iter_child_nodes(node))


def _stmt_candidates(
    func_node: ast.AST, min_statements: int, min_complexity: int
) -> Iterable[Tuple[int, List[ast.stmt]]]:
    """Every comparison unit worth fingerprinting inside one function,
    tagged with the index of the statement list it came from: whole
    sibling blocks of >= min_statements statements (a duplicated
    multi-statement branch body), AND individual statements whose own
    subtree has >= min_complexity nodes (a duplicated single complex
    statement -- see module comment above detect_intra_function_
    duplicate_blocks for why this second case was added: it is not an
    edge case, it is the shape the real motivating bug actually had).

    The block index is what lets the detector tell "the same statement in
    two different branches" (the gate.py shape) from "several similar
    statements in a row in one block" (an __init__ assigning seven
    attributes, a dict built one entry per line) -- see
    detect_intra_function_duplicate_blocks.
    """
    for block_index, block in enumerate(_stmt_blocks(func_node)):
        if len(block) >= min_statements:
            yield block_index, block
        for stmt in block:
            if _node_count(stmt) >= min_complexity:
                yield block_index, [stmt]


@register("intra_function_duplicate_block")
def detect_intra_function_duplicate_blocks(
    files: List[Path], min_statements: int = 3, min_complexity: int = 20
) -> List[Finding]:
    """Within each function independently, groups statement-list blocks
    (if/elif/else bodies, try/except/finally bodies, for/while bodies,
    with bodies) AND individual complex statements by structural
    fingerprint. A group of 2+ is the same "copy this, tweak the values,
    repeat" shape near_duplicate_function is blind to, because no single
    occurrence is a whole function.

    v0.2's first design only compared runs of >= min_statements sibling
    statements. Live-checked against the actual motivating case -- the
    six branches of HERALD gate.py's pre-fix submit(), each hand-building
    a GateDecision -- and it found NOTHING: every branch there was one
    `return GateDecision(...)` statement, a statement COUNT of 1, however
    deeply nested the call inside it. A pure statement-count floor is
    blind to "the interesting duplication is one large statement, not a
    run of several", so min_complexity (AST subtree size of a single
    statement) is compared alongside min_statements, not instead of it --
    both real shapes exist and neither subsumes the other.

    Deliberately scoped to ONE function at a time, not the whole file or
    repo: the confirmed real case was sibling branches within one
    function, and going wider (matching a unit in function A against one
    in function B) is a materially different, noisier claim -- "two
    functions happen to share a sub-shape" is a much weaker signal than
    "this one function repeats itself" -- left for a future version if
    it turns out to matter.

    Two calibrations from the first whole-library run (37 repositories,
    v0.9), each measured before it was adopted:
      - a single statement counts as repeated only across DISTINCT
        statement lists (different branch bodies), never within one.
        The motivating case was six branches each building the same
        object; what the detector was actually reporting, 643 times out
        of 655, was several similar statements in a row in one block --
        an __init__ assigning seven attributes, a dict built one entry
        per line. Those are how code is written, not a ghost. Findings
        went from 1,300 to 421 on the library;
      - min_complexity 15 became 20. The original gate.py's four branch
        returns measured 41, 26, 33 and 22 nodes, so 20 keeps every one
        of them (25 would have lost one); 421 became 221, MAJOR from 89
        to 46.
    Multi-statement blocks are unchanged: 30 findings on the library
    before and after, every one a real repeated branch body.
    """
    findings: List[Finding] = []
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            by_fingerprint: Dict[str, List[List[ast.stmt]]] = {}
            blocks_of: Dict[str, Set[int]] = {}
            for block_index, unit in _stmt_candidates(func, min_statements, min_complexity):
                fp = _block_fingerprint(unit)
                by_fingerprint.setdefault(fp, []).append(unit)
                blocks_of.setdefault(fp, set()).add(block_index)

            for fp, units in by_fingerprint.items():
                if len(units) < 2:
                    continue
                if len(units[0]) == 1 and len(blocks_of[fp]) < 2:
                    continue  # one block repeating a statement is a list, not a ghost
                spans = [f"{u[0].lineno}-{u[-1].lineno}" for u in units]
                first = units[0]
                shape_note = (
                    "single statement" if len(first) == 1
                    else f"{len(first)}-statement block"
                )
                findings.append(Finding(
                    detector="intra_function_duplicate_block",
                    category=Category.DUPLICATION,
                    layer=Layer.MECHANICAL,
                    severity=Severity.MAJOR if len(units) > 2 else Severity.MINOR,
                    status=Status.CONFIRMED,
                    summary=(
                        f"'{func.name}' repeats the same {shape_note} "
                        f"{len(units)} times (lines {', '.join(spans)}): "
                        "same shape, names/literals differ"
                    ),
                    detail=(
                        "Structural fingerprint match within one function, not a "
                        "whole-function match (near_duplicate_function's detection "
                        "is blind to this shape). Typical real cause: several "
                        "branches each hand-build the same kind of object or "
                        "perform the same sequence of calls -- worth a single "
                        "shared helper if the branches really are doing the same "
                        "thing, not just a coincidental resemblance."
                    ),
                    evidence=Evidence(
                        file=str(path), line_start=first[0].lineno,
                        line_end=first[-1].lineno,
                        related_files=[f"{path}:{s}" for s in spans[1:]],
                    ),
                ))
    return findings


# ---------------------------------------------------------------------------
# Detector: doc_test_count_drift -- v0.3. A mechanical, deterministic
# instance of doc/reality drift: a markdown file claims a specific number
# of tests exist ("135 tests passing"), and the number of test_* functions
# actually in the scanned .py files has since grown well past it.
#
# Found live, by hand, doing exactly the taxonomy-driven scrub this
# detector now automates: HERALD's README said "Version 0.3.0. 135 tests
# passing" while `python3 -m pytest --collect-only -q` reported 321.
# git log showed why -- 15 commits touched Tests/ after the README's last
# version-bump commit (an HMAX adversarial-test campaign), and the count
# claim was simply never revisited. This is the same "documentation
# describes a system that no longer exists" failure the semantic layer's
# doc_drift already names (same Category.DOC_DRIFT), but semantic doc_drift
# requires an LLM call AND a human-supplied code summary to compare
# against -- it cannot self-drive a whole-repo scrub. A number in a
# markdown file next to the word "test(s)" is instead a fully mechanical,
# zero-ambiguity check: no API key, no judgment call, Status.CONFIRMED.
# ---------------------------------------------------------------------------

_TEST_COUNT_CLAIM_RE = re.compile(
    r"\b(\d+)\s+tests?\b(?=\s*[,.]|\s+(?:passing|passed|collected))",
    re.IGNORECASE,
)

# A number followed by "tests" is not automatically a claim about how many
# tests this suite has NOW. Four shapes look identical to the regex above
# and mean something else entirely; each of the first three was a real
# false positive on this project's own docs, found by running the detector
# against ghost_tools itself:
#
#   "gained 13 tests"            a delta, not a total
#   "went from 255 to 272 tests" a recorded transition, true when written
#   'claimed "135 tests"'        another project's stale claim, quoted here
#                                as the example this detector was built from
#
# Flagging these is worse than saying nothing: the finding is false, and
# the doc_count_contradicted_by_run connector built on top of it then
# recommends writing the current count over a number that was correct.
# Measured on ghost_tools: all three of its doc_test_count_drift findings,
# and all three correlations, were this.
#
# Each pattern must match IMMEDIATELY before the number (trailing `$`
# against the text preceding it), which keeps them narrow -- a live claim
# rarely has one of these words adjacent to its count.
_CLAIM_LOOKBACK = 80

_NOT_A_CURRENT_CLAIM = (
    ("delta", re.compile(
        r"\b(?:gained|gains|gain|added|adds|add|grew|grown|grows|growing|plus|minus|"
        r"removed|removes|dropped|drops|another|extra|net|more|fewer)\b\s*(?:by\s+)?$",
        re.IGNORECASE)),
    ("transition", re.compile(
        r"(?:\bfrom\s+\d+\s+to\s+|\b\d+\s*(?:->|-->|\u2192)\s*)$", re.IGNORECASE)),
    # Quote characters only -- NOT the backtick. A markdown code fence ends
    # in backticks, so including it suppressed the live "519 tests" claim
    # sitting right under a ```bash block in this project's own README:
    # a false negative, and the one outcome worse than the false positives
    # these rules exist to remove.
    ("quotation", re.compile(r"[\"'\u201c\u2018]\s*$")),
    ("attribution", re.compile(r"\b(?:claimed|reported|said)\s*$", re.IGNORECASE)),
)


def claim_shape(before: str) -> Optional[str]:
    """The reason a "N tests" claim preceded by `before` is not about the
    current suite ("delta", "transition", "quotation", "attribution"), or
    None if it reads as a live claim. See _NOT_A_CURRENT_CLAIM above.

    Takes the preceding text rather than (text, offset) so that anything
    holding only a finding can re-run the same judgement -- correlate.py's
    doc_count_contradicted_by_run does exactly that, re-checking rather
    than trusting that its input was filtered.
    """
    for reason, pattern in _NOT_A_CURRENT_CLAIM:
        if pattern.search(before):
            return reason
    return None


def claim_context(text: str, start: int) -> str:
    """The text immediately before a claim, as claim_shape() wants it."""
    return text[max(0, start - _CLAIM_LOOKBACK):start]


def _count_test_functions(files: List[Path]) -> int:
    """Static, conservative LOWER BOUND on the real test count: every
    function (module-level or a method) named test_* in the scanned .py
    files. A lower bound, not an exact match to pytest's own collection,
    because @pytest.mark.parametrize expands one function into several
    collected cases -- the true number can only be higher than this, never
    lower, which is exactly the property detect_doc_test_count_drift needs
    to flag an undercount claim without false-positiving on parametrize
    making a once-correct claim look artificially low.
    """
    count = 0
    for path in files:
        if path.suffix != ".py":
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    count += 1
    return count


@register("doc_test_count_drift")
def detect_doc_test_count_drift(
    files: List[Path], min_growth_ratio: float = 1.15, min_absolute_growth: int = 10
) -> List[Finding]:
    """Flags a markdown "N tests passing/collected" (or "N tests,") claim
    once the real, statically-counted test_* function count has grown well
    past it. Deliberately one-directional: only flags UNDERcounts (real >
    documented), never overcounts. _count_test_functions is a lower bound
    (see its docstring -- parametrize can only push the true count higher),
    so a documented number ABOVE the static count is not necessarily wrong
    and is not flagged; a documented number this far BELOW the static count
    is unambiguously stale regardless of parametrize.

    Both min_growth_ratio and min_absolute_growth must be cleared (an AND,
    not an OR) before flagging -- guards against flagging a doc that is
    merely a commit or two behind (normal, not a ghost) versus one that
    has been stale across an entire campaign of new tests (the real case
    this was built from: 135 documented vs. 256 statically counted, a
    parametrize-inclusive pytest run reporting 321).
    """
    md_files = [p for p in files if p.suffix.lower() == ".md"]
    if not md_files:
        return []
    actual = _count_test_functions(files)
    if actual == 0:
        return []

    findings: List[Finding] = []
    for path in md_files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _TEST_COUNT_CLAIM_RE.finditer(text):
            documented = int(match.group(1))
            if documented == 0:
                continue
            before = claim_context(text, match.start())
            if claim_shape(before) is not None:
                continue
            if actual < documented * min_growth_ratio:
                continue
            if actual - documented < min_absolute_growth:
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append(Finding(
                detector="doc_test_count_drift",
                category=Category.DOC_DRIFT,
                layer=Layer.MECHANICAL,
                severity=Severity.MINOR,
                status=Status.CONFIRMED,
                summary=(
                    f"'{path.name}' claims {documented} test(s), but at least "
                    f"{actual} test_* function(s) exist in the scanned .py files "
                    "-- this claim is stale"
                ),
                detail=(
                    "actual is a static AST lower bound (functions named test_*, "
                    "counted directly, no pytest run) -- the true collected count "
                    "can only be higher (pytest.mark.parametrize expands one "
                    "function into several cases), never lower, so this can only "
                    "under-flag, not over-flag. Confirm by running the real suite "
                    "and update the claim, or remove the specific number if it "
                    "will keep going stale."
                ),
                attributes={
                    "documented_count": str(documented),
                    "static_lower_bound": str(actual),
                    # The text this claim sits in, so a consumer can re-run
                    # claim_shape() itself instead of assuming the claim was
                    # already filtered. correlate.py does.
                    "claim_context": " ".join(before.split()),
                },
                evidence=Evidence(
                    file=str(path), line_start=line, line_end=line,
                    snippet=" ".join((before + match.group(0)).split())[-160:],
                ),
            ))
    return findings


# ---------------------------------------------------------------------------
# Detector: merge_conflict_marker -- an unresolved git conflict marker
# (<<<<<<< / ======= / >>>>>>>) left in a committed file.
# ---------------------------------------------------------------------------

_CONFLICT_OURS = re.compile(r"^<{7}(?:\s.*)?$")
_CONFLICT_SEP = re.compile(r"^={7}$")
_CONFLICT_THEIRS = re.compile(r"^>{7}(?:\s.*)?$")


def _next_matching(lines: List[str], pattern: "re.Pattern[str]", start: int) -> Optional[int]:
    """Index of the first line at or after `start` matching `pattern`, or
    None. Shared by both marker lookups below -- they are the same
    operation ("find the next line of this shape") against two different
    patterns, not two independent pieces of logic."""
    return next((j for j in range(start, len(lines)) if pattern.match(lines[j])), None)


@register("merge_conflict_marker")
def detect_merge_conflict_markers(files: List[Path]) -> List[Finding]:
    """Flags an unresolved conflict-marker triplet: a `<<<<<<<` line,
    followed later by a `=======` line, followed later by a `>>>>>>>`
    line, in that order, anywhere in the same file.

    THE ONE DETECTOR HERE THAT DOES NOT CALL _parse(), ON PURPOSE
    -------------------------------------------------------------------
    Every other detector in this module starts from an AST. A file that
    genuinely still has an unresolved conflict marker in it is, in
    virtually every real case, no longer valid Python -- the marker lines
    are not legal syntax, so `ast.parse()` raises and `_parse()` fails
    closed to None. Going through `_parse()` here would mean this
    detector finds nothing in exactly the files most likely to have the
    problem. So this one reads the file as plain text and never touches
    `ast` at all.

    WHY A TRIPLET, NOT ANY ONE MARKER LINE BY ITSELF
    -----------------------------------------------------
    `=======` alone is a real false-positive risk: a Setext-style Markdown
    H1 underline is any run of `=` characters, and one that happens to be
    exactly 7 long is indistinguishable from git's separator line on its
    own. Requiring the full shape in order -- the same discipline the
    widely-used `pre-commit-hooks` project's own check-merge-conflict hook
    uses, for the same reason -- means a lone `=======` proves nothing,
    but the triplet essentially never occurs by coincidence. A stray
    `<<<<<<<` with no `=======`/`>>>>>>>` after it (a truncated file, or a
    doc showing one marker line as an isolated example) is deliberately
    not flagged either, for the same reason.

    Each marker line must be the WHOLE line: exactly 7 of the character,
    then nothing or a space and a label, never "at least 7" and never
    "somewhere in the line". This is what keeps this detector from firing
    on prose that mentions `<<<<<<<` inline, in backticks, in the middle
    of a sentence -- text like that never starts a physical source line
    with the bare marker, so it never matches. Confirmed by running this
    detector against mechanical.py itself, this docstring included, after
    it was written.

    A diff3-style conflict (`git config merge.conflictstyle diff3`) adds
    a fourth marker line, `|||||||`, between `<<<<<<<` and `=======` --
    already handled without special-casing it, since finding `=======`
    only requires it to appear somewhere after `<<<<<<<`, not immediately
    after.
    """
    findings: List[Finding] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            if not _CONFLICT_OURS.match(lines[i]):
                i += 1
                continue
            ours_line = i
            sep_line = _next_matching(lines, _CONFLICT_SEP, ours_line + 1)
            theirs_line = (
                _next_matching(lines, _CONFLICT_THEIRS, sep_line + 1)
                if sep_line is not None else None
            )
            if sep_line is None or theirs_line is None:
                i = ours_line + 1
                continue
            findings.append(Finding(
                detector="merge_conflict_marker",
                category=Category.MERGE_CONFLICT_MARKER,
                layer=Layer.MECHANICAL,
                severity=Severity.CRITICAL,
                status=Status.CONFIRMED,
                summary=f"unresolved merge conflict marker in {path.name}",
                detail=(
                    f"lines {ours_line + 1}-{theirs_line + 1}: a <<<<<<< / ======= / "
                    ">>>>>>> triplet is still in this file. Whatever is between the "
                    "markers is almost certainly not the intended content, and in a "
                    ".py file this line shape alone is very likely a syntax error."
                ),
                evidence=Evidence(
                    file=str(path), line_start=ours_line + 1, line_end=theirs_line + 1,
                    snippet=lines[ours_line][:200],
                ),
            ))
            i = theirs_line + 1
    return findings


# Registered here rather than decorated in naming.py, so that module keeps
# importing nothing but the schema and cannot form a cycle with this one.
# Both abstain rather than guess: the vestigial check needs at least two
# cassettes to tell a domain's vocabulary from the engine's, and returns
# nothing at all when a tree has no seam to check against.
from .naming import (                                            # noqa: E402
    DISAGREEMENT_DETECTOR, PLACEHOLDER_DETECTOR, VESTIGIAL_DETECTOR,
    detect_name_disagreements, detect_placeholder_names,
    detect_vestigial_domain_names,
)

register(VESTIGIAL_DETECTOR)(detect_vestigial_domain_names)
register(PLACEHOLDER_DETECTOR)(detect_placeholder_names)
# Sees more the wider the scan: within one repository it finds what crosses
# its files, and under --join or an ecosystem scan it finds what crosses
# repositories, which is where the two-names-for-one-thing problem lives.
register(DISAGREEMENT_DETECTOR)(detect_name_disagreements)


def run_all(files: Iterable[Path]) -> List[Finding]:
    """Run every registered mechanical detector against the given file
    list. Detectors are independent and order-independent by design
    (see registered_detectors)."""
    file_list = list(files)
    findings: List[Finding] = []
    for name, fn in registered_detectors().items():
        findings.extend(fn(file_list))
    return findings
