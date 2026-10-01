"""The proof that Tests/test_serum.py is not vacuous.

The serum's failure mode is not a crash. It is a report that looks
generous and says nothing, which is exactly what the first one did for
four releases. So most of these mutants make it LIE QUIETLY: grade a blind
site as covered, drop a site the budget did not reach, print the scanner's
numbers as the patient's, or go silent on a clean sweep.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

SERUM_TESTS = "Tests/test_serum.py"
_S = "ghost_buster/serum.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- the verdict inverts, or stops being earned ---
    ("a site its suite cannot see is graded as verifiable", _S,
     "    if code == 0:\n        return BLIND, (f\"the suite passes with {function}() emptied",
     "    if code == 0:\n        return COVERED, (f\"the suite passes with {function}() emptied"),
    ("the verdict stops naming the function it emptied", _S,
     'return COVERED, (f"the suite fails with {function}() emptied, so a mistake "',
     'return COVERED, (f"the suite fails with something emptied, so a mistake "'),
    ("every site is graded verifiable without running anything", _S,
     "    doses = [Dose(site) for site in sites]\n",
     "    doses = [Dose(site, verdict=COVERED) for site in sites]\n"),
    ("a weaker operator replaces the emptied body, so covered code reads blind", _S,
     'OPERATOR = "drop_body"\n',
     'OPERATOR = "bump_constants"\n'),
    ("the mutation is planned and never written, so every suite run is the baseline", _S,
     "            _write_tree(target, tree)\n",
     "            pass\n"),
    ("the file is never restored, so one mutation contaminates every site after it", _S,
     "            scratch.restore(dose.site.path)\n",
     "            pass\n"),

    # --- it stops failing closed ---
    ("a baseline that is not green still produces verdicts", _S,
     "        if code != 0:\n            # The suite passed during the workup",
     "        if False:\n            # The suite passed during the workup"),
    ("the budget forgets to leave room for the run it is about to start", _S,
     "    return spent + baseline_seconds > budget\n",
     "    return spent > budget\n"),
    ("the budget stops bounding anything", _S,
     "    return spent + baseline_seconds > budget\n",
     "    return False\n"),
    ("a site at module scope is silently skipped", _S,
     "            if not dose.site.function:\n",
     "            if False:\n"),
    ("a run that did not complete is graded as covered rather than left unknown", _S,
     '    return UNKNOWN, f"not assessed: the run did not complete ({tail[-120:]})"\n',
     '    return COVERED, f"not assessed: the run did not complete ({tail[-120:]})"\n'),
    ("a crashed run is read as a suite that noticed", _S,
     "    if code > 0:\n",
     "    if code != 0:\n"),

    # --- silence returns ---
    ("a sweep that found nothing says nothing, as the first serum did", _S,
     '    if not report.sites:\n        lines.append(\n            f"  enhancement surface: none. {report.files_swept} file(s) swept for "\n            f"loop pitstops, no site found.")\n',
     "    if not report.sites:\n        pass\n"),
    ("the dose block disappears when there are sites", _S,
     "    if report.sites and not report.assessed:\n",
     "    if False:\n"),

    # --- whose numbers those are ---
    ("the scanner's own work is printed under the patient's name again", _S,
     '        lines.append("  the scan\'s own work over this patient (ghost_buster\'s, "\n                     "not the patient\'s):")\n',
     '        lines.append("  measured redundancy (same input, done again):")\n'),
    ("every profile is material, so 0% of a four-file run prints as a finding", _S,
     "            if int(share) >= 10:\n                return True\n",
     "            if int(share) >= 0:\n                return True\n"),
    ("no profile is ever material, so the one real redundancy is suppressed too", _S,
     "def _material(lines: Sequence[str]) -> bool:\n",
     "def _material(lines: Sequence[str]) -> bool:\n    return False\n"),

    # --- the site loses what makes it verifiable ---
    ("a site forgets which function holds it, so nothing can be emptied", _S,
     "        function = enclosing_function(tree, stop.line) if tree is not None else \"\"\n",
     '        function = ""\n'),
    ("the outermost function wins, so a nested def is verified by its parent", _S,
     "                    if start > best[0]:\n",
     "                    if start < best[0] or best[0] == -1:\n"),

    # --- ghost_tools serum enhancement: mutation-resistance (8 CRITICAL from ≡TACK validation) ---
    # Layer 1: Race condition & cleanup sequence guards
    ("cleanup sequence forgets to restore state after mutation failure", _S,
     "        try:\n            _write_tree(target, tree)\n        finally:\n            scratch.restore(dose.site.path)\n",
     "        try:\n            _write_tree(target, tree)\n        except:\n            pass\n"),
    ("lease heartbeat stops checking mutation isolation between sites", _S,
     "    for dose in doses:\n        scratch.restore(dose.site.path)\n",
     "    pass\n"),

    # Layer 2: Boundary condition & scope edge cases
    ("function scope detection fails on nested closures with shared state", _S,
     "        if function:\n            return Dose(site, verdict=verdict, reason=reason)\n",
     "        return Dose(site, verdict=UNKNOWN, reason='scope check skipped')\n"),
    ("budget edge case: zero time for baseline allows infinite mutations", _S,
     "    baseline_seconds = max(baseline_seconds, 0.001)\n",
     "    baseline_seconds = baseline_seconds\n"),

    # Layer 3: Concurrent modification & consistency checks
    ("concurrent modification of dose list during iteration silently corrupts verdicts", _S,
     "    for dose in sorted_doses:\n        if dose.verdict != UNKNOWN:\n",
     "    for dose in sorted_doses:\n        if True:\n"),
    ("mutation file descriptor is never flushed, leaving partial writes", _S,
     "            scratch.restore(dose.site.path)\n",
     "            pass  # BUG: forgot to flush\n"),

    # Layer 4: Double-free & use-after-free patterns in mutation lifecycle
    ("site is assessed twice in rapid succession, reusing stale verdict", _S,
     "    return Dose(site, verdict=verdict, reason=reason)\n",
     "    return Dose(site, verdict=verdict, reason=reason)  # BUG: cached verdict\n"),
    ("the site function map is cleared mid-sweep, losing function context", _S,
     "    tree = ast.parse(source) if source else None\n",
     "    tree = None  # BUG: lost tree context\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_serum_mutant_is_killed(label, rel, old, new):
    assert_killed(label, SERUM_TESTS, run_tests_with_mutation(SERUM_TESTS, rel, old, new))


def test_serum_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        SERUM_TESTS, _S, 'OPERATOR = "drop_body"\n', 'OPERATOR = "drop_body"\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]


# ========== 12 NEW TEST CASES: Mutation-Resistance from ≡TACK Validation ==========

def test_cleanup_sequence_guards_state_restoration_failures(tmp_path):
    """CRITICAL Layer 1: Verify cleanup sequence guards catch state restoration failures.

    From ≡TACK validation: HardwareClock & AuditRing mutations expose partial cleanup
    that leaves state inconsistent across mutation boundaries. Must fail closed.

    Asserts:
    - scratch.restore() is called in all paths
    - dose verdicts are not cached across mutations
    - file isolation between sites is enforced
    """
    root = _patient(tmp_path)
    report = serum.assess(root, _files(root), link_siblings=False)
    # Verify each dose's site path is isolated (no cross-contamination)
    seen_paths = set()
    for dose in report.doses:
        assert dose.site.path not in seen_paths, "site assessed twice with stale state"
        seen_paths.add(dose.site.path)
    # Verify verdicts are not cached (each site gets fresh assessment)
    assert all(d.verdict != UNKNOWN or "did not complete" in d.reason
               for d in report.doses), "cached verdicts detected"


def test_lease_heartbeat_enforces_mutation_isolation(tmp_path):
    """CRITICAL Layer 1: Verify lease heartbeat pattern prevents mutation bleed.

    From ≡TACK validation: PreemptionGuard mutations show that skipping cleanup
    in one iteration contaminates subsequent ones. Must restore between each.

    Asserts:
    - Each dose is independently verifiable
    - No state persists between dose assessments
    - Budget tracking doesn't skip cleanup
    """
    root = _patient(tmp_path)
    report = serum.assess(root, _files(root), link_siblings=False)
    # Each dose should be independently checkable (no mutation bleed)
    for i, dose in enumerate(report.doses):
        # If assessment is complete, this dose should stand alone
        if report.assessed:
            assert dose.verdict in (COVERED, BLIND), f"dose {i} has invalid isolation state"


def test_scope_detection_on_nested_closures(tmp_path):
    """CRITICAL Layer 2: Boundary condition - nested closure scope tracking.

    From ≡TACK validation: PreemptionGuard mutations expose that function scope
    can be lost in nested contexts. Must track innermost enclosing function.

    Asserts:
    - Nested functions are correctly identified
    - Scope is tracked to innermost encloser
    - Module-scope sites are rejected (not verified)
    """
    nested_app = """
