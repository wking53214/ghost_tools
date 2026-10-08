# Stack role — ghost_tools

**ASSURANCE (not the live decision path).**

Codebase integrity toolkit: structural ghosts, documentation drift, duplication, dead code, parallel implementations. Human triage required for fixes.

| Related | Role |
|---------|------|
| [SWIZZLE](https://github.com/wking53214/SWIZZLE) | Adversarial lab targeting this toolkit |
| [ASSAY](https://github.com/wking53214/ASSAY) | Non-synthetic ground-truth specimens; replayed by the swizzle-gate CI job |
| [Warden](https://github.com/wking53214/Warden) | Calls ghost_buster to observe and re-inspect around a human-authorized change |
| [observe-perceive](https://github.com/wking53214/observe-perceive) | Live governed-action hub |

```text
Live path: Admission → OBSERVE/Keys → Locks → PERCEIVE → Decision → Conservation → Execution → Custody
Assurance: ghost_tools · Warden · SWIZZLE · ASSAY
```

See [README.md](README.md) for full tool documentation.
