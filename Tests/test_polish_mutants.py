"""The proof that the ported pipeline suite in test_polish.py is not vacuous:
break ghost_writer/polish one way at a time in a scratch copy of the project
and run only that file. Every mutant here must be killed.

ghost_buster --mutate reported zero candidates in test_polish.py (no test
in it has a shape the tool mutates), so this is the hand-made complement,
the same arrangement test_gate_mutants.py has for the gate tests. The list
is only what test_polish.py kills on its own, and as of 0.6.2 that is
every mutant written for this code: nothing is held back as a known
survivor. Six of them survived the ported suite as received -- the
speculation filter's is_clean alias, the pipeline's pronoun and
speculation checks taken singly (every fixture that tripped one also
tripped another filter), the signature's dependence on the key, the
recalibration feedback text, and whitespace normalization -- and are here
because 0.6.1 and 0.6.2 added the tests that kill them. Adding a mutant
here without a test that kills it turns this file red.

A mutant that survives is a test-suite defect, reported as a failure with
the mutant named. The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

POLISH_TESTS = "Tests/test_polish.py"
_F = "ghost_writer/polish/filters.py"
_P = "ghost_writer/polish/pipeline.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    ("filters: pronoun pattern matches nothing", _F,
     'PRONOUNS = r"\\b(I|we|my|our|me|us)\\b"',
     'PRONOUNS = r"\\b(zzzz)\\b"'),
    ("filters: pronoun passes() always true", _F,
     "        return not re.search(self.PRONOUNS, text, re.IGNORECASE)\n",
     "        return True\n"),
    ("filters: pronoun violations() unsorted with duplicates", _F,
     "        matches = re.findall(self.PRONOUNS, text, re.IGNORECASE)\n        return sorted(set(matches))\n",
     "        matches = re.findall(self.PRONOUNS, text, re.IGNORECASE)\n        return list(matches)\n"),
    ("filters: pronoun is_clean no longer aliases passes", _F,
     "    # Backwards-compatible alias.\n    is_clean = passes\n\n"
     "    def violations(self, text: str) -> list[str]:\n        \"\"\"Return the unique pronouns",
     "    def is_clean(self, text: str) -> bool:\n        return True\n\n"
     "    def violations(self, text: str) -> list[str]:\n        \"\"\"Return the unique pronouns"),
    ("filters: hedge pattern matches nothing", _F,
     'HEDGES = r"\\b(might|may|could|seems|probably|perhaps|likely|i think|appears|arguably|suggest|may be)\\b"',
     'HEDGES = r"\\b(zzzz)\\b"'),
    ("filters: hedge passes() always true", _F,
     "        return not re.search(self.HEDGES, text, re.IGNORECASE)\n",
     "        return True\n"),
    ("filters: hedge violations() in text order", _F,
     "        matches = re.findall(self.HEDGES, text, re.IGNORECASE)\n        return sorted(set(matches))\n",
     "        matches = re.findall(self.HEDGES, text, re.IGNORECASE)\n        return list(matches)\n"),
    ("filters: empirical contract inverted", _F,
     "        return bool(re.search(self.EVIDENCE_MARKERS, text, re.IGNORECASE))\n",
     "        return not re.search(self.EVIDENCE_MARKERS, text, re.IGNORECASE)\n"),
    ("filters: empirical passes() always true", _F,
     "        return bool(re.search(self.EVIDENCE_MARKERS, text, re.IGNORECASE))\n",
     "        return True\n"),
    ("filters: empirical violations() always empty", _F,
     "        if not self.passes(text):\n"
     "            return [\"Missing empirical support (metrics, evidence, or research citations)\"]\n"
     "        return []\n",
     "        return []\n"),
    ("filters: empirical is_clean no longer aliases passes", _F,
     "    # Backwards-compatible alias.\n    is_clean = passes\n\n    def evidence_found",
     "    def is_clean(self, text: str) -> bool:\n        return True\n\n    def evidence_found"),
    ("filters: percentage marker dropped", _F,
     'EVIDENCE_MARKERS = r"(\\d+%|showed',
     'EVIDENCE_MARKERS = r"(showed'),
    ("filters: hedge is_clean no longer aliases passes", _F,
     "    # Backwards-compatible alias.\n    is_clean = passes\n\n"
     "    def violations(self, text: str) -> list[str]:\n        \"\"\"Return the unique hedging",
     "    def is_clean(self, text: str) -> bool:\n        return True\n\n"
     "    def violations(self, text: str) -> list[str]:\n        \"\"\"Return the unique hedging"),
    ("pipeline: pronoun check forced true", _P,
     "            pronoun_check = self.pronoun_filter.passes(normalized_response)\n",
     "            pronoun_check = True\n"),
    ("pipeline: speculation check forced true", _P,
     "                self.speculation_filter.passes(normalized_response)\n",
     "                True\n"),
    ("pipeline: retry loop runs once", _P,
     "        for iteration in range(1, self.max_attempts + 1):\n",
     "        for iteration in range(1, 2):\n"),
    ("pipeline: empirical check forced true", _P,
     "            empirical_check = self.empirical_filter.passes(normalized_response)\n",
     "            empirical_check = True\n"),
    ("pipeline: duplicate detection disabled", _P,
     "            duplicate_detected = response_hash in historical_hashes\n",
     "            duplicate_detected = False\n"),
    ("pipeline: gateway exception no longer caught", _P,
     "            try:\n                raw_response = await self.gateway(active_prompt)\n"
     "            except Exception as e:\n",
     "            try:\n                raw_response = await self.gateway(active_prompt)\n"
     "            except ZeroDivisionError as e:\n"),
    ("pipeline: max_attempts validation removed", _P,
     "        if max_attempts < 1:\n"
     "            raise ValueError(f\"max_attempts must be >= 1, got {max_attempts}\")\n",
     ""),
    ("pipeline: success reports one attempt too few", _P,
     '                    "retry_attempts": iteration,\n',
     '                    "retry_attempts": iteration - 1,\n'),
    ("pipeline: success returns no validated_content", _P,
     '                    "validated_content": normalized_response,\n',
     '                    "validated_content": None,\n'),
    ("pipeline: exhaustion reports SUCCESS status", _P,
     '        return {\n            "execution_status": "CRITICAL_FAILURE",\n'
     '            "validated_content": None,\n            "retry_attempts": self.max_attempts,\n',
     '        return {\n            "execution_status": "SUCCESS",\n'
     '            "validated_content": None,\n            "retry_attempts": self.max_attempts,\n'),
    ("pipeline: signature uses SHA-256", _P,
     "            self._signing_key, text.encode(\"utf-8\"), hashlib.sha384\n",
     "            self._signing_key, text.encode(\"utf-8\"), hashlib.sha256\n"),
    ("pipeline: violations list emptied on exhaustion", _P,
     '            "violations": failures,\n',
     '            "violations": [],\n'),
    ("pipeline: signature ignores the key", _P,
     '            self._signing_key, text.encode("utf-8"), hashlib.sha384\n',
     '            b"", text.encode("utf-8"), hashlib.sha384\n'),
    ("pipeline: recalibration feedback dropped", _P,
     '                f"{input_prompt}\\n\\n"\n'
     '                f"[RECALIBRATION FEEDBACK - Attempt {iteration}]:\\n"\n',
     '                f"{input_prompt}\\n\\n"\n'),
    ("pipeline: whitespace normalization disabled", _P,
     '        return " ".join(text.split())\n',
     '        return text\n'),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_polish_mutant_is_killed(label, rel, old, new):
    assert_killed(label, POLISH_TESTS, run_tests_with_mutation(POLISH_TESTS, rel, old, new))


def test_polish_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        POLISH_TESTS, _P, "DEFAULT_SIGNING_KEY = b\"CONTENTPOLISH_DEFAULT_HMAC_KEY\"\n",
        "DEFAULT_SIGNING_KEY = b\"CONTENTPOLISH_DEFAULT_HMAC_KEY\"\n",
    )
    assert result.returncode == 0, result.stdout[-2000:]
