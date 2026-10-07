# ghost_buster reference

The short [README](../README.md) says what ghost_tools is for. This page is
the checked inventory behind it: the defaults, every detector, and the
numbers the test suite holds it to. `Tests/test_readme_inventory.py` and
`Tests/test_mutant_census.py` read this file, so a detector added without a
row here, a flag documented after it is removed, or a stale mutant count
turns the suite red.

## What runs by default

Every check is **on** unless you turn it off, and **every check reports its
state on every run** -- performed, impossible, or declined.

| Check | Default | Turn off with |
|---|---|---|
| the twenty-four registered detectors | on | (always run) |
| unmerged branches | on | `--no-branches` |
| test status | on, for a trusted repository (`--trust`, once) | `--no-tests` |
| committed secrets | on | `--no-secrets` |
| project checks (CI, deploy artifacts, test configuration) | on | `--no-project` |
| structural model | on | `--no-structure` |
| correlation | on | `--no-correlate` |
| ledger (memory) | on | `--no-ledger` |
| cross-repository seam | asks, on a terminal; single-repo otherwise | `--join PATH` or `--single-repo` says so outright |
| shared kernel | **off** | opt-in because it needs a path: `--kernel PATH` |
| mutation (`--mutate`) | **off**, and needs a trusted repository | opt-in on cost: one pytest process per mutant |
| semantic layer | **off, and has no flag** | a library (`ghost_buster.semantic`), never wired into the CLI, because every call is paid |

The table above is the source of truth for defaults. Every flag in it exists
in `ghost_buster/cli.py` with the default shown; the `--help` text says "ON
BY DEFAULT" on each one that is.

The half that matters more than the defaults: **a check that does not run
says so.** Until v0.10.1 the repository checks were opt-in and a run that
skipped one printed nothing about it. Measured on a real repository, a scan
with `--branches --secrets` reported 34 findings and exit 1, looked like a
complete audit, and never mentioned that test status had gone unexamined --
where five clinical missed detections were sitting behind skips that
`--tests` rates MAJOR. Silence about a check is the defect; declining one
on purpose is fine, and now leaves a receipt in the output.

Two consequences worth knowing before you point this at an unfamiliar
repository:

- **A default run executes the project's test suite, once you have said
  it may.** That is what `--tests` does. The first run on a repository
  declines the test and mutation scans with a receipt naming the trust
  store; `--trust` records consent once, keyed by the `origin` remote (so
  a fresh clone of a trusted repository is trusted) or by path when there
  is none, in `~/.config/ghost_tools/trust.json` or `$GHOST_TOOLS_TRUST`.
  A file inside the repository would be the stranger's to write, so the
  store is yours. `--no-tests` still declines on purpose, with its own
  receipt, and `GHOST_TOOLS_TRUST=-` trusts everything for a harness that
  scans its own fixtures, printed on the receipt line and never silent.

  **What consent covers, exactly: a name, not a tree.** The grant is
  recorded against the remote, so it holds for every checkout of that
  remote, at any commit, with any contents, until you remove it. Pulling
  a commit does not re-prompt, a second clone inherits the decision, and
  somebody who can change what a trusted remote contains gets their code
  run by your next `--tests`. That is the same question a CI
  configuration answers when it runs a suite, and it is a different
  question from "do I trust this exact code", which would mean consenting
  per commit. If you need the stronger property today, `--no-tests`
  executes nothing regardless of consent. `ghost_buster/trust.py` states
  the model in full.
- **A default run takes minutes, not seconds**, because of that suite.
  `--no-tests` gets the old fast structural pass back.

## What it checks

Every registered detector, by name, with the severity it can reach. This
table is the index, and it is checked against `registered_detectors()` by
the test suite. Each detector's full account is its module docstring; the
long-form prose that used to follow this table lives in the README's git
history (`git show 93143f5^:README.md`).

