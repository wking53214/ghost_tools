"""
Tests for the vendored ghost_writer.polish pipeline and filters, ported from
content-polish-pipeline (tests/test_pipeline.py at commit 44bf225) when that
repo was retired into this one.

Run with: python -m pytest Tests/test_polish.py
"""

import logging
import unittest
from unittest.mock import AsyncMock

from ghost_writer.polish.filters import (
    EmpiricalValidationFilter,
    PersonalPronounFilter,
    SpeculativeLanguageFilter,
)
from ghost_writer.polish.pipeline import ContentPolishPipeline

# The pipeline logs a warning when the default signing key is used; the
# tests below construct pipelines with the default key on purpose, so
# silence that logger rather than let it print to stderr.
logging.getLogger("ghost_writer.polish").addHandler(logging.NullHandler())
logging.getLogger("ghost_writer.polish").propagate = False


class TestPersonalPronounFilter(unittest.TestCase):
    def setUp(self):
        self.filter = PersonalPronounFilter()

    def test_no_pronouns(self):
        text = "The system improved performance."
        self.assertTrue(self.filter.passes(text))

    def test_first_person_singular(self):
        text = "I believe this works."
        self.assertFalse(self.filter.passes(text))
        self.assertIn("I", self.filter.violations(text))

    def test_first_person_plural(self):
        text = "We recommend this approach."
        self.assertFalse(self.filter.passes(text))
        self.assertIn("We", self.filter.violations(text))

    def test_possessive_pronouns(self):
        text = "My analysis shows improvement."
        self.assertFalse(self.filter.passes(text))

    def test_is_clean_is_alias_of_passes(self):
        for text in ("The system improved.", "I did this.", "We and my and us."):
            self.assertEqual(self.filter.is_clean(text), self.filter.passes(text))

    def test_violations_unique_and_sorted(self):
        text = "We we WE us us me my our"
        result = self.filter.violations(text)
        self.assertEqual(result, sorted(set(result)))
        self.assertEqual(len(result), len(set(result)))


class TestSpeculativeLanguageFilter(unittest.TestCase):
    def setUp(self):
        self.filter = SpeculativeLanguageFilter()

    def test_no_hedges(self):
        text = "The system improved by 50%."
        self.assertTrue(self.filter.passes(text))

    def test_might(self):
        text = "This might improve performance."
        self.assertFalse(self.filter.passes(text))

    def test_probably(self):
        text = "This probably works."
        self.assertFalse(self.filter.passes(text))

    def test_i_think(self):
        text = "I think this is good."
        self.assertFalse(self.filter.passes(text))

    def test_violations_sorted(self):
        text = "It probably might seem to appear likely, perhaps."
        result = self.filter.violations(text)
        self.assertEqual(result, sorted(result))

    def test_is_clean_is_alias_of_passes(self):
        for text in ("The system improved.", "This might work.", "I think so, probably."):
            self.assertEqual(self.filter.is_clean(text), self.filter.passes(text))


class TestEmpiricalValidationFilter(unittest.TestCase):
    def setUp(self):
        self.filter = EmpiricalValidationFilter()

    def test_no_evidence(self):
        text = "This is better."
        self.assertFalse(self.filter.passes(text))
        self.assertEqual(len(self.filter.violations(text)), 1)

    def test_percentage(self):
        text = "This improved by 50%."
        self.assertTrue(self.filter.passes(text))
        self.assertEqual(self.filter.violations(text), [])

    def test_metrics_word(self):
        text = "Metrics show improvement."
        self.assertTrue(self.filter.passes(text))

    def test_data_word(self):
        text = "Data demonstrates the effect."
        self.assertTrue(self.filter.passes(text))

    def test_is_clean_is_alias_of_passes(self):
        for text in ("This is better.", "Data shows a 50% gain."):
            self.assertEqual(self.filter.is_clean(text), self.filter.passes(text))


