"""dead_code counts imports, string annotations, stubs and computed lookups as uses.

Red team: Warden removed code that was imported with `from x import y`, used
only in a string annotation or an `if TYPE_CHECKING` block, declared in a
sibling .pyi stub, or reached through `globals()["_cmd_" + name]`.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from ghost_buster.mechanical import detect_dead_code


def _write(root: Path, files: dict) -> list:
    out = []
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
        if name.endswith(".py"):
            out.append(p)
    return out


def _dead(root, files):
    paths = _write(root, files)
    return {f.attributes["name"]: f for f in detect_dead_code(paths)}


def test_a_name_imported_with_from_import_is_used(tmp_path):
    dead = _dead(tmp_path, {
        "lib.py": "def helper():\n    return 1\n\ndef orphan_zz():\n    return 2\n",
        "app.py": "from lib import helper\n",
    })
    assert "helper" not in dead and "orphan_zz" in dead


def test_a_reexport_in_init_is_used(tmp_path):
    dead = _dead(tmp_path, {
        "pkg/__init__.py": "from .core import Engine as Engine\n",
        "pkg/core.py": "class Engine:\n    pass\n\nclass Orphan:\n    pass\n",
    })
    assert "Engine" not in dead and "Orphan" in dead


def test_all_in_any_form_exports(tmp_path):
    dead = _dead(tmp_path, {
        "m.py": """\
            def a_one(): pass
            def b_two(): pass
            def c_three(): pass
            def d_four(): pass
            def e_five(): pass
            __all__: list = ["a_one"]
            __all__ += ["b_two"]
            __all__.extend(["c_three"])
            __all__ = __all__ + ["d_four"]
        """,
    })
    assert set(dead) == {"e_five"}


def test_names_used_only_in_string_annotations_are_used(tmp_path):
    dead = _dead(tmp_path, {
        "types_.py": """\
            class Alpha: pass
            class Beta: pass
            class Gamma: pass
            class Delta: pass
            class Epsilon: pass
            class Nobody: pass
        """,
        "use.py": """\
            from typing import TYPE_CHECKING, Dict, Optional, cast
            if TYPE_CHECKING:
                pass
            def f(a: "Alpha", b: Optional["Beta"]) -> "list[Gamma] | None":
                x: "Delta" = None
                y = cast("Epsilon", x)
                z: Dict[str, "Alpha"] = {}
                return None
            f(None, None)
        """,
    })
    assert set(dead) == {"Nobody"}


def test_a_name_in_a_sibling_pyi_stub_is_used(tmp_path):
    dead = _dead(tmp_path, {
        "native.py": "def fast_path(): pass\ndef orphan_qq(): pass\n",
        "native.pyi": "def fast_path() -> int: ...\n",
    })
    assert "fast_path" not in dead and "orphan_qq" in dead


def test_star_import_uses_public_names_of_that_module(tmp_path):
    dead = _dead(tmp_path, {
        "util.py": "def public_fn(): pass\ndef _private_fn(): pass\n",
        "app.py": "from util import *\n",
    })
    assert "public_fn" not in dead


def _facts(root, files):
    paths = _write(root, files)
    (root / "pyproject.toml").write_text('[project]\nname="x"\nversion="1"\n')
    return {f.attributes["name"]: f.attributes for f in detect_dead_code(paths)}


def test_globals_with_a_computed_name_sets_dynamic_lookup(tmp_path):
    facts = _facts(tmp_path, {
        "cli.py": """\
            def _cmd_run(): pass
            def dispatch(x):
                return globals()["_cmd_" + x]()
        """,
    })
    a = facts["_cmd_run"]
    assert a["dynamic_lookup_possible"] == "yes" and int(a["dynamic_lookup_count"]) >= 1
    assert a["framework_hook"] == "yes" and "_cmd_" in a["referenced_by"]


def test_vars_locals_and_sys_modules_with_computed_names_count(tmp_path):
    facts = _facts(tmp_path, {
        "m.py": """\
            import sys
            def lonely(): pass
            def go(n):
                a = vars()[n]
                b = locals()[f"h_{n}"]
                c = sys.modules[n]
                d = globals().get(n)
                return getattr(sys.modules[__name__], n)
        """,
    })
    a = facts["lonely"]
    assert a["dynamic_lookup_possible"] == "yes" and int(a["dynamic_lookup_count"]) == 5


def test_no_computed_lookup_stays_no(tmp_path):
    facts = _facts(tmp_path, {"m.py": "def lonely(): pass\nx = globals()['other']\n"})
    assert facts["lonely"]["dynamic_lookup_possible"] == "no"
