# ghost_tools -- v0.1

Two tools, one shared finding format, built to work in tandem: `ghost_buster`
hunts down structural problems in code; `ghost_writer` turns the ones a human
decides are worth documenting (not fixing) into accurate docs.

Built from a researched taxonomy of what actually goes wrong in large,
iteratively-built (especially AI-assisted) codebases -- duplication,
parallel unreconciled implementations, dead code, and documentation that
described a system that no longer exists by the time anyone reads it again.

## The pipeline, and the one rule that makes it safe

```
ghost_buster (mechanical + semantic detectors)
        |
        v
   FindingSet (every finding: REASONED or CONFIRMED, never assumed)
        |
        v
   HUMAN TRIAGE  <-- the gate. Nothing skips this.
        |
   +----+----+----------+
   |         |          |
  fix      suppress   document
   |         |          |
(issue    (baseline)    v
 tracker)            ghost_writer
                      (renders ONLY disposition="document" findings)
```

`ghost_writer` never reads `ghost_buster`'s raw output. It only reads
findings a human has explicitly marked `disposition="document"`. A real bug
goes to `fix`, not into a README pretending it's a design decision. This
gate is enforced in code (`ghost_writer/report.py`'s
`dispositioned_for_documentation`), not just convention.

## ghost_buster

Two independent layers, both producing the same `Finding` shape
(`ghost_buster/schema.py`):

- **Mechanical** (`ghost_buster/mechanical.py`) -- deterministic, AST-based,
  stdlib only. Every finding is `Status.CONFIRMED`; there's nothing to
  doubt about a deterministic check. Three detectors in v0.1:
  `dead_code`, `long_function`, `near_duplicate_function`.

  `dead_code` was calibrated against a real, previously-unseen repo
  (ANVIL) and found two real false-positive classes on the first run:
  `Protocol`/`ABC` interface classes (whose whole purpose is often zero
  in-file references -- external implementers are the intended
  consumers) and string-keyed dynamic dispatch (`registry["Name"]`,
  including a module loaded via `exec()` into a dict and read back by
  string key). Both are now excluded/traced (v0.1.1). Still disclosed and
  not fixed: getattr-by-string and decorator-based registration --
  confirmed live, this tool's own `@register` pattern in `mechanical.py`
  self-flags for exactly that reason when ghost_buster scans itself.
- **Semantic** (`ghost_buster/semantic.py`) -- backed by a real Claude API
  call (`AnthropicModelClient`, model `claude-sonnet-5`), for the class of
  ghost no static pass can see: two modules solving the same problem two
  different ways, or a doc claim that no longer matches what the code
  does. Every finding here is `Status.REASONED`, never `CONFIRMED` --
  enforced by `schema.py`, not just a naming convention. It takes a human
  (or a second check) to promote one to `CONFIRMED_BY_REVIEW`.

  Untrusted code/docs are always sent role-separated (system instruction
  vs. user-turn data) and XML-fenced, the same two-layer defense pattern
  used in `sentinel_os`'s own governor integration -- written fresh here,
  not copied, but the same shape for the same reason. Every failure mode
  (no API key, network error, malformed JSON, a response missing the
  required shape) fails closed to an empty finding list plus a
  `SemanticRunReport` explaining why -- never a crash, never a fabricated
  finding.

### Usage

```bash
# scan a directory, show new findings since the last baseline
python -m ghost_buster.cli /path/to/repo

# accept everything currently found into the baseline (stop re-flagging it)
python -m ghost_buster.cli /path/to/repo --accept

# emit machine-readable JSON (feeds the triage step, then ghost_writer)
python -m ghost_buster.cli /path/to/repo --json > findings.json
```

Exit code is `1` if any new CRITICAL/MAJOR finding exists, `0` otherwise --
usable as a CI gate on the mechanical layer (the semantic layer needs an
API key and isn't wired into the CLI by default; see below).

The semantic layer is a library, used directly:

```python
from ghost_buster.semantic import AnthropicModelClient, detect_parallel_implementations

client = AnthropicModelClient(api_key="...")
findings, report = detect_parallel_implementations(client, {
    "harness_a.py": "...",  # a summary/docstring, not necessarily the full file
    "harness_b.py": "...",
})
```

## ghost_writer

- `ghost_writer/report.py` -- pure templating (no API call). Renders
  `disposition="document"` findings, grouped by category, into a markdown
  section -- including *why* it was documented rather than fixed
  (`disposition_note`), which is exactly the context a stale doc usually
  lacks.
- `ghost_writer/correct.py` -- the judgment-requiring half. Given one
  `doc_drift` finding and a current, accurate code summary, proposes a
  **minimal, targeted replacement** for the one stale claim -- deliberately
  not a full doc regeneration, which risks losing hard-won specificity a
  human wrote for a real reason. Reuses `ghost_buster.semantic`'s client
  protocol and injection-fencing helpers directly rather than
  reimplementing them (exactly the "two implementations of the same thing"
  problem this whole project exists to catch, not repeated here). Returns
  a `CorrectionProposal` -- a suggestion with reasoning and a confidence
  score. **Nothing in this module writes to a file.** Applying a proposal
  is a human decision, always, outside this module.

### Usage

```bash
python -m ghost_writer.cli findings.json --title "Known Structural Ghosts"
python -m ghost_writer.cli findings.json --out ARCHITECTURE_GHOSTS.md
```

## Non-goals, stated explicitly (v0.1 and likely beyond)

- **Neither tool ever fixes anything automatically.** `ghost_buster` finds
  and reports; `ghost_writer` documents or proposes a correction. Applying
  either is always a separate, human-initiated act.
- The semantic layer never runs by default (costs real money per call);
  it's opt-in, by design, every time.
- `ghost_writer` never touches a file except via the explicit `--out` flag
  writing a *new* report file -- it does not open and rewrite an existing
  README in place.

## Requirements

Stdlib only for the mechanical layer and the whole `ghost_writer` package.
`anthropic` (already a dependency in this environment) only if you
construct an `AnthropicModelClient` -- everything else is fully testable
via `StubModelClient` with zero network access, which is how the entire
test suite runs.

## Tests

```bash
python -m pytest Tests/ -v
```

31 tests, 0 network calls, 0 API key required -- the semantic-layer tests
verify the real parsing/fail-closed/injection-fencing logic via
`StubModelClient`, the same technique `sentinel_os`'s own `interpretation/`
package uses for its model-client tests.