class TestContentPolishPipeline(unittest.IsolatedAsyncioTestCase):
    async def test_success_on_first_try(self):
        mock_llm = AsyncMock(
            return_value="The system demonstrated a 25% performance improvement."
        )

        pipeline = ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=3)
        result = await pipeline.execute("Summarize the results.")

        self.assertEqual(result["execution_status"], "SUCCESS")
        self.assertEqual(result["retry_attempts"], 1)
        self.assertIsNotNone(result["validated_content"])
        self.assertEqual(len(result["violations"]), 0)

    async def test_retry_on_pronouns(self):
        responses = [
            "I believe this is a good result.",
            "Analysis shows this is a good result with 30% improvement.",
        ]
        mock_llm = AsyncMock(side_effect=responses)

        pipeline = ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=5)
        result = await pipeline.execute("Summarize the results.")

        self.assertEqual(result["execution_status"], "SUCCESS")
        self.assertEqual(result["retry_attempts"], 2)
        self.assertIn("good result with 30% improvement", result["validated_content"])

    async def test_pronoun_alone_is_rejected(self):
        # Evidence present, no hedge: only the pronoun check can reject this.
        mock_llm = AsyncMock(return_value="We measured a 25% improvement.")

        pipeline = ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=1)
        result = await pipeline.execute("Summarize the results.")

        self.assertEqual(result["execution_status"], "CRITICAL_FAILURE")
        self.assertEqual(result["violations"], ["First-person pronouns detected: We"])

    async def test_hedge_alone_is_rejected(self):
        # Evidence present, no pronoun: only the speculation check can reject this.
        mock_llm = AsyncMock(return_value="The data might show a 25% improvement.")

        pipeline = ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=1)
        result = await pipeline.execute("Summarize the results.")

        self.assertEqual(result["execution_status"], "CRITICAL_FAILURE")
        self.assertEqual(result["violations"], ["Speculative language detected: might"])

    async def test_max_attempts_exhausted(self):
        mock_llm = AsyncMock(return_value="I think this might be good.")

        pipeline = ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=2)
        result = await pipeline.execute("Summarize the results.")

        self.assertEqual(result["execution_status"], "CRITICAL_FAILURE")
        self.assertEqual(result["retry_attempts"], 2)
        self.assertIsNone(result["validated_content"])
        self.assertGreater(len(result["violations"]), 0)

    async def test_gateway_error(self):
        mock_llm = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        pipeline = ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=3)
        result = await pipeline.execute("Summarize the results.")

        self.assertEqual(result["execution_status"], "CRITICAL_FAILURE")
        self.assertIn("LLM gateway error", result["violations"][0])

    async def test_duplicate_generation_detected(self):
        # Same non-compliant output every time -> second attempt is a duplicate.
        mock_llm = AsyncMock(return_value="This is better.")

        pipeline = ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=4)
        result = await pipeline.execute("Summarize the results.")

        self.assertEqual(result["execution_status"], "CRITICAL_FAILURE")
        self.assertTrue(
            any("Duplicate generation detected" in v for v in result["violations"])
        )

    async def test_signature_stable_for_same_input(self):
        mock_llm = AsyncMock(return_value="Research data demonstrated a 25% gain.")
        key = b"secret-test-key"

        r1 = await ContentPolishPipeline(mock_llm, signing_key=key).execute("x")
        r2 = await ContentPolishPipeline(mock_llm, signing_key=key).execute("x")

        self.assertEqual(r1["execution_status"], "SUCCESS")
        self.assertEqual(r1["payload_signature"], r2["payload_signature"])
        self.assertEqual(len(r1["payload_signature"]), 96)  # SHA-384 hex

    def test_max_attempts_must_be_positive(self):
        mock_llm = AsyncMock(return_value="ok")
        with self.assertRaises(ValueError):
            ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=0)
        with self.assertRaises(ValueError):
            ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=-1)