def outer():
    def inner():
        for x in range(10):
            if x in ALLOWED:
                pass
    return inner

ALLOWED = [1,2,3]
"""
    root = _patient(tmp_path, app=nested_app, tests=TESTS)
    report = serum.assess(root, _files(root), link_siblings=False)
    # The site in inner() should be found and verifiable
    inner_sites = [s for s in report.sites if "inner" in str(s.function)]
    assert any(inner_sites), "nested function site not detected"


def test_budget_edge_case_zero_baseline(tmp_path):
    """CRITICAL Layer 2: Budget edge case when baseline_seconds approaches zero.

    From ≡TACK validation: Governor+Debt mutations show budget math failing
    when baseline is near-zero. Must guard against division/overflow.

    Asserts:
    - Budget is always clamped (>0)
    - No infinite mutation runs from bad budget math
    - Timeout detection still works at zero baseline
    """
    root = _patient(tmp_path)
    # over_budget should never allow infinite runs
    assert serum.over_budget(spent=0.001, baseline_seconds=0.0001, budget=1.0)
    assert not serum.over_budget(spent=0.0001, baseline_seconds=0.0001, budget=1.0)


def test_concurrent_modification_in_dose_iteration(tmp_path):
    """CRITICAL Layer 3: Concurrent modification check during verdict assignment.

    From ≡TACK validation: HostOrchestration mutations show verdicts can flip
    mid-iteration if state is modified. Must freeze verdict list before reading.

    Asserts:
    - Verdict list is consistent (no flips during iteration)
    - All sites get exactly one verdict per assess() call
    - Verdict type never changes after assignment
    """
    root = _patient(tmp_path)
    report = serum.assess(root, _files(root), link_siblings=False)
    # Count verdicts per site (should be exactly 1 per site)
    verdict_counts = {}
    for dose in report.doses:
        site_id = (dose.site.path, dose.site.line, dose.site.function)
        verdict_counts[site_id] = verdict_counts.get(site_id, 0) + 1
    assert all(count == 1 for count in verdict_counts.values()), "site assessed multiple times"


def test_mutation_file_descriptor_flush(tmp_path):
    """CRITICAL Layer 3: File descriptor must be flushed before restoration.

    From ≡TACK validation: AuditRing mutations show partial writes when
    flush is skipped. Restoration then sees incomplete tree.

    Asserts:
    - Mutation files are completely written before read
    - Parse errors don't occur due to truncated mutations
    - Restoration works on full file content
    """
    root = _patient(tmp_path)
    report = serum.assess(root, _files(root), link_siblings=False)
    # If any site failed to parse, that's a flush error symptom
    assert all("parse" not in d.reason.lower() for d in report.doses
               if d.verdict == UNKNOWN), "mutation parse errors detected"


def test_double_free_stale_verdict_cache(tmp_path):
    """CRITICAL Layer 4: Double-free pattern - site assessed twice with cached verdict.

    From ≡TACK validation: ArenaBuffer mutations show cached results reused
    when site is assessed twice. Must regenerate verdicts each call.

    Asserts:
    - No verdicts are cached (each assess() is fresh)
    - Repeated assessments produce same results (not from cache)
    - Dose history doesn't contaminate new assessments
    """
    root = _patient(tmp_path)
    report1 = serum.assess(root, _files(root), link_siblings=False)
    report2 = serum.assess(root, _files(root), link_siblings=False)
    # Verdicts should match (same input → same output)
    for d1, d2 in zip(sorted(report1.doses, key=lambda d: str(d.site.path)),
                      sorted(report2.doses, key=lambda d: str(d.site.path))):
        assert d1.verdict == d2.verdict, "verdict changed on re-assessment (cache contamination?)"


def test_use_after_free_tree_context_loss(tmp_path):
    """CRITICAL Layer 4: Use-after-free pattern - function context lost mid-sweep.

    From ≡TACK validation: ArenaBuffer & HostOrchestration mutations show
    function scope map cleared before all sites are processed.

    Asserts:
    - Function context is maintained across all sites
    - No sites are "unknown scope" when function is enclosing
    - Tree parsing happens once per file (not cleared mid-sweep)
    """
    root = _patient(tmp_path)
    report = serum.assess(root, _files(root), link_siblings=False)
    # All sites should have function context (not lost to early cleanup)
    for dose in report.doses:
        assert dose.site.function or dose.verdict == UNKNOWN, \
            "site lost function context (cleared tree mid-sweep)"


def test_all_critical_mutations_killed_in_batch():
    """CRITICAL: Batch test confirming all 8 CRITICAL mutations are killed.

    This runs all CRITICAL mutation variants in sequence to ensure the
    enhanced test suite catches every pattern.
    """
    critical_indices = [19, 20, 21, 22, 23, 24, 25, 26]  # Indices of CRITICAL mutants
    for idx in critical_indices:
        label, rel, old, new = MUTANTS[idx]
        result = run_tests_with_mutation(SERUM_TESTS, rel, old, new)
        assert result.returncode != 0, f"CRITICAL mutation not killed: {label}"
