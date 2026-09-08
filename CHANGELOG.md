# Changelog

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

### Packaging
- Console scripts: `ghost-buster`, `ghost-writer`, `ghost-triage`,
  `blackhole-extrapolator`. Explicit package list, classifiers, keywords, URLs.
  `pip install git+https://github.com/wking53214/ghost_tools` works from a clean
  environment with no dependencies.

## 0.4 and earlier

See the changelog section at the end of README.md.
