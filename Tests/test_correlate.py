"""Tests for ghost_buster/correlate.py.

Connectors are pure functions over findings, so unlike the ref-graph and
git-history checks these can be tested against constructed findings -- the
findings ARE the input. Each connector gets both directions: it fires on
the shape it exists for, and stays silent on the near-miss that shares
some of that shape.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghost_buster.correlate import (
    PriorRun,
    load_prior_run,
    registered_connectors,
    render_report,
    run_connectors,
)
from ghost_buster.schema import Category, Evidence, Finding, Layer, Severity, Status


def _finding(detector, file, *, summary="s", severity=Severity.MAJOR,
             category=Category.OTHER, attributes=None, related=(), line=None,
             status=Status.CONFIRMED, layer=Layer.MECHANICAL) -> Finding:
    return Finding(
        detector=detector,
        category=category,
        layer=layer,
        severity=severity,
        status=status,
        summary=summary,
        evidence=Evidence(file=file, line_start=line, related_files=list(related)),
        attributes=dict(attributes or {}),
    )


def _secret(file="certs/key.pem", *, fingerprint="abc123:certs/key.pem:private-key:1",
            rule="private-key") -> Finding:
    return _finding(
        "committed_secret", file, severity=Severity.CRITICAL,
        category=Category.COMMITTED_SECRET, line=1,
        summary=f"a '{rule}' secret is committed in {file}:1:1 (commit abc123)",
        attributes={"fingerprint": fingerprint, "rule": rule, "commit": "abc123"},
    )


def _duplicate(file="certs/key.pem", others=("vendor/certs/key.pem",), digest="d" * 64) -> Finding:
    return _finding(
        "duplicate_file", file, category=Category.DUPLICATION, related=others,
        attributes={"content_sha256": digest, "group_size": str(1 + len(others))},
    )


def _test_status(file, *, kind="failing test", phase="collect", nodeid=None) -> Finding:
    return _finding(
        "test_status", file, category=Category.TEST_STATUS,
        summary=f"{kind}: {nodeid or file} cannot be collected",
        attributes={"kind": kind, "phase": phase, "nodeid": nodeid or f"{file}::test_x",
                    "outcome": "error"},
    )


def _marker(file="app/models.py", line=12) -> Finding:
    return _finding(
        "merge_conflict_marker", file, severity=Severity.CRITICAL,
        category=Category.MERGE_CONFLICT_MARKER, line=line,
        summary=f"unresolved merge conflict marker in {Path(file).name}",
    )


def _drift(file="README.md", documented="353", static="429", context="The suite has ") -> Finding:
    return _finding(
        "doc_test_count_drift", file, severity=Severity.MINOR, category=Category.DOC_DRIFT,
        summary=f"'{file}' claims {documented} test(s)",
        attributes={"documented_count": documented, "static_lower_bound": static,
                    "claim_context": context},
    )


class _Report:
    def __init__(self, ran=True, collected=429, passed=387, errored=0,
                 blocked=0):
        self.ran, self.collected, self.passed = ran, collected, passed
        # What produced no result either way. Defaulting to zero keeps every
        # existing test describing the same run it always described.
        self.errored, self.blocked = errored, blocked


# --- registry / plumbing ---------------------------------------------------

def test_every_connector_is_registered_once():
    names = registered_connectors()
    assert set(names) == {
        "secret_in_duplicated_file",
        "secret_in_multiple_repositories",
        "conflict_marker_breaks_tests",
        "doc_count_contradicted_by_run",
    }


def test_no_inputs_produces_no_correlations():
    assert run_connectors([]) == []
    assert render_report([]) == "ghost_buster: correlation found nothing to connect"


def test_correlations_are_never_fed_back_into_connectors():
    # A correlation over correlations would compound both inputs' assumptions.
    first = run_connectors([_secret(), _duplicate()])
    assert len(first) == 1
    again = run_connectors(list(first) + [_secret(), _duplicate()])
    assert len(again) == 1  # the correlation in the input produced nothing further


def test_eligibility_excludes_correlations_and_unconfirmed_findings():
    # The rule stated in the module docstring, tested where it lives rather
    # than only through whichever connectors happen to exist today.
    from ghost_buster.correlate import eligible_findings

    secret, dup = _secret(), _duplicate()
    correlation = run_connectors([secret, dup])[0]
    reasoned = _finding("semantic_thing", "a.py", status=Status.REASONED, layer=Layer.SEMANTIC)

    eligible = eligible_findings([secret, dup, correlation, reasoned])

    assert secret in eligible and dup in eligible
    assert correlation not in eligible   # produced by a connector
    assert reasoned not in eligible      # not CONFIRMED


def test_reasoned_findings_are_not_eligible():
    # A semantic claim is unverified; joining it with a deterministic fact
    # would produce something that is neither.
    reasoned = _finding(
        "committed_secret", "certs/key.pem", severity=Severity.CRITICAL,
        category=Category.COMMITTED_SECRET, status=Status.REASONED, layer=Layer.SEMANTIC,
        attributes={"fingerprint": "f", "rule": "private-key"},
    )
    assert run_connectors([reasoned, _duplicate()]) == []


def test_correlations_do_not_remove_or_mutate_their_inputs():
    secret, dup = _secret(), _duplicate()
    before = (secret.as_dict(), dup.as_dict())
    out = run_connectors([secret, dup])
    assert len(out) == 1
    assert (secret.as_dict(), dup.as_dict()) == before


# --- secret_in_duplicated_file ---------------------------------------------

def test_secret_in_duplicated_file_fires_and_names_every_copy():
    out = run_connectors([_secret(), _duplicate(others=("vendor/certs/key.pem",
                                                        "backup/certs/key.pem"))])
    assert len(out) == 1
    f = out[0]
    assert f.detector == "secret_in_duplicated_file"
    assert f.severity == Severity.CRITICAL
    assert f.status == Status.CONFIRMED
    assert f.category == Category.COMMITTED_SECRET
    assert "2 byte-identical copies" in f.summary
    assert "vendor/certs/key.pem" in f.summary
    assert f.attributes["copies"] == "3"


def test_join_works_against_a_real_duplicate_file_finding(tmp_path):
    # End to end against the real detector rather than a constructed
    # finding: duplicate_file is handed absolute paths from a real scan,
    # and the connector still has to recognise the leaked file among them.
    from ghost_buster.mechanical import detect_duplicate_files

    (tmp_path / ".git").mkdir()
    (tmp_path / "certs").mkdir()
    (tmp_path / "vendor" / "certs").mkdir(parents=True)
    body = "-----BEGIN PRIVATE KEY-----\nnot a real key\n"
    (tmp_path / "certs" / "key.pem").write_text(body)
    (tmp_path / "vendor" / "certs" / "key.pem").write_text(body)

    dups = detect_duplicate_files([tmp_path / "certs" / "key.pem",
                                   tmp_path / "vendor" / "certs" / "key.pem"])
    assert len(dups) == 1
    # Every path the finding carries is project-relative, not absolute.
    assert dups[0].evidence.file == "certs/key.pem"
    assert dups[0].evidence.related_files == ["vendor/certs/key.pem"]

    out = run_connectors([_secret(file="certs/key.pem"), dups[0]])
    assert len(out) == 1
    assert out[0].attributes["copies"] == "2"
    assert "vendor/certs/key.pem" in out[0].summary


def test_duplicate_file_finding_is_checkout_independent(tmp_path):
    # The same two files scanned from two different checkout locations must
    # produce the same finding id, or a committed baseline goes inert -- the
    # exact defect _portable_path exists to prevent, which duplicate_file
    # was reintroducing by naming absolute paths in its summary.
    from ghost_buster.mechanical import detect_duplicate_files

    ids = []
    for name in ("checkout_a", "checkout_b"):
        root = tmp_path / name
        (root / "pkg").mkdir(parents=True)
        (root / ".git").mkdir()
        (root / "pkg" / "a.py").write_text("VALUE = 1\n")
        (root / "pkg" / "b.py").write_text("VALUE = 1\n")
        found = detect_duplicate_files([root / "pkg" / "a.py", root / "pkg" / "b.py"])
        assert len(found) == 1
        ids.append(found[0].id)
    assert ids[0] == ids[1]


def test_secret_in_an_undeduplicated_file_produces_nothing():
    out = run_connectors([_secret(file="app/settings.py"), _duplicate(file="util/io.py",
                                                                     others=("copy/io.py",))])
    assert out == []


def test_duplicate_file_without_a_secret_produces_nothing():
    assert run_connectors([_duplicate()]) == []


def test_same_basename_in_a_different_directory_is_not_a_match():
    # certs/key.pem must not join against secrets/key.pem.
    out = run_connectors([_secret(file="certs/key.pem"),
                          _duplicate(file="secrets/key.pem", others=("vendor/key.pem",))])
    assert out == []


# --- secret_in_multiple_repositories ---------------------------------------

def test_same_fingerprint_in_a_prior_run_is_one_leak_in_two_repositories():
    prior = PriorRun("observe", [_secret(file="sentinel_os/certs/key.pem")])
    out = run_connectors([_secret()], prior_runs=[prior])
    assert len(out) == 1
    f = out[0]
    assert f.detector == "secret_in_multiple_repositories"
    assert f.severity == Severity.CRITICAL
    assert "observe" in f.summary
    assert f.attributes["repositories"] == "2"


def test_a_different_fingerprint_in_a_prior_run_is_not_the_same_leak():
    prior = PriorRun("observe", [_secret(fingerprint="zzz:other.pem:private-key:9")])
    assert run_connectors([_secret()], prior_runs=[prior]) == []


def test_cross_repository_connector_is_silent_without_a_prior_run():
    assert run_connectors([_secret()]) == []


def test_a_secret_with_no_fingerprint_attribute_is_skipped_not_guessed():
    # Two findings that both lack a fingerprint must not be "matched" to
    # each other on their shared absence of one -- an empty join key is not
    # evidence that these are the same leak.
    bare = _finding("committed_secret", "certs/key.pem", severity=Severity.CRITICAL,
                    category=Category.COMMITTED_SECRET)
    also_bare = _finding("committed_secret", "vendor/certs/key.pem",
                         severity=Severity.CRITICAL, category=Category.COMMITTED_SECRET)
    prior = PriorRun("observe", [also_bare])
    assert run_connectors([bare], prior_runs=[prior]) == []
    # ...and it is only the missing key that stops it: a real one matches.
    assert len(run_connectors([_secret()], prior_runs=[PriorRun("observe", [_secret()])])) == 1


def test_one_repository_is_counted_once_even_with_repeat_matches():
    prior = PriorRun("observe", [_secret(), _secret()])
    out = run_connectors([_secret()], prior_runs=[prior])
    assert len(out) == 1
    assert out[0].attributes["repositories"] == "2"


# --- conflict_marker_breaks_tests ------------------------------------------

def test_conflict_marker_explains_tests_in_the_same_file():
    out = run_connectors([
        _marker(file="tests/test_models.py", line=12),
        _test_status("tests/test_models.py", nodeid="tests/test_models.py"),
        _test_status("tests/test_models.py", nodeid="tests/test_models.py::test_b"),
    ])
    assert len(out) == 1
    f = out[0]
    assert f.detector == "conflict_marker_breaks_tests"
    assert f.severity == Severity.CRITICAL
    assert "2 tests cannot run" in f.summary
    assert "tests/test_models.py:12" in f.summary
    assert f.attributes["blocked_tests"] == "2"
    assert f.attributes["collection_errors"] == "2"


def test_conflict_marker_in_an_unrelated_file_does_not_claim_the_tests():
    # Attribution is same-file only; claiming a marker in app/models.py
    # broke tests/test_models.py needs an import graph this does not have.
    out = run_connectors([_marker(file="app/models.py"),
                          _test_status("tests/test_models.py")])
    assert out == []


def test_a_passing_suite_alongside_a_marker_produces_nothing():
    assert run_connectors([_marker(file="tests/test_models.py")]) == []


def test_a_skipped_test_is_not_attributed_to_a_marker():
    # A skip is a decision, not a syntax error; only failures and blocked
    # tests are attributable to broken syntax in their own file.
    out = run_connectors([
        _marker(file="tests/test_models.py"),
        _test_status("tests/test_models.py", kind="skipped for a dependency", phase="setup"),
    ])
    assert out == []


# --- doc_count_contradicted_by_run -----------------------------------------

def test_doc_count_is_checked_against_the_real_run():
    out = run_connectors([_drift()], test_report=_Report(collected=429, passed=387))
    assert len(out) == 1
    f = out[0]
    assert f.detector == "doc_count_contradicted_by_run"
    assert "claims 353" in f.summary
    assert "collects 429" in f.summary
    assert "387 pass" in f.summary
    assert "42 do not" in f.summary
    assert f.severity == Severity.MAJOR   # some collected tests did not pass
    assert f.attributes["collected"] == "429"


def test_a_fully_green_suite_keeps_the_doc_finding_minor():
    out = run_connectors([_drift()], test_report=_Report(collected=429, passed=429))
    assert len(out) == 1
    assert out[0].severity == Severity.MINOR
    assert "do not" not in out[0].summary


# --- what never ran is in neither number (v1.7.3) --------------------------
#
# A module that cannot be imported contributes nothing to `collected` and
# nothing to `passed`, so `collected - passed` is zero and the suite reads
# as green. It is not green: a whole file of it did not execute, and nobody
# knows what is in there.
#
# The tool already reported the blocked module, in the same run, naming the
# missing import. That knowledge never reached the finding's attributes, so
# the remedy wrote "N tests, all passing" into a README over a suite with a
# file that could not be collected.

def test_a_suite_with_a_file_that_never_ran_is_not_green():
    out = run_connectors([_drift()],
                         test_report=_Report(collected=30, passed=30, errored=1,
                                             blocked=1))
    assert len(out) == 1
    finding = out[0]
    assert finding.severity == Severity.MAJOR, (
        "collected == passed, and the suite still did not run")
    assert finding.attributes["unexamined"] == "1"


def test_the_summary_says_a_file_did_not_run_at_all():
    out = run_connectors([_drift()],
                         test_report=_Report(collected=30, passed=30, blocked=1))
    assert "did not run at all" in out[0].summary


def test_the_detail_explains_why_subtracting_says_green():
    """A reader who sees MAJOR on a suite where collected equals passed has
    to be able to find out why without reading this source."""
    out = run_connectors([_drift()],
                         test_report=_Report(collected=30, passed=30, blocked=1))
    assert "absent from the collected count" in out[0].detail


def test_errored_and_blocked_are_not_added_together():
    """One file that fails to import is usually counted both ways: once as
    a collection error and once as blocked by a dependency. Summing them
    would report two unexamined files where there is one, and a number a
    remedy prints to a human has to be the number of files."""
    out = run_connectors([_drift()],
                         test_report=_Report(collected=30, passed=30, errored=1,
                                             blocked=1))
    assert out[0].attributes["unexamined"] == "1"


def test_a_suite_with_nothing_unexamined_is_unchanged():
    """The control. The fix must be invisible to a suite that fully ran."""
    out = run_connectors([_drift()], test_report=_Report(collected=429, passed=429))
    assert out[0].severity == Severity.MINOR
    assert out[0].attributes["unexamined"] == "0"
    assert "did not run at all" not in out[0].summary


def test_a_report_that_never_heard_of_unexamined_still_works():
    """An older report object has no `errored` or `blocked`. It must read as
    zero rather than raising, because a connector that crashes on an
    unfamiliar report takes the whole correlation down with it."""
    class Ancient:
        ran, collected, passed = True, 429, 429
    out = run_connectors([_drift()], test_report=Ancient())
    assert len(out) == 1
    assert out[0].attributes["unexamined"] == "0"


def test_doc_count_connector_is_silent_without_a_tests_run():
    assert run_connectors([_drift()]) == []
    assert run_connectors([_drift()], test_report=_Report(ran=False)) == []


@pytest.mark.parametrize("context,shape", [
    ("`Tests/test_x.py` gained ", "a delta"),
    ("ghost_tools went from 255 to ", "a recorded transition"),
    ('HERALD\'s README claimed "', "a quoted claim"),
    ("That project's README claimed ", "an attributed claim"),
])
def test_doc_count_connector_refuses_to_rewrite_a_claim_that_is_not_a_total(context, shape):
    """The connector tells a reader to write a specific number into a
    specific file. It re-checks the claim's shape itself rather than
    trusting the detector filtered it, because that instruction is wrong
    for a delta or a quotation -- it would replace something true with
    something false. All four shapes were real findings on ghost_tools.
    """
    out = run_connectors([_drift(context=context)], test_report=_Report())
    assert out == [], f"recommended overwriting {shape}"


def test_doc_count_connector_still_fires_on_a_real_claim_with_context():
    out = run_connectors([_drift(context="the suite has ")], test_report=_Report())
    assert len(out) == 1
    assert "collects 429" in out[0].summary


def test_doc_count_connector_is_silent_without_a_drift_finding():
    assert run_connectors([], test_report=_Report()) == []


# --- correlation findings behave like every other finding ------------------

def test_correlation_findings_are_stable_and_round_trip():
    first = run_connectors([_secret(), _duplicate()])[0]
    second = run_connectors([_secret(), _duplicate()])[0]
    assert first.id == second.id
    assert Finding.from_dict(first.as_dict()).attributes == first.attributes


def test_correlation_detail_names_the_findings_it_was_built_from():
    secret, dup = _secret(), _duplicate()
    f = run_connectors([secret, dup])[0]
    assert secret.id in f.detail
    assert dup.id in f.detail


def test_render_report_counts_by_connector():
    out = run_connectors([_secret(), _duplicate()])
    assert render_report(out) == (
        "ghost_buster: correlation connected 1 finding(s): 1 secret_in_duplicated_file"
    )


# --- prior-run loading ------------------------------------------------------

def test_load_prior_run_reads_a_json_dump_and_labels_it(tmp_path):
    from ghost_buster.schema import FindingSet
    path = tmp_path / "observe.json"
    path.write_text(FindingSet([_secret()]).to_json())
    prior = load_prior_run(path)
    assert prior.label == "observe"
    assert len(prior.findings) == 1
    assert prior.findings[0].attributes["fingerprint"]


def test_load_prior_run_accepts_an_explicit_label(tmp_path):
    from ghost_buster.schema import FindingSet
    path = tmp_path / "sentinel_os_findings.json"
    path.write_text(FindingSet([_secret()]).to_json())

    assert load_prior_run(path).label == "sentinel_os_findings"
    assert load_prior_run(f"sentinel_os={path}").label == "sentinel_os"


def test_correlation_provenance_does_not_repeat_an_id(tmp_path):
    # The same vendored leak in two repositories produces two findings with
    # the same id by construction; listing it twice reads as a bug.
    prior = PriorRun("observe", [_secret()])
    f = run_connectors([_secret()], prior_runs=[prior])[0]
    ids = f.detail.split("Built from findings: ")[1].rstrip(".").split(", ")
    assert len(ids) == len(set(ids))


def test_load_prior_run_rejects_a_missing_file(tmp_path):
    with pytest.raises(ValueError) as e:
        load_prior_run(tmp_path / "nope.json")
    assert "nope.json" in str(e.value)


def test_load_prior_run_rejects_a_file_that_is_not_a_finding_set(tmp_path):
    path = tmp_path / "junk.json"
    path.write_text(json.dumps({"not": "a finding set"}))
    with pytest.raises(ValueError) as e:
        load_prior_run(path)
    assert "not a ghost_buster" in str(e.value)


# --- CLI wiring -------------------------------------------------------------

def test_cli_reports_correlation_and_a_bad_correlate_with_is_a_usage_error(tmp_path, capsys):
    from ghost_buster.cli import main
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "m.py").write_text("x = 1\n")

    rc = main([str(proj), "--json", "--baseline", str(tmp_path / "b.json")])
    out, err = capsys.readouterr()
    assert rc == 0
    assert "correlation found nothing to connect" in err

    rc = main([str(proj), "--correlate-with", str(tmp_path / "missing.json"),
               "--baseline", str(tmp_path / "b.json")])
    out, err = capsys.readouterr()
    assert rc == 2
    assert "--correlate-with" in err


def test_cli_no_correlate_skips_the_pass(tmp_path, capsys):
    from ghost_buster.cli import main
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "m.py").write_text("x = 1\n")
    rc = main([str(proj), "--no-correlate", "--baseline", str(tmp_path / "b.json")])
    out, err = capsys.readouterr()
    assert rc == 0
    # v0.11.0: a skipped pass is no longer silent. What must be absent is the
    # WORK (no connector ran, no correlation finding was produced), not the
    # word -- the receipt naming the opt-out is the point of the change.
    assert "correlation SKIPPED at your request (--no-correlate)" in err
    assert "found nothing to connect" not in err
    assert "connected" not in err
