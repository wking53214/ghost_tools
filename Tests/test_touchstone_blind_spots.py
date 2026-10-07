"""Three TOUCHSTONE failure modes ghost_buster used to miss.

WHERE THIS CAME FROM

`swizzle touchstone` scores ghost_buster against TOUCHSTONE's MANIFEST, real
damage with the correct answers written down. On 2026-10-07 it named 0 of 5
failure modes. Three of the five are visible to a syntax-tree scanner:

  3.1 silent pass       a file whose code is all in one comment
  3.2 overclaim         a method calling self.<name>() that cannot exist
  3.3 flattening dup    an unreadable file that is a readable one, flattened

Each fixture below reproduces the SHAPE of the specimen, not its text, and
each detector has a control that must stay quiet.
"""
from __future__ import annotations

from ghost_buster.buried import detect_commented_out_modules
from ghost_buster.flattened import detect_flattened_copies
from ghost_buster.mechanical import registered_detectors
from ghost_buster.selfcall import detect_undefined_self_methods


def _w(tmp_path, name, text):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# --------------------------------------------------------- 3.1 silent pass

BURIED = ("# import os class Ledger: def __init__(self): self.rows = [] "
          "def add(self, row): self.rows.append(row) def total(self): return len(self.rows)")


def test_a_module_whose_code_is_one_comment_is_reported(tmp_path):
    p = _w(tmp_path, "ledger.py", BURIED)
    [f] = detect_commented_out_modules([p])
    assert f.detector == "commented_out_module"
    assert f.attributes["signatures_in_comments"] >= 2
    assert f.evidence.line_start == 1


def test_a_licence_header_init_is_not_buried_code(tmp_path):
    p = _w(tmp_path, "pkg/__init__.py",
           "# Copyright 2026 William N. King\n# Licensed under the Apache License 2.0\n")
    assert detect_commented_out_modules([p]) == []


def test_live_code_beside_commented_code_is_not_this_finding(tmp_path):
    p = _w(tmp_path, "m.py", BURIED + "\nVALUE = 1\n")
    assert detect_commented_out_modules([p]) == []


def test_one_signature_in_a_comment_is_a_note_not_a_module(tmp_path):
    p = _w(tmp_path, "m.py", '"""Doc."""\n# see def helper( in utils\n')
    assert detect_commented_out_modules([p]) == []


# ---------------------------------------------------------- 3.2 overclaim

OVERCLAIM = '''class Construct:
    def __init__(self, layers):
        self.layers = layers

    def validate(self, data):
        for node in self.layers:
            if not self._check_node(data, node):
                return False
        return True
'''


def test_a_call_on_self_to_a_name_the_class_cannot_have(tmp_path):
    p = _w(tmp_path, "c.py", OVERCLAIM)
    [f] = detect_undefined_self_methods([p])
    assert f.attributes == {"class": "Construct", "method": "validate", "missing": "_check_node"}
    assert f.evidence.line_start == 7


def test_inherited_from_a_class_in_the_same_file_is_defined(tmp_path):
    p = _w(tmp_path, "c.py", "class Base:\n    def _check_node(self, d, n):\n        return True\n\n"
           + OVERCLAIM.replace("class Construct:", "class Construct(Base):"))
    assert detect_undefined_self_methods([p]) == []


def test_a_callable_assigned_to_self_is_defined(tmp_path):
    p = _w(tmp_path, "c.py", OVERCLAIM.replace(
        "self.layers = layers", "self.layers = layers\n        self._check_node = lambda d, n: True"))
    assert detect_undefined_self_methods([p]) == []


def test_abstains_when_a_base_is_not_visible(tmp_path):
    p = _w(tmp_path, "c.py", "from lib import Base\n\n"
           + OVERCLAIM.replace("class Construct:", "class Construct(Base):"))
    assert detect_undefined_self_methods([p]) == []


def test_abstains_on_getattr_metaclass_decorator_and_setattr(tmp_path):
    variants = [
        OVERCLAIM + "\n    def __getattr__(self, name):\n        return lambda *a: True\n",
        OVERCLAIM.replace("class Construct:", "class Construct(metaclass=Meta):"),
        "@register\n" + OVERCLAIM,
        OVERCLAIM.replace("self.layers = layers", "setattr(self, 'layers', layers)"),
        OVERCLAIM.replace("self.layers = layers", "self.__dict__.update(layers=layers)"),
    ]
    for i, text in enumerate(variants):
        p = _w(tmp_path, f"c{i}.py", text)
        assert detect_undefined_self_methods([p]) == [], text


# ------------------------------------------------------ 3.3 flattening dup

READABLE = '''import hashlib


class Sandbox:
    """Runs a payload under a capability set."""

    def __init__(self, capabilities):
        self.capabilities = set(capabilities)

    def validate_capabilities(self, requested):
        missing = set(requested) - self.capabilities
        if missing:
            raise PermissionError(sorted(missing))
        return True

    def digest(self, payload):
        return hashlib.sha256(payload.encode()).hexdigest()
'''


def _flatten(text):
    # What a paste through a chat window does: every line break gone.
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def test_an_unreadable_flattened_copy_names_its_readable_twin(tmp_path):
    good = _w(tmp_path, "wrapper/sandbox.py", READABLE)
    flat = _w(tmp_path, "secure/sandbox.py", _flatten(READABLE))
    [f] = detect_flattened_copies([good, flat])
    assert f.detector == "flattened_copy"
    assert f.evidence.file.endswith("secure/sandbox.py")
    assert f.attributes["token_similarity"] >= 0.9
    assert any(r.endswith("wrapper/sandbox.py") for r in f.evidence.related_files)


def test_an_unreadable_file_with_no_twin_is_left_to_unassessable_file(tmp_path):
    other = _w(tmp_path, "other.py", "def unrelated():\n    return 42\n")
    flat = _w(tmp_path, "flat.py", _flatten(READABLE))
    assert detect_flattened_copies([other, flat]) == []


SAME_WORDS_OTHER_CODE = '''import hashlib


class Sandbox:
    def digest(self, payload, capabilities=None):
        capabilities = capabilities or {}
        for requested in sorted(capabilities):
            if requested not in payload:
                continue
            payload = hashlib.sha256((payload + requested).encode()).hexdigest()
        return payload

    def validate_capabilities(self, requested, missing=()):
        return [r for r in requested if r in missing] or None
'''


def test_same_vocabulary_different_code_is_not_a_copy(tmp_path):
    """Shares the names (so it passes the prefilter) but not the code."""
    other = _w(tmp_path, "other.py", SAME_WORDS_OTHER_CODE)
    flat = _w(tmp_path, "flat.py", _flatten(READABLE))
    assert detect_flattened_copies([other, flat]) == []


def test_two_readable_copies_are_not_this_finding(tmp_path):
    a = _w(tmp_path, "a.py", READABLE)
    b = _w(tmp_path, "b.py", READABLE + "\n# trailing note\n")
    assert detect_flattened_copies([a, b]) == []


def test_all_three_are_registered():
    names = set(registered_detectors())
    assert {"commented_out_module", "flattened_copy", "undefined_self_method"} <= names
