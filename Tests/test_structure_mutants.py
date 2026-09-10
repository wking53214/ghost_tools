"""The proof that Tests/test_structure.py is not vacuous.

This module's promise is that it never exceeds its evidence, so the
mutants that matter most make it OVERREACH: report an undecidable import
as undeclared, treat a bare pathlib import as disk access, emit findings
from an empty model, drop the unresolved list so dynamic behaviour
vanishes from the picture. Each of those produces a model that reads as
more certain than the evidence supports, which is the one failure this
module was written to prevent.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

STRUCTURE_TESTS = "Tests/test_structure.py"
_S = "ghost_buster/structure.py"
_C = "ghost_buster/cli.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- it overreaches ---
    ("an unmappable import is reported as undeclared", _S,
     "            distribution = mapping.get(package)\n            if distribution is None:\n",
     "            distribution = mapping.get(package) or package\n            if False:\n"),
    ("findings are derived from an empty model", _S,
     "    if not model.modules:\n", "    if False:\n"),
    ("a bare pathlib import counts as touching the filesystem", _S,
     '    "filesystem": ("shutil", "tempfile", "glob", "fileinput"),\n',
     '    "filesystem": ("shutil", "tempfile", "glob", "fileinput", "pathlib"),\n'),
    ("a valid console script is reported as missing", _S,
     "        elif symbol and symbol not in facts.exported and symbol not in facts.internal:\n",
     "        elif symbol:\n"),
    ("a repo with no declaration mechanism is nagged anyway", _S,
     "    if model.dependency_sources:\n", "    if True:\n"),
    ("every top-level binding counts as mutable state", _S,
     "    return isinstance(node, (ast.List, ast.Dict, ast.Set, ast.ListComp,\n"
     "                             ast.DictComp, ast.SetComp))\n",
     "    return True\n"),

    # --- it stops observing ---
    ("optional dependencies stop counting as declarations", _S,
     '    for extra in (project.get("optional-dependencies") or {}).values():\n'
     "        deps.extend(str(d) for d in extra)\n", ""),
    ("console scripts are not read", _S,
     '    scripts = {str(k): str(v) for k, v in (project.get("scripts") or {}).items()}\n',
     "    scripts = {}\n"),
    ("a real filesystem call is no longer a boundary", _S,
     "                for boundary, names in _BOUNDARY_CALLS.items():\n"
     "                    if attr in names and boundary not in facts.boundaries:\n"
     "                        facts.boundaries.append(boundary)\n", ""),
    ("os.environ access stops counting", _S,
     '        elif isinstance(node, ast.Attribute) and node.attr == "environ":\n',
     "        elif False:\n"),
    ("__main__ guards are not recognised as entry points", _S,
     '                facts.entry_points.append(f"{dotted}:__main__ guard")\n', "                pass\n"),
    ("internal imports are misfiled as external", _S,
     "    if top in package_roots:\n", "    if False:\n"),
    ("dataclasses stop being recognised as data representations", _S,
     "            if isinstance(node, ast.ClassDef) and _model_kind(node):\n",
     "            if False:\n"),
    ("__all__ is not read, so no declared public surface exists", _S,
     '                if isinstance(t, ast.Name) and t.id == "__all__":\n',
     "                if False:\n"),

    # --- it stops naming its gaps ---
    ("dynamic imports vanish from the model instead of being recorded", _S,
     '                    facts.unresolved.append(f"{dotted} calls {fn}() -- resolved at runtime")\n',
     "                    pass\n"),
    ("the report stops declaring what it will not answer", _S,
     '    L.append("NOT ANSWERED HERE, ON PURPOSE")\n', '    L.append("")\n'),
    ("requirement names stop normalising, so Ruff != ruff", _S,
     '    return spec.strip().lower().replace("_", "-").replace(".", "-")\n',
     "    return spec.strip()\n"),

    # --- the CLI contract ---
    ("the structure scan silently returns to opt-in", _C,
     '        "--structure", action=argparse.BooleanOptionalAction, default=True,\n',
     '        "--structure", action=argparse.BooleanOptionalAction, default=False,\n'),
    ("declining the structure scan leaves no receipt", _C,
     '        _skipped("structure scan", "--no-structure")\n', "        pass\n"),
    ("--structure-out writes nothing", _C,
     "                args.structure_out.write_text(model.to_json(), encoding=\"utf-8\")\n",
     "                pass\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_structure_mutant_is_killed(label, rel, old, new):
    assert_killed(label, STRUCTURE_TESTS, run_tests_with_mutation(STRUCTURE_TESTS, rel, old, new))


def test_structure_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        STRUCTURE_TESTS, _S, 'DETECTOR = "structure"\n', 'DETECTOR = "structure"\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
