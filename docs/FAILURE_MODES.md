# How AI-assisted workflows fail, and which horseman catches each

A map from the failure modes of multi-model, vibe-coded work to the seven
repositories of the circuit (ASSAY, ghost_tools, SWIZZLE, Warden, Drafter,
Judge, Burnish). The list on the left is a research synthesis cross-checked
against this project's own history (2026-10-14); the right-hand columns say
what is mechanically caught today, by what, and what is not caught by
anything but a person. "Caught" means a detector, a gate or a rule exists,
has tests, and has been run on the circuit's own repositories. Nothing here
is claimed on the strength of a name.

The finding behind the whole list: most of the risk is in **trusting that
something is done or verified when it is not**, more than in bad code. That
is why the circuit's gates are built the way they are (unknown is not
approved; a check that did not run says so; nothing is accepted on its own
author's word), and why the three detectors added on 2026-10-14 all target
the "looks done, isn't" tier.

## Tier 1: looks done, isn't

| Failure | Caught by | How | Not caught |
|---|---|---|---|
| **Theater code**: functions never called, stubs left in place | ghost_tools | `dead_code` (nothing references it), `dead_end_call` (live code calls a body that does nothing), `commented_out_module` (a file whose code is all comments) | A stub that returns a plausible constant and is called: that is a correctness question, and no scanner here answers it |
| **Theater code**: features validated only against mocks | ghost_tools | `mock_only_test` (every assertion in a test is a Mock assertion) | A mock-only unit test that sits beside a real integration test is reported too; the tree cannot tell whether the integration test exists elsewhere |
| **Theater code**: docs claiming more than the code does | ghost_tools, Burnish | `unverified_status_claim` ("production ready", "battle-tested", "100% coverage", "RL Ready"), `doc_test_count_drift` (a stale test count); Burnish's critic writes the measured facts into the README and names every claim it cannot support | Whether a label is *true*. The detector surfaces it for re-verification; a person decides |
| **Tests that cannot fail** | ghost_tools, Warden, Judge | `assertless_test` (a stub body is MAJOR; a body that asserts nothing is MINOR); `--mutate` proves a test vacuous by breaking what it names; Warden refuses any edit to a test file, test config or CI, and the Judge rejects a run that touched one even by whitespace, so an agent cannot rewrite the tests to pass | An assertion that is logically always true (`assert x == x`); a hardcoded expected output that happens to match. `--mutate` finds some of these, at a cost |
| **Silent failures**: errors caught and ignored | ghost_tools, Burnish | `swallowed_exception` (bare `except` is MAJOR, a named one MINOR); Burnish `PY-EXC`, `PY-SWALLOW` | A handler that logs and continues when it should have stopped |
| **Unverified status claims**: "confirmed", "done", "complete" without checking | Judge, Warden, Burnish | The Judge's rule is "unknown is not approved": a check that did not run yields INSUFFICIENT, never ACCEPT. Warden's output lists `unmeasured` by name and only exit 0 means ACCEPT. Burnish's README section says what was measured and what was not | A claim made in a chat, outside any repository |

## Tier 2: workflow contamination

| Failure | Caught by | How | Not caught |
|---|---|---|---|
| **Context rot and bleed** across long sessions | Warden (by construction) | Every run is a fresh process with a fresh snapshot; nothing carries over but the tree and the grant | Rot inside the session that wrote the proposal |
| **Invention sprawl**: new names and fake hashes minted per session | ghost_tools | `near_duplicate_function`, `duplicate_file`, `drifted_copy` (one thing under several names), `vestigial_domain_name`, `name_disagreement` (one value passed under two names), `placeholder_name` | A hash in a document that matches no commit. Designed, not built: it would false-positive on every honest cross-repository citation |
| **Handoff loss between AIs**: flattened text, lossy summaries | ghost_tools, ASSAY | `flattened_copy` (an unparseable file that is a readable one with its whitespace destroyed; ASSAY 3.3), `merge_conflict_marker`, `unassessable_file` (a file nothing could read is a MAJOR finding, never a skip) | A summary that dropped a requirement |
| **AI grading AI** | Warden, Judge, SWIZZLE | Separate seats, one-way imports: the Drafter proposes, Ghost re-inspects, the Judge decides, and none of them may grade its own work. SWIZZLE's oracles are frozen before the target runs. Warden cannot grant itself, and a stack name cannot authorize a change to Warden's own tree | Two seats filled by the same model family share biases. Fill the Judge from a different family when it matters |

## Tier 3: agent behaviour and understanding

| Failure | Caught by | How | Not caught |
|---|---|---|---|
| **Scope creep, destructive actions** | Warden, Judge | A grant names a scope (`documentation` or `code`); a proposal outside it is declined. The protected-file list (tests, CI, config, hooks, lockfiles) cannot be edited at all. A dirty folder is refused before anything starts, every edit is listed for the Judge, and a run that does not end ACCEPT is put back byte for byte | Edits the person makes during a run |
| **Invented packages** (slopsquatting) | ghost_tools (partly) | The structural model reports an `undeclared dependency` (imported, not declared) | The reverse: a declared package that does not exist. Checking that needs the network, which the scanner never touches. Designed, not built: an offline "declared but never imported and not installed" check |
| **Comprehension debt** | Burnish | The README critic requires a one-sentence statement of what the project is, an install, a usage, limits, status and support, and fails the README below the tier asked for | Whether the person can explain the code. Nothing mechanical can |

## Tier 4: classic checks

| Failure | Caught by |
|---|---|
| Mutable default arguments | Not yet. Burnish has eight Python rules (`burnish check`); this is the obvious ninth |
| Catch-all exception handlers | ghost_tools `swallowed_exception`; Burnish `PY-EXC` |
| Injection, path traversal, destructive SQL | ghost_tools `sql_injection`, `destructive_sql` |
| Missing authorization | ghost_tools `unauthenticated_route` |
| Configuration mistakes | ghost_tools `insecure_default` (`DEBUG = True`, open CORS with credentials, `verify=False`), `no_ci_configuration`, `test_config_collects_nothing` |
| One query per item, unprofiled slowness | ghost_tools `loop_invariant_call`, `list_membership_in_loop` (the Drafter fixes the latter), `--profile` |
| Duplicated code, dead code, long functions | ghost_tools `duplicate_file`, `near_duplicate_function`, `intra_function_duplicate_block`, `dead_code`, `long_function` |

## How the answer key keeps the scanner honest

ASSAY records each named failure mode as a specimen with a correct answer,
and `swizzle assay` scores the scanner against it. Two specimens were added
with the detectors above, both constructed and both saying so: a test module
whose four green tests could never have been red (3.6), and a README calling
itself production-ready beside no code and no test (3.7). On 2026-10-14 the
scanner caught 5 of the 7 known failure modes; the two it misses (an
unreachable branch provable only numerically, and a reskinned duplicate whose
sameness is a formula, not a shape) are marked in SWIZZLE as beyond what a
syntax-tree scanner can know. Warden grades the scanner against this key
before it writes anything, and the Judge sees the score.

## What a person still has to do

- Re-verify every status label the scanner surfaces. The scanner proves the
  label is there; it does not prove it is false.
- Read the `drafter_skipped` and `unmeasured` lists in Warden's output. A
  silent check is the defect; these are where the silence is named.
- Fill the Judge from a different model family than the one that wrote the
  code, when the decision matters.
- Keep tests read-only for every agent. The circuit enforces this inside a
  run; outside it, the branch-and-review habit is the defence.
