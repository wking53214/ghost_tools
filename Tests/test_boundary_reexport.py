"""A package's front door is its re-exports, and its layout is not its name.

Both bugs here produced the same symptom -- a CRITICAL saying a package
"does not export" a name it exports fine -- and both were found by joining
two real repositories on 2026-09-10 rather than by reading the code.
"""
from __future__ import annotations

import textwrap

from ghost_buster.boundary import build_joined_model, derive_findings
from ghost_buster.structure import build_model


def _write(root, rel, body):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body))
    return path


def _provider_src_layout(root):
    """A package under src/ that presents its surface exactly the way GEMS; does: a star-import, explicit re-export lines, and an __all__."""
    _write(root, "src/prov/contracts/models.py", '''
        class Authority:
            pass

        class Origin:
            pass
        ''')
    _write(root, "src/prov/contracts/__init__.py",
           "from prov.contracts.models import Authority, Origin\n")
    _write(root, "src/prov/core/handoff.py", "class HandoffValidator:\n    pass\n")
    _write(root, "src/prov/__init__.py", '''
        from prov.contracts import *
        from prov.core.handoff import HandoffValidator

        __all__ = ["HandoffValidator"]
        ''')
    (root / ".git").mkdir(exist_ok=True)
    return [p for p in root.rglob("*.py")]


#: Real adapters guard their cross-repo import and fall back when the other
#: repository is not checked out -- that guard is what MAKES it a boundary.
#: The first version of these fixtures used a plain import, so no boundary
#: was detected and three "no critical finding" tests passed while asserting
#: nothing at all. The genuinely-absent case is what exposed them.
def _guarded(body: str) -> str:
    return (
        "try:\n"
        + textwrap.indent(textwrap.dedent(body), "    ")
        + "except ImportError:\n    pass\n"
    )


def _consumer(root, body):
    _write(root, "adapter.py", body)
    (root / ".git").mkdir(exist_ok=True)
    return [p for p in root.rglob("*.py")]


def _join(tmp_path, consumer_body, tag=""):
    prov = tmp_path / f"prov_repo{tag}"
    cons = tmp_path / f"cons_repo{tag}"
    prov.mkdir(exist_ok=True)
    cons.mkdir(exist_ok=True)
    files = {str(prov.resolve()): _provider_src_layout(prov),
             str(cons.resolve()): _consumer(cons, consumer_body)}
    joined = build_joined_model([str(prov), str(cons)], files)
    return joined, derive_findings(joined, files)


def _criticals(findings):
    return [f for f in findings if f.severity.value == "critical"]


# ------------------------------------------------------ re-exports

def test_an_explicitly_reexported_name_is_not_missing(tmp_path):
    joined, findings = _join(tmp_path, _guarded("from prov import HandoffValidator\n"))
    assert joined.reaches, "fixture produced no boundary; the test would be vacuous"
    assert _criticals(findings) == [], [f.summary for f in _criticals(findings)]


def test_a_name_arriving_through_a_star_import_is_not_missing(tmp_path):
    """`from prov.contracts import *` is how Authority and Origin reach the; package root. Collecting only definitions made them invisible."""
    joined, findings = _join(tmp_path, _guarded("from prov import Authority, Origin\n"))
    assert joined.reaches, "fixture produced no boundary; the test would be vacuous"
    assert _criticals(findings) == [], [f.summary for f in _criticals(findings)]


def test_a_genuinely_absent_name_is_still_reported(tmp_path):
    """Seeing re-exports must not blind the check to a real break."""
    joined, findings = _join(tmp_path, _guarded("from prov import NoSuchThing\n"))
    crit = _criticals(findings)
    assert len(crit) == 1, [f.summary for f in findings]
    assert "NoSuchThing" in crit[0].summary


# ------------------------------------------------------ src layout

def test_a_src_layout_package_provides_its_own_names(tmp_path):
    """`packages` reported `prov` while every module was dotted `src.prov.*`,
    so nothing matched and the repository provided NOTHING -- which made
    every imported name missing."""
    joined, _ = _join(tmp_path, "x = 1\n")
    prov = tmp_path / "prov_repo"
    model = build_model(str(prov), list(prov.rglob("*.py")))
    assert model.packages == ["prov"]
    package = joined.provides.get("prov")
    assert package is not None, "the src-layout package was not registered at all"
    _root, names = package
    assert {"HandoffValidator", "Authority", "Origin"} <= names, sorted(names)


# ------------------------------------------------------ abstention

