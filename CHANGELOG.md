# Changelog

## 0.6.1 (2026-09-09)

### Tests
- `Tests/test_polish_mutants.py`: 25 hand-made mutants of
  `ghost_writer/polish` (each filter's pattern emptied, `passes()` forced
  true, `violations()` unsorted, the empirical contract inverted, the retry
  loop cut to one attempt, duplicate detection disabled, the gateway
  exception uncaught, the `max_attempts` check removed, the result dict's
  status, attempt count, content and violations falsified, the signature
  hash downgraded), each required to fail a test in `Tests/test_polish.py`.
  `ghost-buster --mutate --mutate-only test_polish.py` reports zero
  candidates in that file, as it does for `test_ghost_writer.py`: no test in
  either has a shape it mutates, so these suites are the complement.
- The scratch-copy harness both mutant suites use is one module,
  `Tests/mutant_harness.py`; `test_gate_mutants.py` no longer carries its
  own copy.
- Three mutants survived the ported `test_polish.py` as received: the
  speculation filter's `is_clean` alias had no alias test (the other two
  filters did), and no pipeline fixture tripped the pronoun check or the
  speculation check alone, so forcing either to pass changed nothing.
  Three tests added, one per gap; the three mutants are in the suite.
- Three mutants `test_polish.py` still does not kill are recorded in the
  new file's docstring and left out of it rather than papered over: the
  signature's dependence on the key, the recalibration feedback text
  (covered by `test_ghost_writer.py`), and whitespace normalization.

## 0.6.0 (2026-09-09)

### ghost_writer
- **Quality gate on `correct.py`.** The one LLM call in `ghost_writer` that
  generates new text is now wrapped in a retry loop that rejects a response
  containing a first-person pronoun or a hedging word in either the
  proposed replacement or the reasoning, or no evidence marker in the
  reasoning, feeds the violations back into the prompt (after the fenced
  untrusted block) and asks again, three attempts by default
  (`propose_correction(..., max_attempts=3)`). Exhausting the attempts
  yields the existing `(None, report)` outcome with the violations in
  `report.reason`; empty, malformed and client-failed responses are not
  retried and behave as before. `CorrectionProposal` is unchanged.
  `report.py` is not gated.
- **`ghost_writer/polish/`**, vendored from `content-polish-pipeline` at
  commit `44bf225` (MIT, notice kept beside the files) when that repo was
  retired into this one. The copy differs from the source in an unused
  `asyncio` import removed (ruff gate), the standalone import fallback
  removed, and the logger renamed to `ghost_writer.polish`; `PROVENANCE.md`
  records it. Its 23 tests are ported as `Tests/test_polish.py`.
- `Tests/test_gate_mutants.py`: fourteen hand-made mutants of the gate, each
  required to fail a gate test. `ghost-buster --mutate` finds no candidate
  in the gate's tests (none has a shape it mutates), so this is the proof
  that they are not vacuous.
- The `correct.py` happy-path fixture's reasoning changed from `why` to a
  sentence that names its evidence, the one existing test the gate
  rejects as written. No caller changed.
- Setuptools now lists `ghost_writer.polish`; `pip install .` was not
  installing subpackages by discovery.

## 0.5.2 (2026-09-08)

### blackhole_extrapolator
Three defects from the first full-library run (18 checkouts):
- A directory with Python anywhere beneath it is an importable namespace
  package, not only one with `.py` files directly inside. ecology's `src/`
  was reported missing 38 times.
- Requirements files are found anywhere in the tree, and `-r` / `--requirement`
  includes are followed relative to the including file, with a cycle guard.
  sentinel_os keeps its requirements one directory down; GSA-815's file is a
  single include into a submodule.
- The debris scanner no longer reads `{"ok": True,` as a type annotation:
  an annotation must follow a parameter name, and `True`, `False`, `None`
  are never dangling types.
- A declared distribution provides the import name it plausibly maps to:
  its first name token (`psycopg2-binary` gives `psycopg2`,
  `opentelemetry-api` gives `opentelemetry`) plus a short alias table
  (`PyYAML` gives `yaml`). sentinel_os declared every dependency it uses and
  three still read as voids.
- A requirements line starting with `http` is skipped only when it is a
  URL. `httpx<0.28` was being skipped as one.

## 0.5.1 (2026-09-08)

