"""ghost_writer.polish -- the quality gate around correct.py's LLM call.

Vendored from wking53214/content-polish-pipeline (MIT) at commit
44bf225abd819008f898510c37ea5b432cb44532 on 2026-09-09, when that repo was
retired into this one. The MIT notice is in LICENSE beside this file; the
record of what was copied and what changed is in PROVENANCE.md at the
ghost_tools root.

Three filters, each exposing ``passes(text) -> bool``, and a retry loop
(``ContentPolishPipeline``) that calls an async gateway, runs the filters,
and feeds the violations back into the prompt until the output passes or
``max_attempts`` is spent. ghost_writer.correct is the only consumer.
"""

from .filters import (
    EmpiricalValidationFilter,
    PersonalPronounFilter,
    SpeculativeLanguageFilter,
)
from .pipeline import ContentPolishPipeline

__all__ = [
    "ContentPolishPipeline",
    "EmpiricalValidationFilter",
    "PersonalPronounFilter",
    "SpeculativeLanguageFilter",
]
