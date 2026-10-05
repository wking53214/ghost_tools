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
# The gathering half of the CLI moved to pipeline.py in 1.6.0. The
# mutants below that point at it were re-aimed, not removed: the code
# they mutate is the same code, in its new module.
_P = "ghost_buster/pipeline.py"

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

    # --- the slopsquat surface (v0.17) ---
    ("an invented package name is no longer reported", _S,
     "    for package in unresolvable:\n", "    for package in []:\n"),
    ("a guarded import is reported as an invented name", _S,
     "        if pkg not in declared and pkg not in mapping and pkg not in guarded\n",
     "        if pkg not in declared and pkg not in mapping\n"),
    ("only ImportError counts as a guard, so ModuleNotFoundError leaks through", _S,
     '        if name in ("ImportError", "ModuleNotFoundError", "Exception", "BaseException"):\n',
     '        if name == "ImportError":\n'),
    ("an installed package is reported as invented", _S,
     "        if pkg not in declared and pkg not in mapping and pkg not in guarded\n",
     "        if pkg not in declared and pkg not in guarded\n"),
    ("a package this repository provides is reported as invented", _S,
     '        and pkg.replace("-", "_") not in local\n', "\n"),
    ("a declared package is reported as invented", _S,
     "        if pkg not in declared and pkg not in mapping and pkg not in guarded\n",
     "        if pkg not in mapping and pkg not in guarded\n"),
    ("an invented package is downgraded to a nit", _S,
     '            model, "unresolvable dependency", Severity.MAJOR,\n',
     '            model, "unresolvable dependency", Severity.INFORMATIONAL,\n'),

    ("the src layout is not recognised, so a repo imports itself from outside", _S,
     '    for parent in _PACKAGE_PARENTS:\n', "    for parent in []:\n"),
    ("a src directory that IS a package is descended into anyway", _S,
     '        if d.is_dir() and not (d / "__init__.py").is_file():\n',
     "        if d.is_dir():\n"),

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
    ("declining the structure scan leaves no receipt", _P,
     '        _skipped("structure scan", "--no-structure", say)\n', '        pass\n'),
    # --- build-time imports, and the packaging declared twice ---
    ("[build-system].requires is ignored again, so setup.py's import is 'undeclared'", _S,
     "    model.build_requires = sorted({requirement_name(r) for r in facts.build_requires} - {\"\"})\n",
     "    model.build_requires = []\n"),
    ("every module counts as build-time, so a real missing runtime dep is cleared", _S,
     "        at_build_time = facts.dotted in model.build_modules\n",
     "        at_build_time = True\n"),
    ("setup.py is never recognised as build-time", _S,
     "        elif relative.name in _BUILD_TIME_FILES and len(relative.parts) == 1:\n",
     "        elif False:\n"),
    ("two files declaring one package is silent", _S,
     "    shared = sorted(set(pyproject) & set(setup))\n    if not shared:\n",
     "    shared = []\n    if not shared:\n"),
    ("drift is downgraded to the they-agree severity", _S,
     '            model, "parallel packaging metadata", Severity.MAJOR,\n',
     '            model, "parallel packaging metadata", Severity.MINOR,\n'),
    ("agreement is inflated to the they-disagree severity", _S,
     '        model, "parallel packaging metadata", Severity.MINOR,\n',
     '        model, "parallel packaging metadata", Severity.MAJOR,\n'),
    ("agreeing declarations are passed over in silence", _S,
     "    return [_finding(\n        model, \"parallel packaging metadata\", Severity.MINOR,\n",
     "    return []\n    return [_finding(\n        model, \"parallel packaging metadata\", Severity.MINOR,\n"),
    ("a name spelled two ways is reported as drift", _S,
     '    if key == "name":\n        import re as _re\n        return _re.sub(r"[-_.]+", "-", str(value)).strip().lower()\n',
     ""),
    ("a computed setup() argument is compared as though it were a declaration", _S,
     "            try:\n                value = ast.literal_eval(kw.value)\n            except (ValueError, SyntaxError):\n                continue        # computed, so not a declaration to compare\n",
     "            try:\n                value = ast.literal_eval(kw.value)\n            except (ValueError, SyntaxError):\n                value = ast.dump(kw.value)\n"),
    ("--structure-out writes nothing", _P,
     "                args.structure_out.write_text(model.to_json(), encoding=\"utf-8\")\n",
     "                pass\n"),
    # --- the comment citation (1.8.0): a name parked in a comment is
    # --- evidence about the name, and must neither clear the finding
    # --- nor let prose answer for a package.
    ("a commented-out dependency clears the finding instead of citing it", _S,
     "        parked = model.commented_out.get(package)\n",
     "        parked = None\n"),
    ("every word of a comment answers for a package of that name", _S,
     '            first = re.split(r"[\\s,\\[\\]\'\\"()]+", comment.strip(), maxsplit=1)[0]\n',
     '            first = re.split(r"[\\s,\\[\\]\'\\"()]+", comment.strip())[-1]\n'),
    ("a comment counts as a declaration", _S,
     "    model.commented_out = commented_out_dependencies(root)\n",
     "    model.commented_out = commented_out_dependencies(root)\n"
     "    model.declared_dependencies = sorted(set(model.declared_dependencies) | set(model.commented_out))\n"),
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