### blackhole_extrapolator
- **Rename candidates.** A name nothing defines is compared, by shape and
  never by name, against every signature the tree still has: parsing files
  and the headers read back from flattened ones. Dimensions: a keyword the
  caller passes is a parameter of the candidate; the caller unpacks N values
  and the candidate returns an N-tuple; an unpacked value is passed on to
  another known signature whose parameter carries the same annotation as the
  tuple element; a method used on the result is one the candidate class
  defines; the two names share a word. Arity compatibility is a gate. Two
  matching dimensions, at least one of them not the name, make a
  `rename_candidate` evidence item in the undefined name's own void, and the
  void lists the hypothesis as undeterminable. Nothing is merged. Found on
  TOUCHSTONE: `initialize_hybrid_cluster` is `initialize_network_cluster` on
  five dimensions, and `UnifiedGovernanceKernel` is `GovernanceKernel` on its
  four keyword parameters, in a flattened file the callers never name.

## 0.5.0 (2026-09-08)

The release that makes the toolkit shippable and closes the pipeline.

### ghost_buster
- **Mutation mode** (`--mutate`). Finds tests shaped like they check nothing
  (weak assertions only, a computed result never read, assertions behind a
  guard, a hand-written list restating a set the source defines), resolves the
  project code each one calls, breaks that code in a scratch copy one operator
  at a time (`drop_body`, `return_none`, `flip_compare`, `bump_constants`;
  guard instrumentation; enum extension), runs only that test, and reports a
  finding **only when the test survived**, carrying the mutation as its proof.
  The working tree is never modified; siblings are symlinked beside the copy so
  `../sibling` imports resolve. Candidates that do not pass unmutated are
  reported as unjudged, never as findings. New category `vacuous_check`.
  Validated on real repositories: found the test the 2026-09-08 audit had
  confirmed by hand, and a test that survives eleven inverted comparisons.
- Guard semantics are "the guarded assertions never ran", measured by
  instrumentation, not "removing the guard fails the test" (which flags every
  data-dependent guard). An if/else that asserts on both sides is a branch, not
  a guard. A guard holding every assertion of its test is CRITICAL; one beside
  unguarded assertions is MAJOR.

### ghost_writer
- **`ghost-triage`**, the human step the README always drew and never had a
  tool for: records `fix` / `suppress` / `document` decisions with a note
  against finding ids in the FindingSet JSON, refuses unknown or ambiguous ids,
  lists what is still undecided.
- **Triage report mode** (`--mode triage`): every finding, most severe first,
  grouped by file, with a severity and detector summary, `vacuous_check` proofs
  rendered as such, and already-decided findings listed with their decision.
  It states on its face that nothing in it has been reviewed. The document
  mode and its gate are unchanged.

### blackhole_extrapolator
- **Ecosystem awareness.** An import that a sibling checkout defines, that the
  project declares as a dependency (requirements files, pyproject dependencies
  and optional extras), or that a declared git submodule would provide is
  reported as **wiring** with the provider named, beside the voids, never
  grouped into one and never silenced. An uninitialised submodule is attached
  to unresolved imports as a note, not a claim. `--sibling DIR` (repeatable),
  `--ecosystem PARENT` (every checkout under a parent, each against the rest),
  `--show-wiring`. Default JSON shape unchanged; with `--show-wiring` it is
  `{"voids": [...], "wiring": [...]}`. Measured on the governance stack: the
  spine went from five voids to the one real nominal dependency.
- **Debris archaeology.** A flattened file (no newlines, does not parse)
  keeps every `class` and `def` header in token order. New evidence kind
  `debris_structure` reads the interface back, with parameter lists and return
  annotations and methods attributed to the class that precedes them, and the
  void lists it under `must define`. Bodies, docstring examples and
  interleaved pastes are named as undeterminable on every such void. A parsing
  companion (`x_source.py` beside `x_adapter.py`) is checked for shared class
  names so an ancestor of a rewrite is not reported as a lost dependency.
  Measured on TOUCHSTONE's `quorum_state_governance_source.py`: 38 signatures
  recovered where 0.4 reported seven names and no shape.
- **Corpus run fixes** (nine checkouts, 49 voids to 36). A test that imports
  a sibling-provided module is wiring, not an orphaned test (the spine's
  `ccc`, `gems` and `governance_gateway` were being reported twice, once by
  each detector, and only one consulted the providers). A file that parses as
  a single comment is destroyed for the structure detector as it already was
  for the residue detector, and its void is classified destroyed. Callers of a
  name a destroyed file's debris defines join that file's void instead of
  forming a second, never-built one; the void says the join is by name.
  `--json` emits JSON when nothing is missing, and `--ecosystem --json` emits
  one object keyed by checkout instead of prose headers between documents.

### Packaging
- Console scripts: `ghost-buster`, `ghost-writer`, `ghost-triage`,
  `blackhole-extrapolator`. Explicit package list, classifiers, keywords, URLs.
  `pip install git+https://github.com/wking53214/ghost_tools` works from a clean
  environment with no dependencies.

## 0.4 and earlier

See the changelog section at the end of README.md.
