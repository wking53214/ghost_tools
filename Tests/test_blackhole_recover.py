"""Getting the original back, and refusing to when it is not the original.

The whole module rests on one claim: flattening replaces whitespace and
nothing else, so `collapse` is invariant under it and a text that collapses
to what a flattened file collapses to IS its original. These tests are about
that claim holding in both directions -- recovering when it is true, and
staying silent when something merely looks close.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from blackhole_extrapolator.recover import (
    CONTAINED,
    NBSP,
    REPAIR_NBSP,
    recovered_name,
    IDENTICAL,
    MANIFEST,
    NONE,
    RELATED,
    Source,
    collapse,
    collapse_with_index,
    harvest,
    recover_one,
    render_manifest,
    write_manifest,
    write_recovery,
)

ORIGINAL = textwrap.dedent('''\
    """A guard that only observes."""
    import time


    class Guard:
        def __init__(self, limit):
            self.limit = limit
            self.seen = []

        def observe(self, reading):
            self.seen.append((time.time(), reading))
            return reading < self.limit
''')

# The two shapes measured in the wild. One replaced each newline with a
# single space and left the indentation alone; the other collapsed every
# whitespace run, indentation included.
INDENT_KEPT = ORIGINAL.replace("\n", " ")
FULLY_COLLAPSED = " ".join(ORIGINAL.split())


def _source(text, origin="export.json", label="a message"):
    return [Source(origin=origin, label=label, text=text)]


# ------------------------------------------------------------- the invariant

@pytest.mark.parametrize("flattened", [INDENT_KEPT, FULLY_COLLAPSED],
                         ids=["indent-kept", "fully-collapsed"])
def test_collapse_is_invariant_under_flattening(flattened):
    """Neither shape adds, removes or reorders a non-whitespace character.
    That is the entire licence this module has to call a match a recovery."""
    assert collapse(flattened) == collapse(ORIGINAL)


@pytest.mark.parametrize("flattened", [INDENT_KEPT, FULLY_COLLAPSED],
                         ids=["indent-kept", "fully-collapsed"])
def test_the_original_is_recovered_verbatim(tmp_path, flattened):
    path = tmp_path / "guard.py"
    path.write_text(flattened)
    r = recover_one(path, flattened, _source(ORIGINAL))
    assert r.verdict == IDENTICAL
    assert r.text == ORIGINAL
    assert r.is_recovered


def test_a_trailing_newline_does_not_prevent_a_match(tmp_path):
    """The flattened copy has no trailing newline and the original does.
    A collapse that did not strip would call these different texts."""
    flattened = FULLY_COLLAPSED.rstrip()
    r = recover_one(tmp_path / "g.py", flattened, _source(ORIGINAL + "\n\n"))
    assert r.verdict == IDENTICAL


# --------------------------------------------------- code inside a message

def test_code_wrapped_in_prose_recovers_only_the_code(tmp_path):
    """A message is usually commentary around a code block. The span is
    located in the collapsed form and sliced out of the REAL text, so what
    comes back is the original's own bytes rather than a re-derivation."""
    message = ("Here is the guard you asked for.\n\n" + ORIGINAL
               + "\nLet me know if you want the async version.")
    r = recover_one(tmp_path / "g.py", FULLY_COLLAPSED, _source(message))
    assert r.verdict == CONTAINED
    assert r.text.strip() == ORIGINAL.strip()
    # Real line breaks and real indentation, not a rebuilt approximation.
    assert r.text.count("\n") >= 10
    assert "\n        self.limit = limit" in r.text
    assert "Here is the guard" not in r.text
    assert "async version" not in r.text


def test_the_index_points_into_the_original_text():
    text = "a\n\n   bb\tccc "
    collapsed, index = collapse_with_index(text)
    assert collapsed == "a bb ccc"
    assert len(index) == len(collapsed)
    for position, character in enumerate(collapsed):
        if character != " ":
            assert text[index[position]] == character


