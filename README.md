# ghost_tools
**Repository integrity and documentation-drift detection for evolving software systems.**
`ghost_tools` provides two complementary tools:
- **`ghost_buster`** identifies structural and semantic inconsistencies in a codebase.
- **`ghost_writer`** converts human-approved findings into documentation artifacts or proposes narrowly scoped documentation corrections.
The project is designed for repositories that evolve rapidly—particularly large, long-lived, and AI-assisted codebases where obsolete implementations, duplicated logic, stale documentation, and unreconciled architectural paths can accumulate over time.
## Design Principle
`ghost_tools` separates **detection** from **judgment**.
```text
Repository
    │
    ▼
ghost_buster
    │
    ├── Mechanical findings
    │     deterministic
    │
    └── Semantic findings
          model-assisted
          explicitly reasoned
    │
    ▼
FindingSet
    │
    ▼
Human Review
    │
    ├── fix
    ├── suppress
    └── document
          │
          ▼
     ghost_writer

A finding is not automatically treated as a defect.

Mechanical detectors identify conditions that can be established deterministically. Semantic detectors identify conditions that require interpretation and therefore remain explicitly marked as REASONED until independently reviewed.

Human review is the authority boundary.

ghost_buster

ghost_buster provides two detection layers.

Mechanical Layer

The mechanical layer is deterministic and AST-based. It does not require an API or network connection.

Current detectors include:

* dead_code
* long_function
* near_duplicate_function
* intra_function_duplicate_block
* doc_test_count_drift

Mechanical findings are represented as CONFIRMED because the underlying detector establishes the condition through deterministic analysis.

The detectors are intentionally conservative. They document known scope limitations rather than presenting static analysis as universal program understanding.

Semantic Layer

The semantic layer identifies problems that cannot reliably be established through syntax alone, including:

* potentially unreconciled parallel implementations;
* documentation claims that may no longer match implementation behavior.

Semantic analysis uses an Anthropic-compatible model client and currently defaults to claude-sonnet-5.

Semantic findings are represented as REASONED, not CONFIRMED.

This distinction is intentional:

A model-generated finding is a hypothesis requiring review, not an established fact.

The semantic layer therefore cannot silently promote its own conclusions to confirmed findings.

Untrusted Repository Content

Repository source code and documentation are treated as untrusted analysis data.

The semantic layer uses:

1. role separation between instructions and repository content;
2. structural fencing of repository content;
3. strict JSON response validation;
4. fail-closed handling of client, network, and parsing failures.

A failed semantic run is reported as a failed or incomplete analysis rather than being represented as an empty successful scan.

ghost_writer

ghost_writer operates downstream of human review.

It supports two distinct workflows.

Documentation Reporting

Reviewed findings can be rendered into Markdown reports.

Only findings explicitly designated for documentation are rendered by the reporting layer.

Targeted Correction Proposals

For documentation-drift findings, ghost_writer can generate a minimal correction proposal based on a current implementation summary.

A correction proposal contains:

* the affected claim;
* the proposed replacement;
* reasoning;
* confidence.

ghost_writer does not automatically rewrite an existing README or other documentation file.

Applying a proposed correction remains a separate human-controlled action.

Finding Lifecycle

DETECTED
   │
   ▼
REASONED / CONFIRMED
   │
   ▼
HUMAN TRIAGE
   │
   ├── FIX
   ├── SUPPRESS
   └── DOCUMENT
          │
          ▼
     ghost_writer

This separation prevents a detection tool from silently converting its own observations into architectural truth.

Usage

Mechanical scan

python -m ghost_buster.cli /path/to/repository

Accept current findings into the baseline

python -m ghost_buster.cli /path/to/repository --accept

Emit machine-readable findings

python -m ghost_buster.cli /path/to/repository --json > findings.json

Generate a documentation report

python -m ghost_writer.cli findings.json \
  --title "Known Structural Ghosts"

Or write the generated report to a new file:

python -m ghost_writer.cli findings.json \
  --out ARCHITECTURE_GHOSTS.md

Semantic analysis

The semantic layer can be used directly through its model-client interface:

from ghost_buster.semantic import (
    AnthropicModelClient,
    detect_parallel_implementations,
)
client = AnthropicModelClient(api_key="...")
findings, report = detect_parallel_implementations(
    client,
    {
        "module_a.py": "Module summary...",
        "module_b.py": "Module summary...",
    },
)

Testing

The project includes deterministic tests for the mechanical and semantic-processing layers.

Semantic tests can use StubModelClient, allowing response parsing, validation, finding construction, and fail-closed behavior to be tested without network access or an API key.

Run the test suite with:

python -m pytest Tests/ -v

Requirements

The mechanical layer and ghost_writer are designed to operate without an external model service.

The semantic layer requires the Anthropic Python SDK and an API key when the real model client is used.

Scope and Non-Goals

ghost_tools is an analysis and documentation-support system.

It does not:

* automatically refactor source code;
* automatically delete code;
* automatically rewrite an existing README;
* treat model-generated findings as confirmed facts;
* claim complete detection of every architectural or documentation inconsistency.

The tool is intended to make potentially significant inconsistencies visible, reviewable, and traceable.

Project Status

Current version: v0.3

The current release includes mechanical structural detectors, documentation test-count drift detection, semantic analysis, human-dispositioned findings, and targeted documentation correction proposals.

License

See LICENSE for licensing information.

### Why I prefer this version
It makes the important architectural idea much clearer:
> **Detection ≠ judgment ≠ remediation.**
That is actually the strongest conceptual contribution of `ghost_tools`.
It also avoids making the README depend on a long list of historical anecdotes to establish credibility. Those anecdotes should become a separate **`CASE_STUDIES.md` or `DEVELOPMENT_HISTORY.md`**. The HERALD and ANVIL discoveries are valuable evidence; they shouldn't disappear—they should simply move to the right document.
One caveat: I could verify the implementation-level claims above directly, but I **couldn't independently confirm the README's exact “47 tests” count from the current GitHub file interface**, because the repository's test directory wasn't exposed as a fetchable file in the connector. I therefore deliberately removed the hard-coded test count from the professional version rather than repeating an unverified number.