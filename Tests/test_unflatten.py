"""The rebuild of a flattened file, held to the one case with an answer.

A flattened file has no original to check against, which is exactly why it
needed rebuilding. One does: a file in the KAGGLE repository was flattened,
and its original was later found intact inside a Gemini export. Both are
fixtures here, so the tool's central claim is a test rather than a promise.

What the tool may claim is narrow. Every statement, name and literal comes
from the input unchanged; the nesting is inferred, and the count of block
boundaries that had more than one reading is printed and written into the
file. These tests pin that split: an exact match where one is possible, and
the reported count where it is not.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONTROL_FLAT = FIXTURES / "flattened_control.py.flattened"
# Both fixtures are named so the scanner reads them as data, not as source:
# the original is real Python that imports lightgbm and scikit-image, and a
# scan of this tree would otherwise report those as undeclared dependencies
# of ghost_tools. `.flattened` already means data here; `.original` matches it.
CONTROL_ORIGINAL = FIXTURES / "flattened_control.py.original"


def _load():
    spec = importlib.util.spec_from_file_location("unflatten", ROOT / "tools" / "unflatten.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["unflatten"] = module
    spec.loader.exec_module(module)
    return module


unflatten = _load()


def rebuild(text: str):
    """Whichever pass the input calls for, as __main__ chooses it."""
    text = text.replace(unflatten.NBSP, " ")
    if unflatten.INDENT_RUN.search(text):
        src, _ = unflatten.reconstruct_indented(text)
        return src, 0
    ok, src, _, ambiguous = unflatten.reconstruct(unflatten.unswallow_comments(text))
    return src, ambiguous


# ------------------------------------------------------------- the control

def test_the_rebuild_matches_the_original_that_was_later_found():
    """The whole claim, on the only file where it can be checked."""
    src, _ = rebuild(CONTROL_FLAT.read_text())
    assert ast.dump(ast.parse(src)) == ast.dump(ast.parse(CONTROL_ORIGINAL.read_text()))


def test_the_control_is_genuinely_flattened():
    """A fixture that quietly stopped being flattened would make the test
    above pass for the wrong reason."""
    flat = CONTROL_FLAT.read_text()
    assert flat.count("\n") <= 1
    with pytest.raises(SyntaxError):
        ast.parse(flat)


# --------------------------------------------------- what it may claim

def test_every_name_in_the_input_survives_the_rebuild():
    flat = "class A:  def f(self):  return 1  def g(self):  return 2"
    src, _ = rebuild(flat)
    names = {n.name for n in ast.walk(ast.parse(src))
             if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    assert names == {"A", "f", "g"}


def test_a_method_that_takes_self_is_placed_inside_its_class():
    src, _ = rebuild("class A:  X = 1  def f(self):  return self.X")
    cls = ast.parse(src).body[0]
    assert isinstance(cls, ast.ClassDef)
    assert [n.name for n in cls.body if isinstance(n, ast.FunctionDef)] == ["f"]


def test_the_entry_point_guard_goes_back_to_column_zero():
    src, _ = rebuild('def f():  return 1  if __name__ == "__main__":  f()')
    assert isinstance(ast.parse(src).body[-1], ast.If)


def test_an_inferred_boundary_is_counted_not_hidden():
    """A `return` at the end of a block could close one block or several.
    The tool is allowed to choose; it is not allowed to choose silently."""
    flat = ("def f(a):  if a:  if a > 1:  return 2  return 1  "
            "def g():  return 0")
    _, ambiguous = rebuild(flat)
    assert ambiguous > 0


def test_a_comment_does_not_swallow_the_code_after_it():
    """Flattened, a `#` runs to the end of the file and the tokenizer sees
    one comment where a program was."""
    src, _ = rebuild("x = 1  # a note about x  y = 2")
    names = {t.id for n in ast.walk(ast.parse(src))
             for t in ast.walk(n) if isinstance(t, ast.Name)}
    assert {"x", "y"} <= names


def test_a_body_the_source_never_held_is_marked_rather_than_invented():
    src, filled = unflatten.fill_missing_bodies("def f():\n    # nothing follows\n")
    assert filled == 1
    assert unflatten.MISSING_BODY.split("#")[0].strip() in src
    assert "reconstruction" in src
    ast.parse(src)


def test_a_line_that_is_not_python_is_kept_as_a_marked_comment():
    src, foreign = unflatten.comment_out_foreign("x = 1\nmkdir -p ~/.kaggle && echo hi\n")
    assert foreign == 1
    assert unflatten.FOREIGN in src
    ast.parse(src)


# ------------------------------------------------- what it must never do

def test_it_writes_only_where_it_was_told(tmp_path):
    """Nothing in the toolkit modifies a file it did not create."""
    src = tmp_path / "flat.py"
    src.write_text(CONTROL_FLAT.read_text())
    before = src.read_text()
    out = tmp_path / "rebuilt.py"

    import subprocess
    rc = subprocess.run([sys.executable, str(ROOT / "tools" / "unflatten.py"),
                         str(src), str(out)], capture_output=True, text=True)

    assert rc.returncode == 0, rc.stderr
    assert src.read_text() == before
    assert out.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["flat.py", "rebuilt.py"]