def test_a_fenced_block_gives_an_exact_match(tmp_path):
    """Harvesting the fence as well as the whole message is what turns a
    `contained` into an `identical`: the block is the file, exactly."""
    message = "Sure:\n\n```python\n" + ORIGINAL + "```\n\nThat covers it."
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"messages": [{"text": message}]}))
    r = recover_one(tmp_path / "g.py", FULLY_COLLAPSED, harvest([export]))
    assert r.verdict == IDENTICAL
    assert r.text == ORIGINAL


# --------------------------------------------------------- staying silent

DIFFERENT_DRAFT = ORIGINAL.replace("self.seen.append((time.time(), reading))",
                                   "self.seen.append(reading)\n        self.count += 1")


def test_a_different_draft_is_named_and_never_written(tmp_path):
    """The verdict that keeps this honest. Measured 2026-09-10 against a real
    export: four files scored 100% identifier overlap against a message that
    was a DIFFERENT VERSION of the same code. High overlap is not the same
    claim as identical bytes, and treating it as one is how a plausible file
    gets committed as a real one."""
    path = tmp_path / "g.py"
    path.write_text(FULLY_COLLAPSED)
    r = recover_one(path, FULLY_COLLAPSED, _source(DIFFERENT_DRAFT))
    assert r.verdict == RELATED
    assert r.text is None
    assert not r.is_recovered
    assert r.overlap >= 0.6
    with pytest.raises(ValueError):
        write_recovery(r, tmp_path / "out")


def test_a_match_starting_mid_token_is_not_a_match(tmp_path):
    """`port os` is found inside `import os` by a plain substring search,
    and the span recovered from it starts mid-identifier. Because collapse
    normalises every gap to one space, a real boundary is a space or an end."""
    flattened = FULLY_COLLAPSED[3:]          # starts partway into `"""A guard`
    r = recover_one(tmp_path / "g.py", flattened, _source("xxx" + ORIGINAL))
    assert r.verdict != CONTAINED


def test_a_blob_of_everything_is_not_a_close_relative(tmp_path):
    """Measured 2026-09-10: a derived CSV holding EVERY message in an export
    scored 100% against eight different files, because one-directional
    coverage rewards a candidate for being large. Union in the denominator
    prices that in."""
    blob = DIFFERENT_DRAFT + "\n" + "\n".join(
        "def unrelated_%d(argument_%d):\n    return argument_%d\n" % (i, i, i)
        for i in range(400))
    r = recover_one(tmp_path / "g.py", FULLY_COLLAPSED, _source(blob))
    assert r.verdict == NONE


def test_something_unrelated_is_not_related(tmp_path):
    other = "import os\n\n\ndef listing(root):\n    return sorted(os.listdir(root))\n"
    r = recover_one(tmp_path / "g.py", FULLY_COLLAPSED, _source(other))
    assert r.verdict == NONE
    assert r.text is None


def test_a_flattened_copy_in_the_corpus_is_not_offered_as_the_original(tmp_path):
    """It collapses to the same thing, because it IS the same thing. A
    candidate with no line breaks cannot be the original of a file whose
    defect is that its line breaks are gone."""
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"parts": [FULLY_COLLAPSED, INDENT_KEPT]}))
    r = recover_one(tmp_path / "g.py", FULLY_COLLAPSED, harvest([export]))
    assert r.verdict == NONE


def test_an_empty_file_recovers_nothing(tmp_path):
    assert recover_one(tmp_path / "g.py", "   \n  ", _source(ORIGINAL)).verdict == NONE


# --------------------------------------------------------------- the corpus

def test_the_reader_does_not_know_the_export_schema(tmp_path):
    """ChatGPT, Claude, Copilot and Gemini nest message text differently. A
    reader that knows one shape returns nothing on the other three, which
    reads exactly like `the original is not in there`."""
    export = tmp_path / "export.json"
    export.write_text(json.dumps(
        {"conversations": [{"mapping": {"a": {"message": {"content": {
            "parts": [ORIGINAL]}}}}}]}))
    assert recover_one(tmp_path / "g.py", FULLY_COLLAPSED,
                       harvest([export])).verdict == IDENTICAL


