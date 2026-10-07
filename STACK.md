# Stack role — ghost_tools

**ASSURANCE (not the live decision path).**

Codebase integrity toolkit: structural ghosts, documentation drift, duplication, dead code, parallel implementations; optional branch surgeon. Human triage required for fixes.

| Related | Role |
|---------|------|
| [SWIZZLE](https://github.com/wking53214/SWIZZLE) | Adversarial lab targeting this toolkit |
| [TOUCHSTONE](https://github.com/wking53214/TOUCHSTONE) | Non-synthetic ground-truth specimens; replayed by the swizzle-gate CI job |
| [Elegant](https://github.com/wking53214/Elegant) | Calls ghost_buster to observe and re-inspect around a human-authorized change |
| [observe-perceive](https://github.com/wking53214/observe-perceive) | Live governed-action hub |

```text
Live path: Admission → OBSERVE/Keys → Locks → PERCEIVE → Decision → Conservation → Execution → Custody
Assurance: ghost_tools · Elegant · SWIZZLE · TOUCHSTONE
```

See [README.md](README.md) for full tool documentation.
