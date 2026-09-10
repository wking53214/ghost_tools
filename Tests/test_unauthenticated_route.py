"""The handler somebody forgot, and the many handlers nobody forgot.

The obvious version of this check -- "report routes with no auth" -- is
unusable: a login endpoint has no auth by definition, and so do signup,
health probes, webhooks, OAuth callbacks, and every endpoint of every
public API. It fires dozens of times per repository and is right twice.

This detector reports INCONSISTENCY instead. Most of the tests below are
therefore about silence: the fully public module, the fully protected
module, and the module too small or too mixed to be claiming anything.
"""
from __future__ import annotations

import pytest

from ghost_buster.mechanical import detect_unauthenticated_route, run_all
from ghost_buster.schema import Severity

HEAD = "from fastapi import APIRouter, Depends\nrouter = APIRouter()\n\n"


def _route(name, method="get", auth=True):
    dep = "user = Depends(require_user)" if auth else ""
    return (f"@router.{method}('/{name}')\n"
            f"async def {name}({dep}):\n    return {{}}\n\n")


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _module(tmp_path, *specs, name="api.py"):
    body = HEAD + "".join(_route(n, auth=a) for n, a in specs)
    return _write(tmp_path, name, body)


# ------------------------------------------------------------- it fires

def test_the_one_forgotten_handler_is_reported(tmp_path):
    p = _module(tmp_path, ("list_users", True), ("create_user", True),
                ("delete_user", False), ("settings", True))
    findings = detect_unauthenticated_route([p])
    assert len(findings) == 1
    assert findings[0].attributes["route"] == "delete_user"
    assert findings[0].attributes["protected_siblings"] == "3"
    assert findings[0].attributes["routes_in_module"] == "4"
    assert findings[0].severity == Severity.MAJOR, (
        "an unprotected DELETE among protected siblings is the shape of a "
        "real breach, not a nit"
    )


def test_the_finding_points_at_the_handler(tmp_path):
    p = _module(tmp_path, ("a", True), ("b", True), ("c", False), ("d", True))
    f = detect_unauthenticated_route([p])[0]
    src = p.read_text().splitlines()
    assert src[f.evidence.line_start - 1].startswith("@router.get('/c')") or \
        src[f.evidence.line_start - 1].startswith("async def c")


def test_two_forgotten_handlers_are_two_findings(tmp_path):
    p = _module(tmp_path, ("a", True), ("b", True), ("c", True),
                ("d", False), ("e", False))
    assert {f.attributes["route"] for f in detect_unauthenticated_route([p])} == {"d", "e"}


@pytest.mark.parametrize("marker", [
    "@login_required", "@jwt_required", "@requires_auth", "@admin_required",
])
def test_decorator_style_auth_counts(tmp_path, marker):
    """Flask and its ecosystem attach auth as a decorator, not a parameter.
    A FastAPI-only rule would read every Flask router as fully public and
    say nothing at all."""
    body = "from flask import Blueprint\nbp = Blueprint('b', __name__)\n\n"
    for n in ("a", "b", "c"):
        body += f"@bp.route('/{n}')\n{marker}\ndef {n}():\n    return ''\n\n"
    body += "@bp.route('/d')\ndef d():\n    return ''\n"
    findings = detect_unauthenticated_route([_write(tmp_path, "views.py", body)])
    assert [f.attributes["route"] for f in findings] == ["d"]


# ---------------------------------------------------------- it stays quiet

def test_auth_inside_a_project_specific_wrapper_still_counts(tmp_path):
    """Teams routinely wrap Depends in a helper of their own. The wrapper
    name is not in the marker list and never will be, but `require_user`
    is right there inside it -- so the inner arguments are scanned too.

    Without this, such a module reads as fully public, falls below the
    majority gate, and the forgotten handler is never reported."""
    body = HEAD
    for n in ("a", "b", "c"):
        body += (f"@router.get('/{n}')\n"
                 f"async def {n}(user = resolve_dependency(require_user)):\n"
                 f"    return {{}}\n\n")
    body += "@router.delete('/d')\nasync def d():\n    return {}\n"
    findings = detect_unauthenticated_route([_write(tmp_path, "api.py", body)])
    assert [f.attributes["route"] for f in findings] == ["d"]


def test_a_fully_public_module_says_nothing(tmp_path):
    """health, login, docs. Nobody forgot anything here, and this is the
    shape that makes the naive version of this check unusable."""
    p = _module(tmp_path, ("health", False), ("login", False), ("docs", False))
    assert detect_unauthenticated_route([p]) == []


def test_a_fully_protected_module_says_nothing(tmp_path):
    p = _module(tmp_path, ("a", True), ("b", True), ("c", True))
    assert detect_unauthenticated_route([p]) == []


def test_a_half_and_half_module_says_nothing(tmp_path):
    """No clear claim about intent, so no basis for calling one a mistake."""
    p = _module(tmp_path, ("a", True), ("b", True), ("c", False), ("d", False))
    assert detect_unauthenticated_route([p]) == []


def test_a_module_with_too_few_routes_says_nothing(tmp_path):
    """With two routes, "most of them" is not a statement about anybody's
    intent -- it is one example."""
    p = _module(tmp_path, ("a", True), ("b", False))
    assert detect_unauthenticated_route([p]) == []


def test_auth_applied_by_middleware_is_invisible_and_fails_quiet(tmp_path):
    """If auth is attached somewhere this detector cannot see, every route
    reads as unprotected, the module falls below the protected majority,
    and nothing is reported. That is the designed failure direction."""
    p = _module(tmp_path, ("a", False), ("b", False), ("c", False), ("d", False))
    assert detect_unauthenticated_route([p]) == []


def test_plain_functions_are_not_routes(tmp_path):
    body = HEAD + _route("a", auth=True) + _route("b", auth=True) + _route("c", auth=True)
    body += "def helper():\n    return 1\n\n\ndef another():\n    return 2\n"
    assert detect_unauthenticated_route([_write(tmp_path, "api.py", body)]) == []


def test_test_files_are_skipped(tmp_path):
    p = _module(tmp_path, ("a", True), ("b", True), ("c", False), name="test_api.py")
    assert detect_unauthenticated_route([p]) == []


def test_an_unparseable_file_is_left_to_the_other_detector(tmp_path):
    assert detect_unauthenticated_route([_write(tmp_path, "broken.py", "def f(:\n")]) == []


def test_run_all_actually_calls_this_detector(tmp_path):
    p = _module(tmp_path, ("a", True), ("b", True), ("c", False), ("d", True))
    assert "unauthenticated_route" in {f.detector for f in run_all([p])}