def test_transcripts_on_disk_work_as_a_corpus(tmp_path):
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "chat.md").write_text("## turn\n\n" + ORIGINAL)
    r = recover_one(tmp_path / "g.py", FULLY_COLLAPSED, harvest([tmp_path / "corpus"]))
    assert r.verdict in (IDENTICAL, CONTAINED)


def test_an_html_encoded_corpus_is_decoded(tmp_path):
    """A rendered export stores `\"\"\"` as `&quot;` three times, which no amount
    of whitespace normalisation turns back into a match. Decoding is lossless,
    only ADDS a candidate, and the decoded one still has to pass the same
    exact collapse test as any other."""
    encoded = (ORIGINAL.replace("&", "&amp;").replace('"', "&quot;")
               .replace("<", "&lt;"))
    export = tmp_path / "messages.jsonl"
    export.write_text(json.dumps({"text": encoded}))
    r = recover_one(tmp_path / "g.py", FULLY_COLLAPSED, harvest([export]))
    assert r.verdict == IDENTICAL
    assert r.text == ORIGINAL


def test_prose_is_not_harvested_as_code(tmp_path):
    export = tmp_path / "notes.md"
    export.write_text("Some notes.\nMore notes.\nStill more.\nAnd more.\n")
    assert harvest([export]) == []


# --------------------------------------------------------------- the writing

def test_a_recovered_file_carries_no_header(tmp_path):
    """A reconstruction is annotated because it is a guess. Annotating a
    byte-faithful original is how it stops being one."""
    path = tmp_path / "guard.py"
    path.write_text(FULLY_COLLAPSED)
    r = recover_one(path, FULLY_COLLAPSED, _source(ORIGINAL))
    target = write_recovery(r, tmp_path / "out")
    assert target.read_text() == ORIGINAL
    assert target.parent != path.parent


def test_a_recovery_that_does_not_collapse_back_is_refused(tmp_path):
    """The match test, run again against what is about to hit the disk."""
    path = tmp_path / "guard.py"
    path.write_text(FULLY_COLLAPSED)
    r = recover_one(path, FULLY_COLLAPSED, _source(ORIGINAL))
    path.write_text("x = 1\n")          # the file changed underneath us
    with pytest.raises(ValueError):
        write_recovery(r, tmp_path / "out")


def test_an_existing_recovery_is_never_overwritten(tmp_path):
    path = tmp_path / "guard.py"
    path.write_text(FULLY_COLLAPSED)
    r = recover_one(path, FULLY_COLLAPSED, _source(ORIGINAL))
    write_recovery(r, tmp_path / "out")
    with pytest.raises(FileExistsError):
        write_recovery(r, tmp_path / "out")


# ------------------------------------------------ a corpus that renders HTML

# What an HTML export leaves behind: `&nbsp;` decoded to U+00A0 where the
# code had ordinary indentation.
HTML_RENDERED = ORIGINAL.replace("\n    ", "\n" + NBSP * 4).replace(
    "\n        ", "\n" + NBSP * 8)


def test_a_non_breaking_space_still_counts_as_whitespace():
    """The reason an HTML-rendered corpus matches at all, and the reason
    substituting cannot invalidate the collapse check that guards the write."""
    assert collapse(HTML_RENDERED) == collapse(ORIGINAL)


def test_an_html_indent_is_repaired_only_because_it_then_parses(tmp_path):
    """Python rejects U+00A0 outside a string, so a byte-faithful recovery
    from an HTML export does not parse. The substitution is applied because
    it demonstrably fixes that, not because it looks like a good idea."""
    path = tmp_path / "guard.py"
    path.write_text(FULLY_COLLAPSED)
    r = recover_one(path, FULLY_COLLAPSED, _source(HTML_RENDERED))
    assert r.verdict == IDENTICAL
    assert r.repairs == (REPAIR_NBSP,)
    assert r.parses
    assert NBSP not in r.text
    # And it is still the same file, by the same test the match was made on.
    assert collapse(r.text) == collapse(FULLY_COLLAPSED)
    write_recovery(r, tmp_path / "out")