def test_an_unresolvable_star_makes_the_surface_opaque(tmp_path):
    """A module that re-exports everything from somewhere this scan cannot
    see has an unknowable surface. A CRITICAL that is wrong costs more than
    one that is absent, so it abstains and says so."""
    prov, cons = tmp_path / "p2", tmp_path / "c2"
    prov.mkdir()
    cons.mkdir()
    _write(prov, "src/opaque/__init__.py", "from somewhere_unseen import *\n")
    (prov / ".git").mkdir(exist_ok=True)
    files = {str(prov.resolve()): list(prov.rglob("*.py")),
             str(cons.resolve()): _consumer(
                 cons, _guarded("from opaque import Whatever\n"))}
    joined = build_joined_model([str(prov), str(cons)], files)
    findings = derive_findings(joined, files)
    assert _criticals(findings) == []
    assert any("not enumerable" in u for u in joined.unresolved), joined.unresolved


def _provider_without_all(root):
    """A package that re-exports and declares no __all__ at all -- the common
    case, and the one that exercises the re-export collection on its own.

    The fixture above lists its re-exported name in __all__ too, so
    `public_names` covered it and two mutants on the re-export path survived.
    A test that is satisfied by a different mechanism than the one it names
    is not testing that mechanism.
    """
    _write(root, "src/bare/inner.py", "class OnlyReexported:\n    pass\n")
    _write(root, "src/bare/__init__.py", "from bare.inner import OnlyReexported\n")
    (root / ".git").mkdir(exist_ok=True)
    return list(root.rglob("*.py"))


def test_a_reexport_without_an_all_declaration_is_still_provided(tmp_path):
    prov, cons = tmp_path / "bare_p", tmp_path / "bare_c"
    prov.mkdir()
    cons.mkdir()
    files = {str(prov.resolve()): _provider_without_all(prov),
             str(cons.resolve()): _consumer(
                 cons, _guarded("from bare import OnlyReexported\n"))}
    joined = build_joined_model([str(prov), str(cons)], files)
    assert joined.reaches, "fixture produced no boundary; the test would be vacuous"
    findings = derive_findings(joined, files)
    assert _criticals(findings) == [], [f.summary for f in _criticals(findings)]
    _root, names = joined.provides["bare"]
    assert "OnlyReexported" in names


def test_a_missing_name_is_still_caught_when_there_is_no_all(tmp_path):
    prov, cons = tmp_path / "bare_p2", tmp_path / "bare_c2"
    prov.mkdir()
    cons.mkdir()
    files = {str(prov.resolve()): _provider_without_all(prov),
             str(cons.resolve()): _consumer(
                 cons, _guarded("from bare import NotThere\n"))}
    joined = build_joined_model([str(prov), str(cons)], files)
    findings = derive_findings(joined, files)
    assert len(_criticals(findings)) == 1
    assert "NotThere" in _criticals(findings)[0].summary


def test_a_facade_submodule_reexporting_a_name_is_resolved(tmp_path):
    """`from pkg.facade import Thing`, where facade.py re-exports Thing from
    elsewhere in the package.

    This is the case the re-export collection exists for. An import of the
    PACKAGE ROOT is already satisfied by the union of every module's
    exports, so two mutants on the re-export path survived until a test
    aimed at a SUBMODULE, where the union does not apply and the facade
    must be able to speak for itself.
    """
    prov, cons = tmp_path / "fac_p", tmp_path / "fac_c"
    prov.mkdir()
    cons.mkdir()
    _write(prov, "src/fac/deep/engine.py", "class Thing:\n    pass\n")
    _write(prov, "src/fac/deep/__init__.py", "")
    _write(prov, "src/fac/facade.py", "from fac.deep.engine import Thing\n")
    _write(prov, "src/fac/__init__.py", "")
    (prov / ".git").mkdir(exist_ok=True)
    files = {str(prov.resolve()): list(prov.rglob("*.py")),
             str(cons.resolve()): _consumer(
                 cons, _guarded("from fac.facade import Thing\n"))}
    joined = build_joined_model([str(prov), str(cons)], files)
    assert joined.reaches, "fixture produced no boundary; the test would be vacuous"
    assert "Thing" in joined.provides_module.get("fac.facade", set()), (
        "the facade does not report the name it re-exports: "
        f"{sorted(joined.provides_module.get('fac.facade', set()))}"
    )
    assert _criticals(derive_findings(joined, files)) == []


def test_a_facade_that_does_not_reexport_a_name_still_reports_it_missing(tmp_path):
    prov, cons = tmp_path / "fac_p2", tmp_path / "fac_c2"
    prov.mkdir()
    cons.mkdir()
    _write(prov, "src/fac/deep/engine.py", "class Thing:\n    pass\n")
    _write(prov, "src/fac/deep/__init__.py", "")
    _write(prov, "src/fac/facade.py", "from fac.deep.engine import Thing\n")
    _write(prov, "src/fac/__init__.py", "")
    (prov / ".git").mkdir(exist_ok=True)
    files = {str(prov.resolve()): list(prov.rglob("*.py")),
             str(cons.resolve()): _consumer(
                 cons, _guarded("from fac.facade import Absent\n"))}
    joined = build_joined_model([str(prov), str(cons)], files)
    crit = _criticals(derive_findings(joined, files))
    assert len(crit) == 1 and "Absent" in crit[0].summary
