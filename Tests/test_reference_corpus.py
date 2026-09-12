"""Naming a function in this tool can blind a detector in every repository.

THE COUPLING THIS FILE MAKES VISIBLE (v1.6.1)

`detect_vestigial_domain_names` decides which words belong to a domain by
subtracting the words that are "just Python", and it takes that reference
corpus from this tool's own source. A word ghost_buster uses as an
identifier is therefore generic everywhere, forever, in every repository
the tool will ever scan.

The docstring on `_generic_vocabulary` knows that scanning ghost_buster
with itself is vacuous. What nobody had written down is the other
direction: EDITING ghost_buster changes what the detector can see
elsewhere.

Measured while fixing the surgeon's-notes defect. A new helper was called
`_patient_dirt`, which put the word `patient` into the reference corpus,
which removed it from the pediatric domain vocabulary, which silently
narrowed the detector. Two naming tests failed, and neither said anything
about the real cause. The helper is `_dirty_paths` now.

So this file states the coupling as a checked claim. When it fails, the
fix is almost always to rename the new identifier, not to edit the list.
Widening the reference corpus is a decision about a word in every
repository, and it should cost a measurement rather than happen as a side
effect of naming a local function.
"""
from __future__ import annotations

import ast
import pathlib
import re

from ghost_buster.naming import _identifiers

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "ghost_buster"
_SPLIT = re.compile(r"[_\W]+|(?<=[a-z0-9])(?=[A-Z])")

#: Domain words the naming suite's fixtures depend on being domain words.
#: Two toy cassettes, one clinical and one industrial. If ghost_buster
#: starts using one of these as an identifier, the word becomes generic and
#: the detector stops reporting it for everybody.
CLINICAL = {"patient", "pediatric", "oxygen", "respiratory", "saturation", "heart"}
INDUSTRIAL = {"vibration", "bearing", "asset"}

#: Words BOTH toy cassettes use. These are not domain vocabulary, and the
#: naming suite proves it by asserting they stay out of every domain's
#: words. That proof needs them to reach the "appears in more than one
#: cassette" rule, and a word already in the reference corpus never gets
#: that far, so the rule stops being tested.
#:
#: Added after `subject` slipped in, inside a constant named
#: _ATTRIBUTED_TO_A_SUBJECT, and a naming mutant went from killed to
#: surviving. The first version of this file listed only domain words and
#: did not catch it.
SHARED_BY_BOTH_CASSETTES = {"subject", "reading"}


def _reference_corpus() -> set[str]:
    words = set()
    for path in sorted(PACKAGE.glob("*.py")):
        for name in _identifiers(ast.parse(path.read_text(encoding="utf-8"))):
            words.update(part.lower() for part in _SPLIT.split(name) if part)
    return words


def test_the_tool_does_not_speak_the_domains_it_measures():
    swallowed = sorted((CLINICAL | INDUSTRIAL | SHARED_BY_BOTH_CASSETTES)
                       & _reference_corpus())
    assert not swallowed, (
        "ghost_buster now uses these domain words as identifiers: "
        + ", ".join(swallowed)
        + ". Because the reference corpus is this package's own source, each "
        "one is now 'just Python' and vestigial_domain_name will no longer "
        "report it in ANY repository. Rename the identifier. Only widen the "
        "corpus deliberately, with a measurement."
    )


def test_the_reference_corpus_is_this_package():
    """If the corpus ever stops being the package, this file is measuring
    nothing and should be rewritten rather than quietly passing."""
    corpus = _reference_corpus()
    assert "detector" in corpus and "finding" in corpus
    assert len(corpus) > 500, f"reference corpus is only {len(corpus)} words"


def test_prose_is_not_part_of_the_corpus():
    """The metaphor is safe. `operate.py` calls the repository a patient in
    almost every docstring, and none of that reaches the corpus, because
    only identifiers do."""
    assert "patient" in (PACKAGE / "operate.py").read_text(encoding="utf-8")
    assert "patient" not in _reference_corpus()