| Detector | Reports | Up to |
|---|---|---|
| `unassessable_file` | a file the corpus could not read or parse, so every detector below skipped it | MAJOR |
| `merge_conflict_marker` | an unresolved `<<<<<<<` / `=======` / `>>>>>>>` triplet | CRITICAL |
| `dead_code` | a definition nothing in the scan references | MINOR |
| `dead_end_call` | a definition live code calls whose body does nothing, with no seam declared | MAJOR |
| `long_function` | a function past the length threshold | MAJOR |
| `duplicate_file` | a byte-identical file group, reported once | MAJOR |
| `drifted_copy` | the same file in several places, no longer agreeing | MAJOR |
| `near_duplicate_function` | two functions with the same structural fingerprint | MAJOR |
| `intra_function_duplicate_block` | repeated branch bodies inside one function | MAJOR |
| `swallowed_exception` | a handler that catches something and does nothing | MAJOR |
| `unreachable_declared_state` | an enum member no code produces, in an enum whose others it does | MINOR&nbsp;/&nbsp;MAJOR&nbsp;/&nbsp;CRITICAL |
| `doc_test_count_drift` | a test count in a markdown file the real suite has grown well past | MINOR |
| `name_disagreement` | one value passed under two names, only where it is a bijection | MINOR |
| `vestigial_domain_name` | an identifier carrying a domain this repository no longer has | MINOR |
| `placeholder_name` | `foo`, `tmp`, `data2`: a name that says nothing, where that is decidable | MINOR |
| `sql_injection` | SQL built by interpolation and then executed | CRITICAL |
| `destructive_sql` | `DELETE` or `UPDATE` with no `WHERE`, or `TRUNCATE`, executed | MAJOR |
| `insecure_default` | `DEBUG = True`, wide-open CORS with credentials, `verify=False` | CRITICAL |
| `unauthenticated_route` | a route with no auth while most of its siblings have it | MAJOR |
| `loop_invariant_call` | a call inside a loop whose arguments the loop cannot change (a serum pitstop) | MINOR |
| `list_membership_in_loop` | membership tests against a list literal inside a loop (a serum pitstop) | MINOR |
| `commented_out_module` | a file that parses and defines nothing because its code is all in comments (TOUCHSTONE 3.1) | MAJOR |
| `undefined_self_method` | `self.name()` on a fully visible class that has no `name` anywhere (TOUCHSTONE 3.2) | MAJOR |
| `flattened_copy` | an unparseable file that is a readable one with its whitespace destroyed (TOUCHSTONE 3.3) | MAJOR |

One detector reads more than the files on disk. `unreachable_declared_state`
grades a declared-but-unproduced enum member by what the evidence costs to
fake. Structure clears it: something building the enum from a runtime value
(`Status(row["s"])`) means the member really can arrive, and faking that
means writing a real deserialiser. Prose never clears it on its own, and a
docstring claiming a member arrives from stored data with no such path is
CRITICAL -- a documented gap is a gap plus an assurance that stops the next
reader looking. And git history, through `ghost_buster/forensics.py`,
separates a state nobody wired up (MINOR) from one a commit stopped
producing (MAJOR), including the case where the last production moved out of
library code and into a test. An unreadable history grades at the weight of
what was actually observed and never escalates; `history=False` makes the
detector a pure function of the files on disk. What that history cannot
tell apart -- a security fix, a deliberate refactor and a regression leave
the same trace -- is in `docs/forensics-limits.md`, with the reason it
escalates anyway.

Beside the detectors, six repository-level checks and two passes over
everything, described in the module docstrings: unmerged branches, test
status, committed secrets, the project checks (`no_ci_configuration`,
`test_config_collects_nothing`), the structural model (`entry point target
missing`, `undeclared dependency`, `parallel packaging metadata`),
the seam between repositories (`--join`), the shared kernel (`--kernel`:
`kernel_shadow`, `drifted_contract`), the ledger (`regressed_finding`,
`flapping_finding`, `persistent_finding`, `blind_spot`, trajectory), and
correlation (four connectors). Readiness reads six criteria off the whole
set and gates the surgeon's serum on them.

## What it remembers

The ledger (`.ghost_ledger.json`), committed beside the baseline: regressed,
flapping and persistent findings, blind spots, and trajectory. See
`ghost_buster/ledger.py` for the full account.

## Tests

`test_mutation.py` and the 54 `Tests/*_mutants.py` files run pytest in
scratch copies with one piece of the code broken at a time, and fail if the
suite still passes: each test file is held to catching the defect it names.
