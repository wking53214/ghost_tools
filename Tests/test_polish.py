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
from ghost_writer.polish.oscillation import OscillationDetector
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


class TestOscillationDetector(unittest.TestCase):
    def setUp(self):
        self.detector = OscillationDetector(max_history=3)

    def test_first_observation_is_never_a_repeat(self):
        self.assertFalse(self.detector.observe("a"))

    def test_exact_repeat_is_detected(self):
        self.detector.observe("a")
        self.assertTrue(self.detector.observe("a"))

    def test_comparison_is_exact_not_case_insensitive(self):
        # Deliberate deviation from the source branch: this detector does
        # no normalization of its own. Different case is a different value.
        self.detector.observe("Repeated text.")
        self.assertFalse(self.detector.observe("repeated text."))

    def test_history_is_bounded(self):
        self.detector.observe("a")
        self.detector.observe("b")
        self.detector.observe("c")
        self.detector.observe("d")  # evicts "a"
        # "a" was evicted, so this is treated as a fresh value, and this
        # call's own append evicts "b" in turn.
        self.assertFalse(self.detector.observe("a"))
        self.assertEqual(self.detector.get_history(), ["c", "d", "a"])

    def test_reset_clears_history(self):
        self.detector.observe("a")
        self.detector.reset()
        self.assertFalse(self.detector.observe("a"))
        self.assertEqual(self.detector.get_history(), ["a"])

    def test_get_history_snapshot_is_independent_of_the_live_deque(self):
        self.detector.observe("a")
        snapshot = self.detector.get_history()
        self.detector.observe("b")
        self.assertEqual(snapshot, ["a"])

    def test_max_history_must_be_positive(self):
        with self.assertRaises(ValueError):
            OscillationDetector(max_history=0)
        with self.assertRaises(ValueError):
            OscillationDetector(max_history=-1)


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
        self.assertTrue(result["oscillation_detected"])

    async def test_oscillation_detected_is_false_when_nothing_repeats(self):
        mock_llm = AsyncMock(
            return_value="The system demonstrated a 25% performance improvement."
        )

        pipeline = ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=3)
        result = await pipeline.execute("Summarize the results.")

        self.assertEqual(result["execution_status"], "SUCCESS")
        self.assertFalse(result["oscillation_detected"])

    async def test_oscillation_detector_resets_between_execute_calls(self):
        # The second execute() call opens with the exact same non-compliant
        # string the first call opened with. If reset() didn't clear the
        # detector's own history (only oscillation_detected reset to False
        # each call), this attempt would be flagged as a repeat of the
        # first call's leftover history, even though it is genuinely this
        # call's first observation.
        mock_llm = AsyncMock(
            side_effect=[
                "This is better.",
                "Data shows a 25% gain.",
                "This is better.",
                "More data shows a 30% gain.",
            ]
        )
        pipeline = ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=2)

        first = await pipeline.execute("Summarize the results.")
        self.assertEqual(first["execution_status"], "SUCCESS")
        self.assertFalse(first["oscillation_detected"])

        second = await pipeline.execute("Summarize the results, take two.")
        self.assertEqual(second["execution_status"], "SUCCESS")
        self.assertFalse(second["oscillation_detected"])

    async def test_recalibration_feedback_names_the_violation(self):
        responses = [
            "This is better.",                        # no evidence marker
            "Analysis shows a 30% improvement.",
        ]
        mock_llm = AsyncMock(side_effect=responses)

        pipeline = ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=3)
        result = await pipeline.execute("Summarize the results.")

        self.assertEqual(result["execution_status"], "SUCCESS")
        first_prompt = mock_llm.call_args_list[0].args[0]
        retry_prompt = mock_llm.call_args_list[1].args[0]
        # The first call is the caller's prompt untouched; the retry carries
        # the violation that rejected the first response, so the model is
        # told what to avoid rather than merely asked again.
        self.assertNotIn("RECALIBRATION FEEDBACK", first_prompt)
        self.assertIn("[RECALIBRATION FEEDBACK - Attempt 1]", retry_prompt)
        self.assertIn("Missing empirical support", retry_prompt)
        self.assertIn("Summarize the results.", retry_prompt)

    async def test_whitespace_is_normalized_in_validated_content(self):
        mock_llm = AsyncMock(return_value="  Research   data\n\ndemonstrated a 25%\tgain.  ")

        pipeline = ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=1)
        result = await pipeline.execute("Summarize the results.")

        self.assertEqual(result["execution_status"], "SUCCESS")
        self.assertEqual(
            result["validated_content"], "Research data demonstrated a 25% gain.",
        )

    async def test_signature_stable_for_same_input(self):
        mock_llm = AsyncMock(return_value="Research data demonstrated a 25% gain.")
        key = b"secret-test-key"

        r1 = await ContentPolishPipeline(mock_llm, signing_key=key).execute("x")
        r2 = await ContentPolishPipeline(mock_llm, signing_key=key).execute("x")

        self.assertEqual(r1["execution_status"], "SUCCESS")
        self.assertEqual(r1["payload_signature"], r2["payload_signature"])
        self.assertEqual(len(r1["payload_signature"]), 96)  # SHA-384 hex

    async def test_signature_depends_on_the_signing_key(self):
        # Same validated content, two different secrets: a signature that
        # does not use the key would be identical in both.
        mock_llm = AsyncMock(return_value="Research data demonstrated a 25% gain.")

        r1 = await ContentPolishPipeline(mock_llm, signing_key=b"key-one").execute("x")
        r2 = await ContentPolishPipeline(mock_llm, signing_key=b"key-two").execute("x")

        self.assertEqual(r1["execution_status"], "SUCCESS")
        self.assertEqual(r2["execution_status"], "SUCCESS")
        self.assertEqual(r1["validated_content"], r2["validated_content"])
        self.assertNotEqual(r1["payload_signature"], r2["payload_signature"])

    def test_max_attempts_must_be_positive(self):
        mock_llm = AsyncMock(return_value="ok")
        with self.assertRaises(ValueError):
            ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=0)
        with self.assertRaises(ValueError):
            ContentPolishPipeline(execution_gateway=mock_llm, max_attempts=-1)
