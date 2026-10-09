"""dead_code flags names that something outside the Python call graph reaches.

The sample repo is the red team's: Warden commented out a console script, a
plugin, a settings.yaml function and a getattr target because no test ran them.
"""
from __future__ import annotations

import json
import textwrap

from ghost_buster import cli as buster_cli
from ghost_buster.mechanical import detect_dead_code
from tree_guard import unchanged

QUIET = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
         "--no-correlate", "--no-ledger", "--json"]

PYPROJECT = '''\
[project]
name = "pkg"
version = "0.1"

[project.scripts]
tool = "pkg.handlers:cli_entry"

[project.entry-points."pkg.plugins"]
audit = "pkg.plugins:AuditPlugin"
'''


def _sample(root):
    (root / ".git").mkdir(parents=True)
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "settings.yaml").write_text("on_start: configured_hook\n")
    (root / "README.md").write_text("Prose mentions prose_only_name here.\n")
    (root / "pkg" / "handlers.py").write_text(textwrap.dedent('''\
        def cli_entry():
            return 1


        def handle_x():
            return 2


        def configured_hook():
            return 3


        def uncovered_public():
            return 4


        def prose_only_name():
            return 5


        def truly_dead():
            return 6
    '''))
    (root / "pkg" / "plugins.py").write_text("class AuditPlugin:\n    x = 1\n")
    (root / "pkg" / "other.py").write_text("def cli_entry():\n    return 0\n")
    (root / "pkg" / "dispatch.py").write_text(textwrap.dedent('''\
        import pkg.handlers as mod


        def run():
            return getattr(mod, "handle_x")
    '''))
    return root


def _facts(root):
    files = sorted(root.rglob("*.py"))
    return {(f.attributes["name"], f.evidence.file.split("/")[-1]): f.attributes
            for f in detect_dead_code(files)}


def test_the_red_team_sample_flags_exactly_the_reachable_names(tmp_path):
    facts = _facts(_sample(tmp_path / "repo"))
    yes = {k for k, a in facts.items() if a["framework_hook"] == "yes"}
    assert yes == {("cli_entry", "handlers.py"), ("AuditPlugin", "plugins.py"),
                   ("handle_x", "handlers.py"), ("configured_hook", "handlers.py")}
    assert "console script 'tool'" in facts[("cli_entry", "handlers.py")]["referenced_by"]
    assert "plugin entry point 'audit'" in facts[("AuditPlugin", "plugins.py")]["referenced_by"]
    assert facts[("handle_x", "handlers.py")]["referenced_by"] == "named as a string in pkg/dispatch.py"
    assert facts[("configured_hook", "handlers.py")]["referenced_by"] == "named as a string in settings.yaml"


def test_truly_dead_and_uncovered_names_stay_no(tmp_path):
    facts = _facts(_sample(tmp_path / "repo"))
    for key in [("truly_dead", "handlers.py"), ("uncovered_public", "handlers.py"),
                ("prose_only_name", "handlers.py")]:
        assert facts[key]["framework_hook"] == "no"
        assert "referenced_by" not in facts[key]


def test_same_name_in_a_different_module_is_not_flagged(tmp_path):
    facts = _facts(_sample(tmp_path / "repo"))
    assert facts[("cli_entry", "other.py")]["framework_hook"] == "no"


def test_readme_prose_is_not_a_reference(tmp_path):
    root = _sample(tmp_path / "repo")
    assert _facts(root)[("prose_only_name", "handlers.py")]["framework_hook"] == "no"


def test_no_computed_lookup_is_reported_as_no(tmp_path):
    facts = _facts(_sample(tmp_path / "repo"))
    a = facts[("truly_dead", "handlers.py")]
    assert (a["dynamic_lookup_possible"], a["dynamic_lookup_count"]) == ("no", "0")


def test_a_computed_lookup_is_flagged_on_every_finding(tmp_path):
    root = _sample(tmp_path / "repo")
    (root / "pkg" / "dyn.py").write_text(textwrap.dedent('''\
        import importlib


        def load(name, obj, key):
            importlib.import_module(name)
            __import__(name)
            return getattr(obj, f"h_{key}")
    '''))
    facts = _facts(root)
    for a in facts.values():
        assert a["dynamic_lookup_possible"] == "yes"
        assert a["dynamic_lookup_count"] == "3"
    assert facts[("truly_dead", "handlers.py")]["framework_hook"] == "no"


def test_string_in_a_collection_counts_but_a_lone_string_does_not(tmp_path):
    (tmp_path / "m.py").write_text(textwrap.dedent('''\
        def in_list():
            return 1


        def in_dict():
            return 1


        def lone():
            return 1


        NAMES = ["in_list"]
        TABLE = {"k": "in_dict"}
        TEXT = "lone"
    '''))
    found = {f.attributes["name"]: f.attributes["framework_hook"]
             for f in detect_dead_code([tmp_path / "m.py"])}
    assert found == {"in_list": "yes", "in_dict": "yes", "lone": "no"}


def test_setup_cfg_and_setup_py_entry_points(tmp_path):
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "a.py").write_text("def from_cfg():\n    return 1\n\n\ndef from_setup_py():\n    return 2\n")
    (root / "setup.cfg").write_text("[options.entry_points]\nconsole_scripts =\n    a = pkg.a:from_cfg\n")
    (root / "setup.py").write_text("setup(entry_points={'console_scripts': ['b = pkg.a:from_setup_py']})\n")
    found = {f.attributes["name"]: f.attributes["referenced_by"]
             for f in detect_dead_code(sorted(root.rglob("*.py")))}
    assert "setup.cfg" in found["from_cfg"] and "setup.py" in found["from_setup_py"]


def test_src_layout_module_is_matched(tmp_path):
    root = tmp_path / "repo"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "__init__.py").write_text("")
    (root / "src" / "pkg" / "m.py").write_text("def go():\n    return 1\n")
    (root / "pyproject.toml").write_text('[project.scripts]\nx = "pkg.m:go"\n')
    (f,) = detect_dead_code(sorted(root.rglob("*.py")))
    assert f.attributes["framework_hook"] == "yes"


def test_a_scan_of_the_sample_writes_nothing_and_carries_the_facts(tmp_path, capsys):
    root = _sample(tmp_path / "repo")
    with unchanged(root):
        buster_cli.main([str(root), *QUIET])
    rows = [r for r in json.loads(capsys.readouterr().out) if r["detector"] == "dead_code"]
    by_name = {r["attributes"]["name"]: r["attributes"] for r in rows
               if r["evidence"]["file"].endswith("handlers.py")}
    assert by_name["cli_entry"]["framework_hook"] == "yes"
    assert by_name["truly_dead"]["framework_hook"] == "no"
    assert by_name["truly_dead"]["dynamic_lookup_possible"] == "no"
