# Provenance

Lineage of code in this repo that did not originate here. Same convention
as the `PROVENANCE.md` files in the other repos of this stack.

## `ghost_writer/polish/` (2026-09-09)

- **Source:** `wking53214/content-polish-pipeline`, commit
  `44bf225abd819008f898510c37ea5b432cb44532` (`main`, v1.1.0), MIT. That
  repo's own `PROVENANCE.md` traces the code further back, to a Gemini
  transcript archived in the `CODE` repo and a Claude-sandbox zip from
  2026-08-26.
- **Why:** the repo was retired as a standalone package and absorbed here
  as the quality gate around `ghost_writer/correct.py`'s LLM call, the one
  place in `ghost_writer` that generates new text rather than templating
  a human's own decision. It is not a new command. `report.py` is not
  gated.
- **Vendored, not depended on:** ghost_tools declares no dependencies and
  its README says so; a pinned git dependency would have made a fresh
  checkout need network and git to install, and would have blocked any
  PyPI release (direct-URL dependencies are rejected there). Three small
  stdlib-only files were copied instead.

| Source file | Copied to | Changes in the copy |
|---|---|---|
| `LICENSE` | `ghost_writer/polish/LICENSE` | none |
| `content_polish_pipeline/filters.py` | `ghost_writer/polish/filters.py` | attribution header added |
| `content_polish_pipeline/pipeline.py` | `ghost_writer/polish/pipeline.py` | attribution header added; unused `import asyncio` removed (this repo's CI runs `ruff check` as a hard gate and F401 fails it); the `try/except ImportError` standalone-import fallback replaced by the plain relative import; logger renamed `content_polish_pipeline` to `ghost_writer.polish` |
| `content_polish_pipeline/__init__.py` | `ghost_writer/polish/__init__.py` | rewritten: docstring, same four exports, no `__version__` (the package is versioned by ghost_tools now) |
| `tests/test_pipeline.py` | `Tests/test_polish.py` | imports and logger name repointed; docstring notes the port; 23 tests unchanged |

Not copied: `README.md`, `pyproject.toml`, `.gitignore`, that repo's
`PROVENANCE.md`.

- **How it is used:** `correct.py` builds a `ContentPolishPipeline` per
  proposal around an async gateway that calls the model through the
  existing `_run_json_check` fencing, parses the JSON, and hands the
  pipeline the replacement and reasoning as one string. The pipeline's
  `empirical_filter` attribute is replaced with a wrapper that runs the
  same filter on the reasoning only. The pipeline's HMAC signature and
  latency fields have no consumer here; a per-process random signing key
  is passed only so the vendored code does not log its no-key warning on
  every proposal.
- **Changed 2026-09-24:** the upstream `DEFAULT_SIGNING_KEY` constant
  (a key published in source) was removed from the vendored copy. With no
  `signing_key`, the pipeline now uses a random per-instance key and
  warns, so a signature can no longer be forged from the source.
- **Verification at the time of vendoring:** the source suite (23) passed
  at commit `44bf225`; the ported suite passes here; ghost_tools went from
  167 to 220 tests (23 ported, 15 gate tests, 15 mutant checks).

## `ghost_writer/polish/oscillation.py` (2026-09-09)

- **Source:** `wking53214/content-polish-pipeline`, branch
  `claude/ats-oscillation-detection-qs1k74`, commit
  `b0740bf3d827a30c339c5f54e1a14432548d2689` (2026-08-30, "Integrate
  OscillationDetector: bounded-history repetition detection"). This branch
  was never merged and had no pull request against that repo; it sat
  alongside `main` when the repo was retired and archived, and was found
  during a branch audit after the fact.
- **Why:** it refactors the same duplicate-generation check the vendored
  pipeline already carried (an unbounded `set` of response hashes) into a
  reusable, independently-testable `OscillationDetector` class with a
  bounded history. The pipeline's own retry loop never needed the bound
  (`ghost_writer.correct` caps attempts at 3), but the class is a real
  improvement over an inline hash set for any other caller, and the source
  package (`max_attempts` default of 5, and reusable outside this one
  gate) is exactly that kind of caller. `ghost_writer/polish/pipeline.py`
  now uses it in place of the inline `historical_hashes` set it had.
- **Deliberate deviation from the branch, not carried forward:** the
  source's `observe()` normalized its input itself (`.strip().lower()`)
  before comparing. The vendored pipeline already normalizes a response
  (whitespace-collapse only, case-preserving) before any duplicate check
  ever sees it; stacking a second, case-insensitive normalization on top
  would make two proposals that differ only in capitalization count as
  the same output, a real behavior change nothing asked for and nothing
  in the source branch's own tests argued for. The vendored detector
  compares exactly what it is given; normalization stays the caller's
  decision, as it already was.

| Source file | Copied to | Changes in the copy |
|---|---|---|
| `content_polish_pipeline/oscillation.py` | `ghost_writer/polish/oscillation.py` | attribution header added; internal `.strip().lower()` normalization removed (see above); `deque[str]` type hint added; docstring rewritten to explain the deviation and reference this entry |

`ghost_writer/polish/pipeline.py` and `__init__.py` were edited, not
replaced: the inline `historical_hashes: set[str]` block and its
`hashlib.sha256` hashing are gone, replaced by an
`OscillationDetector(max_history=32)` instance, reset once per
`execute()` call; every result path gained an `oscillation_detected`
field; the "Duplicate generation detected" violation text is unchanged.

`content_polish_pipeline/__init__.py`'s export of `OscillationDetector`
and the source branch's README changes were not carried over -- the class
is exported from `ghost_writer/polish/__init__.py` instead, and this repo's
own README documents it in place of that branch's README.

Verification at the time of vendoring: the ported pipeline suite
(`Tests/test_polish.py`) passed unchanged before this change (proving the
refactor is behavior-preserving where it should be), then gained new
tests for `OscillationDetector` itself and for the new
`oscillation_detected` field; `Tests/test_polish_mutants.py` gained eight
mutants for the new code and the rewired pipeline wiring, all killed.
ghost_tools went from 255 to 272 tests.

The branch itself was left in place on the (now archived) source repo as
part of its frozen history; it was not deleted.
