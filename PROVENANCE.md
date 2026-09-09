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
  is passed only so the vendored code does not log its default-key
  warning on every proposal.
- **Verification at the time of vendoring:** the source suite (23) passed
  at commit `44bf225`; the ported suite passes here; ghost_tools went from
  167 to 220 tests (23 ported, 15 gate tests, 15 mutant checks).
