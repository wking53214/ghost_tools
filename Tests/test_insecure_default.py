"""Framework switches left in ship-mode.

This detector's whole value is that it is narrow. Every rule catches a
construct with essentially one meaning, so most of these tests are about
what it declines to say: the safe form of each pattern, and the same
pattern inside a test file where being permissive is usually the point.

Measured 2026-09-10 across ghost_tools, observe-perceive and
content-polish-pipeline: zero findings. A detector for this class is only
worth having if it stays silent on code that is fine.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ghost_buster.mechanical import detect_insecure_default
from ghost_buster.schema import Severity


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _kinds(findings):
    return {f.attributes["kind"] for f in findings}


# ------------------------------------------------------------- it fires

UNSAFE = [
    ("debug enabled", Severity.CRITICAL, "DEBUG = True\n"),
    ("host check disabled", Severity.MAJOR, 'ALLOWED_HOSTS = ["*"]\n'),
    ("debug enabled", Severity.CRITICAL, "def m(app):\n    app.run(debug=True)\n"),
    ("cors wide open with credentials", Severity.CRITICAL,
     'def w(app):\n    app.add_middleware(C, allow_origins=["*"], allow_credentials=True)\n'),
    ("tls verification disabled", Severity.MAJOR,
     "def f(u):\n    return requests.get(u, verify=False)\n"),
]


@pytest.mark.parametrize("kind,severity,src", UNSAFE, ids=[u[2][:28] for u in UNSAFE])
def test_the_unsafe_form_is_reported(tmp_path, kind, severity, src):
    findings = detect_insecure_default([_write(tmp_path, "settings.py", src)])
    assert len(findings) == 1
    assert findings[0].attributes["kind"] == kind
    assert findings[0].severity == severity


def test_flask_style_cors_keywords_are_recognised(tmp_path):
    """flask-cors spells the same two ideas `origins` and
    `supports_credentials`. A FastAPI-only rule would miss every Flask app."""
    src = 'def w(app):\n    CORS(app, origins="*", supports_credentials=True)\n'
    findings = detect_insecure_default([_write(tmp_path, "app.py", src)])
    assert _kinds(findings) == {"cors wide open with credentials"}


def test_the_finding_points_at_the_line(tmp_path):
    src = "import os\n\n\nDEBUG = True\n"
    f = detect_insecure_default([_write(tmp_path, "settings.py", src)])[0]
    assert f.evidence.line_start == 4


# ---------------------------------------------------------- it stays quiet

SAFE = [
    ("DEBUG read from the environment", 'import os\nDEBUG = os.environ.get("D") == "1"\n'),
    ("DEBUG explicitly off", "DEBUG = False\n"),
    ("hosts named", 'ALLOWED_HOSTS = ["example.com", "www.example.com"]\n'),
    ("server started without debug", "def m(app):\n    app.run()\n"),
    ("debug passed as a variable", "def m(app, d):\n    app.run(debug=d)\n"),
    ("any origin but NO credentials",
     'def w(app):\n    app.add_middleware(C, allow_origins=["*"], allow_credentials=False)\n'),
    ("credentials but named origins",
     'def w(app):\n    app.add_middleware(C, allow_origins=["https://a.com"], allow_credentials=True)\n'),
    ("verification left on", "def f(u):\n    return requests.get(u, verify=True)\n"),
]


@pytest.mark.parametrize("label,src", SAFE, ids=[s[0] for s in SAFE])
def test_the_safe_form_is_not_reported(tmp_path, label, src):
    assert detect_insecure_default([_write(tmp_path, "settings.py", src)]) == []


def test_wide_open_cors_without_credentials_is_not_reported(tmp_path):
    """Deliberate. A public read-only API with `allow_origins=["*"]` and no
    credentials is a normal, correct configuration. Reporting it would fire
    on every public API and teach people to skim this detector."""
    src = 'def w(app):\n    app.add_middleware(C, allow_origins=["*"])\n'
    assert detect_insecure_default([_write(tmp_path, "app.py", src)]) == []


@pytest.mark.parametrize("name", [
    "test_settings.py", "settings_test.py", "conftest.py",
    "tests/settings.py", "test/settings.py", "fixtures/settings.py",
])
def test_the_same_pattern_inside_a_test_is_not_reported(tmp_path, name):
    src = 'DEBUG = True\nALLOWED_HOSTS = ["*"]\n'
    assert detect_insecure_default([_write(tmp_path, name, src)]) == []


def test_a_file_that_cannot_be_parsed_is_left_to_the_other_detector(tmp_path):
    """Failing closed here is correct; unassessable_file is what makes the
    silence visible."""
    assert detect_insecure_default([_write(tmp_path, "broken.py", "def f(:\n")]) == []


def test_markdown_is_not_reported(tmp_path):
    """The body must be markdown that ALSO parses as Python, or this test
    passes whether the .py filter exists or not -- the file would simply
    fail to parse and be skipped for the wrong reason. Second time this
    exact trap has been caught by a mutant in this project's own suite."""
    prose = "# Settings\n\nDEBUG = True\n"
    import ast as _ast
    _ast.parse(prose)  # the fixture is only meaningful while this holds
    assert detect_insecure_default([_write(tmp_path, "README.md", prose)]) == []


def test_run_all_actually_calls_this_detector(tmp_path):
    """Every other test here calls the function directly, so all of them
    pass with the @register decorator removed and the detector wired to
    nothing."""
    from ghost_buster.mechanical import run_all
    p = _write(tmp_path, "settings.py", "DEBUG = True\n")
    detectors = {f.detector for f in run_all([p])}
    assert "insecure_default" in detectors


def test_ghost_tools_own_source_is_clean():
    """Measured zero across three real repositories. If this ever fires on
    this project, the rule has drifted wider than its documentation."""
    src = Path(__file__).resolve().parent.parent / "ghost_buster"
    assert detect_insecure_default(sorted(src.glob("*.py"))) == []