def test_damage_the_substitution_cannot_fix_is_left_alone(tmp_path):
    """Two of the 21 recoveries measured on 2026-09-10 carry smart quotes and
    a truncated string. Reported as not parsing, never patched: damage in the
    corpus is a fact about the corpus."""
    broken = HTML_RENDERED.replace('"""A guard', '\u201cA guard')
    r = recover_one(tmp_path / "g.py", collapse(broken), _source(broken))
    assert r.verdict == IDENTICAL
    assert r.repairs == ()
    assert not r.parses
    assert NBSP in r.text


def test_a_non_breaking_space_inside_a_string_survives(tmp_path):
    """The one place U+00A0 is legitimate, and the reason the substitution is
    gated on the file not parsing. This one parses as it stands, so there is
    nothing to fix and nothing is touched."""
    original = ('LABEL = "12' + NBSP + 'kg"\n'
                "import time\n\n\ndef stamp():\n    return (time.time(), LABEL)\n")
    flattened = " ".join(original.split())
    r = recover_one(tmp_path / "g.py", flattened, _source(original))
    assert r.verdict == IDENTICAL
    assert r.repairs == ()
    assert NBSP in r.text
    assert r.parses


def test_a_recovery_that_is_only_comments_does_not_parse(tmp_path):
    """The silent half of flattening. A file whose content is one comment
    parses cleanly and defines nothing, so `parses` asks for a statement."""
    comments = "# import time\n# def observe(reading):\n#     return reading\n"
    r = recover_one(tmp_path / "g.py", " ".join(comments.split()), _source(comments))
    assert r.verdict == IDENTICAL
    assert not r.parses


def test_a_repair_that_changes_nothing_is_not_recorded(tmp_path):
    r = recover_one(tmp_path / "g.py", FULLY_COLLAPSED, _source(ORIGINAL))
    assert r.repairs == ()
    assert r.parses


# ------------------------------------------------------- names that collide

def test_two_repositories_may_hold_the_same_filename(tmp_path):
    """Measured 2026-09-10: naming a recovery after the stem alone refused 6
    of 27 as `a proposal already exists`, when nothing was in conflict."""
    for repo in ("citadel", "kernel"):
        (tmp_path / repo).mkdir()
        (tmp_path / repo / "artifact_1.py").write_text(FULLY_COLLAPSED)
    out = tmp_path / "out"
    written = []
    for repo in ("citadel", "kernel"):
        path = tmp_path / repo / "artifact_1.py"
        r = recover_one(path, FULLY_COLLAPSED, _source(ORIGINAL))
        written.append(write_recovery(r, out, root=tmp_path))
    assert len({p.name for p in written}) == 2
    assert "citadel" in written[0].name and "kernel" in written[1].name


def test_without_a_root_the_name_falls_back_to_the_stem(tmp_path):
    assert recovered_name(Path("/a/b/guard.py")) == "guard.recovered.py"


def test_the_manifest_says_where_each_file_came_from(tmp_path):
    path = tmp_path / "guard.py"
    path.write_text(FULLY_COLLAPSED)
    recovered = recover_one(path, FULLY_COLLAPSED, _source(ORIGINAL))
    other = tmp_path / "draft.py"
    other.write_text(FULLY_COLLAPSED)
    related = recover_one(other, FULLY_COLLAPSED, _source(DIFFERENT_DRAFT))

    text = render_manifest([recovered, related], root=tmp_path)
    assert "guard.py" in text and "draft.py" in text
    assert IDENTICAL in text and RELATED in text
    assert "1 identical, 0 contained, 1 related (not written), 0 unmatched." in text
    assert "parses" in text
    assert write_manifest([recovered, related], tmp_path / "out").name == MANIFEST
