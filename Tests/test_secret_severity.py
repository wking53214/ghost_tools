"""How loudly a committed-secret finding is allowed to shout.

These tests build gitleaks entries directly rather than running the
binary, so they assert the same thing on a developer machine and on a CI
runner that has no gitleaks installed. The rest of the secrets suite is
skipped without it, and a rating rule that is only checked in one of
those two places is not checked.
"""
from __future__ import annotations

from pathlib import Path

from ghost_buster.schema import Category, Layer, Severity, Status
from ghost_buster.secrets import DETECTOR, _SHAPE_ONLY_RULES, _finding

ROOT = Path("/repo")


def _entry(rule: str) -> dict:
    return {
        "File": "src/app.py", "RuleID": rule, "StartLine": 12,
        "Commit": "a" * 40, "Description": "an example rule",
    }


def _for(rule: str):
    finding = _finding(ROOT, _entry(rule))
    assert finding is not None
    return finding


def test_a_provider_issued_prefix_is_critical():
    """AKIA, sk-, ghp_ and a PEM header are minted by a provider. A match
    is a credential, not a guess about one."""
    for rule in ("aws-access-token", "stripe-access-token", "private-key"):
        assert _for(rule).severity is Severity.CRITICAL, rule


def test_a_shape_only_match_is_major_not_critical():
    """Measured 2026-09-10: all 32 'generic-api-key' hits across a
    37-repository library were false positives. Rating a maybe at the same
    level as a confirmed leak is how the confirmed one gets scrolled past."""
    assert _SHAPE_ONLY_RULES, "the set may not be emptied without a reason"
    for rule in sorted(_SHAPE_ONLY_RULES):
        assert _for(rule).severity is Severity.MAJOR, rule


def test_a_shape_only_finding_says_to_verify_before_rotating():
    generic = _for("generic-api-key")
    assert "VERIFY THIS ONE BEFORE ROTATING" in generic.detail
    assert "If it is real, treat it as compromised" in generic.detail
    # The unconditional instruction must not also be present: telling
    # someone to rotate and to verify first, in one report, is telling them
    # nothing.
    assert "Treat the credential as compromised" not in generic.detail


def test_a_provider_finding_still_says_to_rotate_outright():
    specific = _for("aws-access-token")
    assert "Treat the credential as compromised" in specific.detail
    assert "VERIFY THIS ONE BEFORE ROTATING" not in specific.detail


def test_downgrading_changes_nothing_else_about_the_finding():
    """A severity judgement, not a filter. The finding is still produced,
    still mechanical, still confirmed, and still names its rule."""
    generic = _for("generic-api-key")
    assert generic.detector == DETECTOR
    assert generic.category is Category.COMMITTED_SECRET
    assert generic.layer is Layer.MECHANICAL
    assert generic.status is Status.CONFIRMED
    assert generic.attributes["rule"] == "generic-api-key"
    assert "src/app.py" in generic.summary


# ------------------------------------------------- the correlated finding

def _dup_correlation(rule: str):
    """Build the two findings correlate.py joins: a committed secret, and a
    duplicate-file report naming the same path and a twin."""
    from ghost_buster.correlate import CorrelationInput, correlate_secret_in_duplicated_file
    from ghost_buster.schema import Evidence, Finding

    secret = _for(rule)
    dup = Finding(
        detector="duplicate_file", category=Category.DUPLICATION,
        layer=Layer.MECHANICAL, severity=Severity.MINOR, status=Status.CONFIRMED,
        summary="byte-identical files",
        evidence=Evidence(
            file=secret.evidence.file,
            related_files=[secret.evidence.file, "tests/copy_of_app.py"],
        ),
    )
    out = correlate_secret_in_duplicated_file(CorrelationInput([secret, dup]))
    assert len(out) == 1, out
    return out[0]


def test_duplicating_a_shape_only_match_does_not_make_it_critical():
    """Measured 2026-09-10: a test fixture header in two byte-identical
    files produced four CRITICALs. Copying a maybe yields two copies of a
    maybe."""
    assert _dup_correlation("generic-api-key").severity is Severity.MAJOR


def test_duplicating_a_real_credential_stays_critical():
    assert _dup_correlation("aws-access-token").severity is Severity.CRITICAL
