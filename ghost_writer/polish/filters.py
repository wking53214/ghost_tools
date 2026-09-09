# Vendored from wking53214/content-polish-pipeline (MIT), commit
# 44bf225abd819008f898510c37ea5b432cb44532, on 2026-09-09. See
# PROVENANCE.md at the ghost_tools root for what changed in the copy.
"""
Validation filters for output quality enforcement.

Each filter exposes ``passes(text) -> bool``: ``True`` means the text
satisfies that filter's requirement. Note the requirements differ in
direction -- ``PersonalPronounFilter`` and ``SpeculativeLanguageFilter``
pass when their target pattern is *absent*, while ``EmpiricalValidationFilter``
passes when its target pattern is *present*. ``is_clean`` is kept as an
alias of ``passes`` for backwards compatibility.

Designed for composition: multiple filters can be chained in the retry
loop until all pass.
"""

import re


class PersonalPronounFilter:
    """Detects first-person pronouns (I, we, my, our, me, us)."""

    PRONOUNS = r"\b(I|we|my|our|me|us)\b"

    def passes(self, text: str) -> bool:
        """Return True if text contains no first-person pronouns."""
        return not re.search(self.PRONOUNS, text, re.IGNORECASE)

    # Backwards-compatible alias.
    is_clean = passes

    def violations(self, text: str) -> list[str]:
        """Return the unique pronouns found in text, in sorted order."""
        matches = re.findall(self.PRONOUNS, text, re.IGNORECASE)
        return sorted(set(matches))


class SpeculativeLanguageFilter:
    """Detects hedging/qualifying language (might, may, could, seems, probably, etc.)."""

    HEDGES = r"\b(might|may|could|seems|probably|perhaps|likely|i think|appears|arguably|suggest|may be)\b"

    def passes(self, text: str) -> bool:
        """Return True if text contains no speculative language."""
        return not re.search(self.HEDGES, text, re.IGNORECASE)

    # Backwards-compatible alias.
    is_clean = passes

    def violations(self, text: str) -> list[str]:
        """Return the unique hedging phrases found in text, in sorted order."""
        matches = re.findall(self.HEDGES, text, re.IGNORECASE)
        return sorted(set(matches))


class EmpiricalValidationFilter:
    """Detects presence of empirical support: metrics, numbers, evidence markers."""

    # Markers of empirical support: "X%", "X resulted", "data shows", "study", etc.
    EVIDENCE_MARKERS = r"(\d+%|showed|results? in|demonstrated|proven|evidence|data|study|research|analysis|metric|measure)"

    def passes(self, text: str) -> bool:
        """
        Return True if text contains at least one marker of empirical support.

        Unlike the other filters, this one passes on *presence* of its
        pattern: the absence of any evidence marker is treated as a claim
        without backing.
        """
        return bool(re.search(self.EVIDENCE_MARKERS, text, re.IGNORECASE))

    # Backwards-compatible alias.
    is_clean = passes

    def evidence_found(self, text: str) -> list[str]:
        """Return the unique evidence markers found in text, in sorted order."""
        matches = re.findall(self.EVIDENCE_MARKERS, text, re.IGNORECASE)
        return sorted(set(matches))

    def violations(self, text: str) -> list[str]:
        """Return an explanation if no evidence markers are found."""
        if not self.passes(text):
            return ["Missing empirical support (metrics, evidence, or research citations)"]
        return []
