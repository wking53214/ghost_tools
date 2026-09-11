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


def test_the_set_names_exactly_the_two_rules_that_match_shape():
    """Pinned by literal, deliberately.

    The test above iterates _SHAPE_ONLY_RULES and asserts each member is
    MAJOR, which is true of whatever the set happens to hold -- drop a
    rule and it still passes, having checked the ones that remain. This
    one names them, so removing either is a failing test rather than a
    quieter report.

    Both were established the same way: every hit checked at the file,
    line and column reported, across a 37-repository library on
    2026-09-10. 44 'generic-api-key', 4 'curl-auth-header', not one a
    credential. Adding a third is a judgement about a rule, so it should
    cost an edit here.
    """
    assert set(_SHAPE_ONLY_RULES) == {"curl-auth-header", "generic-api-key"}  # gitleaks:allow


def test_a_curl_auth_header_match_is_major_not_critical():
    """It anchors on the header name inside a curl command, not on
    anything a provider issued: -H "X-API-Key: prod_key_123" matches, and
    that is what all four library hits were."""
    curl = _for("curl-auth-header")
    assert curl.severity is Severity.MAJOR
    assert "VERIFY THIS ONE BEFORE ROTATING" in curl.detail


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


def test_duplicating_a_curl_auth_header_match_does_not_make_it_critical():
    """The second door, checked for the rule that was going through it.
    Duplication multiplies reach; it does not upgrade what a rule
    established."""
    assert _dup_correlation("curl-auth-header").severity is Severity.MAJOR
