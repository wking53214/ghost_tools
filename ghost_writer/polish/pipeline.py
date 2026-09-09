# Vendored from wking53214/content-polish-pipeline (MIT), commit
# 44bf225abd819008f898510c37ea5b432cb44532, on 2026-09-09. See
# PROVENANCE.md at the ghost_tools root for what changed in the copy.
"""
ContentPolishPipeline: Async retry loop for LLM output validation.

Calls an external LLM gateway, validates output against multiple filters,
and retries with recalibration feedback on failure.
"""

import hashlib
import hmac
import logging
import time
from typing import Any, Awaitable, Callable, Dict

from .filters import (
    EmpiricalValidationFilter,
    PersonalPronounFilter,
    SpeculativeLanguageFilter,
)

logger = logging.getLogger("ghost_writer.polish")


class ContentPolishPipeline:
    """
    LLM output quality gate: retries generation until output passes
    pronoun/speculation/evidence checks or max attempts exhausted.

    Args:
        execution_gateway: Async callable(prompt: str) -> str
            The LLM call. Receives the prompt, returns generated text.
        max_attempts: Max number of attempts (must be >= 1) before giving up.
        signing_key: HMAC key for payload signatures. The default key is a
            well-known constant, so ``payload_signature`` only provides
            authenticity if you pass your own secret key here.

    Raises:
        ValueError: if ``max_attempts`` is less than 1.
    """

    DEFAULT_SIGNING_KEY = b"CONTENTPOLISH_DEFAULT_HMAC_KEY"

    def __init__(
        self,
        execution_gateway: Callable[[str], Awaitable[str]],
        max_attempts: int = 5,
        signing_key: bytes = DEFAULT_SIGNING_KEY,
    ):
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")

        self.gateway = execution_gateway
        self.max_attempts = max_attempts
        self._signing_key = signing_key
        if signing_key == self.DEFAULT_SIGNING_KEY:
            logger.warning(
                "ContentPolishPipeline is using the default signing key; "
                "payload_signature will not provide authenticity. Pass a "
                "secret signing_key to enable verification."
            )

        self.pronoun_filter = PersonalPronounFilter()
        self.speculation_filter = SpeculativeLanguageFilter()
        self.empirical_filter = EmpiricalValidationFilter()

    def _compute_signature(self, text: str) -> str:
        """Generate HMAC-SHA384 signature for the output."""
        return hmac.new(
            self._signing_key, text.encode("utf-8"), hashlib.sha384
        ).hexdigest()

    def _normalize(self, text: str) -> str:
        """Basic text normalization: strip extra whitespace."""
        return " ".join(text.split())

    async def execute(self, input_prompt: str) -> Dict[str, Any]:
        """
        Retry loop: call LLM, validate, and recalibrate on failure.

        Args:
            input_prompt: Initial prompt to send to the LLM.

        Returns:
            {
                "execution_status": "SUCCESS" | "CRITICAL_FAILURE",
                "validated_content": str (the final text, if successful),
                "retry_attempts": int,
                "violations": list[str] (constraint violations on last attempt),
                "latency_duration_ms": float,
                "payload_signature": str,
            }
        """
        active_prompt = input_prompt
        start_time = time.time()
        historical_hashes: set[str] = set()

        for iteration in range(1, self.max_attempts + 1):
            logger.debug(
                f"ContentPolishPipeline attempt {iteration}/{self.max_attempts}"
            )

            # Call the LLM.
            try:
                raw_response = await self.gateway(active_prompt)
            except Exception as e:
                logger.error(f"LLM gateway error on attempt {iteration}: {e}")
                return {
                    "execution_status": "CRITICAL_FAILURE",
                    "validated_content": None,
                    "retry_attempts": iteration - 1,
                    "violations": [f"LLM gateway error: {type(e).__name__}"],
                    "latency_duration_ms": round((time.time() - start_time) * 1000, 2),
                    "payload_signature": None,
                }

            normalized_response = self._normalize(raw_response)

            # Run validation filters.
            pronoun_check = self.pronoun_filter.passes(normalized_response)
            speculation_check = (
                self.speculation_filter.passes(normalized_response)
            )
            empirical_check = self.empirical_filter.passes(normalized_response)

            # Check for duplicates (infinite loop prevention).
            response_hash = hashlib.sha256(
                normalized_response.encode("utf-8")
            ).hexdigest()
            duplicate_detected = response_hash in historical_hashes

            # All checks pass: success.
            if (
                pronoun_check
                and speculation_check
                and empirical_check
                and not duplicate_detected
            ):
                total_latency_ms = (time.time() - start_time) * 1000.0
                signature = self._compute_signature(normalized_response)

                logger.info(
                    f"ContentPolishPipeline SUCCESS after {iteration} attempt(s)"
                )
                return {
                    "execution_status": "SUCCESS",
                    "validated_content": normalized_response,
                    "retry_attempts": iteration,
                    "violations": [],
                    "latency_duration_ms": round(total_latency_ms, 2),
                    "payload_signature": signature,
                }

            # Validation failed: collect reasons and retry with feedback.
            historical_hashes.add(response_hash)
            failures = []

            if not pronoun_check:
                pronouns = self.pronoun_filter.violations(normalized_response)
                failures.append(
                    f"First-person pronouns detected: {', '.join(pronouns)}"
                )

            if not speculation_check:
                hedges = self.speculation_filter.violations(normalized_response)
                failures.append(
                    f"Speculative language detected: {', '.join(hedges)}"
                )

            if not empirical_check:
                failures.append(
                    "Missing empirical support (metrics, evidence, or citations)"
                )

            if duplicate_detected:
                failures.append("Duplicate generation detected (infinite loop risk)")

            # Build recalibration feedback for next iteration.
            feedback = "\n".join(failures)
            active_prompt = (
                f"{input_prompt}\n\n"
                f"[RECALIBRATION FEEDBACK - Attempt {iteration}]:\n"
                f"Prior output failed validation due to:\n{feedback}\n\n"
                f"Please regenerate, avoiding these issues."
            )

            logger.debug(f"Recalibrating on iteration {iteration}: {len(failures)} issues")

        # Max attempts exhausted.
        logger.error(
            f"ContentPolishPipeline CRITICAL_FAILURE after {self.max_attempts} attempts"
        )
        return {
            "execution_status": "CRITICAL_FAILURE",
            "validated_content": None,
            "retry_attempts": self.max_attempts,
            "violations": failures,
            "latency_duration_ms": round((time.time() - start_time) * 1000, 2),
            "payload_signature": None,
        }
