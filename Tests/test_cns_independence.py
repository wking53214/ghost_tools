"""ghost_tools is independent of CNS, and these tests hold whether or not CNS is installed.

The checks that need a fresh interpreter block ``cns`` outright
(``sys.modules['cns'] = None`` makes any import of it fail), so the result does not
depend on what the test environment happens to contain.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import textwrap
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

#: Written exactly as Warden writes its pin, so pip never sees two differing direct URLs.
CNS_PIN = "cns @ git+https://github.com/wking53214/CNS.git@v1.9.0"

BLOCK = ("import sys; sys.modules['cns'] = None; sys.modules['cns.gate'] = None; "
         "sys.modules['cns.finding'] = None\n")

PACKAGES = ("ghost_buster", "ghost_writer", "blackhole_extrapolator", "stack_census")


def _run(code: str, *, block: bool = True) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a fresh interpreter, with ``cns`` blocked outright unless told not to."""
    return subprocess.run(
        [sys.executable, "-c", (BLOCK if block else "") + textwrap.dedent(code)],
        capture_output=True, text=True, timeout=120,
        env={"PYTHONPATH": str(ROOT), "PATH": "", "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _ok(done: subprocess.CompletedProcess[str]) -> None:
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().endswith("ok"), done.stdout


def test_the_package_declares_no_runtime_dependency():
    assert CONFIG["project"]["dependencies"] == []


def test_the_cns_extra_is_the_shared_pin_and_nothing_else():
    assert CONFIG["project"]["optional-dependencies"]["cns"] == [CNS_PIN]


def test_the_extra_is_pinned_to_a_tag_or_a_full_commit():
    ref = CNS_PIN.rsplit("@", 1)[1]
    is_tag = ref.startswith("v") and ref[1:].replace(".", "").isdigit()
    is_commit = len(ref) == 40 and all(c in "0123456789abcdef" for c in ref)
    assert is_tag or is_commit, f"cns is pinned to {ref!r}, which can move"


def test_the_tests_workflow_installs_the_same_pin():
    text = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert f'python -m pip install "{CNS_PIN}"' in text


def test_the_publish_workflow_installs_no_extra():
    text = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "cns" not in text


def test_the_package_and_its_connector_import_with_cns_blocked():
    _ok(_run("import ghost_buster, ghost_buster.cns_adapter, ghost_buster.cli; print('ok')"))


def test_nothing_loads_cns_when_the_package_is_imported():
    done = _run(
        """
        import sys
        import ghost_buster, ghost_buster.cns_adapter, ghost_buster.cli, ghost_buster.schema
        loaded = sorted(m for m in sys.modules if m == "cns" or m.startswith("cns."))
        assert not loaded, loaded
        print('ok')
        """,
        block=False,
    )
    _ok(done)


def test_ghost_still_does_its_job_with_cns_blocked(tmp_path):
    (tmp_path / "m.py").write_text("def orphan_one():\n    return 1\n")
    done = _run(
        f"""
        import io, json, contextlib
        from ghost_buster import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main([{str(tmp_path)!r}, "--no-branches", "--no-tests", "--no-secrets",
                      "--no-project", "--no-correlate", "--no-structure", "--single-repo",
                      "--no-ledger", "--json"])
        report = json.loads(out.getvalue())
        assert report["findings"], report
        print('ok')
        """
    )
    _ok(done)


def test_the_existing_adapter_still_answers_with_cns_blocked():
    done = _run(
        """
        from ghost_buster import cns_adapter
        from ghost_buster.schema import Status
        assert cns_adapter.cns_available().ok is False
        r = cns_adapter.translate_status(Status.CONFIRMED, {"path": "a.py"})
        assert r.translation.authority == "advisory_only" and r.gate_result is None
        assert r.translation.cns_outcome == "pass"
        print('ok')
        """
    )
    _ok(done)


def test_each_cns_backed_function_says_what_is_missing_when_cns_is_blocked():
    done = _run(
        """
        from ghost_buster.cns_adapter import CnsNotInstalled, FindingGate, check_report, cns_chain
        for call in (FindingGate, cns_chain, lambda: check_report([])):
            try:
                call()
            except CnsNotInstalled as exc:
                assert "pip install 'ghost-tools[cns]'" in str(exc), exc
                assert isinstance(exc, ImportError)
            else:
                raise SystemExit("did not raise")
        print('ok')
        """
    )
    _ok(done)


def test_constructing_a_gate_fails_at_construction_not_at_first_use():
    done = _run(
        """
        from ghost_buster.cns_adapter import CnsNotInstalled, FindingGate
        try:
            FindingGate()
        except CnsNotInstalled:
            print('ok')
        """
    )
    _ok(done)


def _imports_of(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def test_no_module_imports_cns_by_statement():
    offenders = []
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            if any(n == "cns" or n.startswith("cns.") for n in _imports_of(path)):
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"these import cns by statement (use importlib, lazily): {offenders}"
