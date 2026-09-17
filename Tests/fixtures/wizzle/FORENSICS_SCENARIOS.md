# Wizzle: Forensics Edge Cases Repository

Test repository demonstrating edge cases where Ghost's forensics layer produces technically correct but semantically misleading findings.

## Scenario 1: Phantom - Briefly Produced then Removed

### History
1. **16e9923**: Add `Status.PHANTOM` to enum
2. **3e2ddc3**: Use `Status.PHANTOM` in library.py (`get_user_status()`, `check_if_active()`)
3. **ce544ad**: Remove `Status.PHANTOM` usage from library.py
4. **a1a1356**: Remove `Status.PHANTOM` from enum
5. **Test commit**: Add test referencing `Status.PHANTOM`
6. **b923f37**: Re-add `Status.PHANTOM` to enum (for test compatibility)

### Current State
- `Status.PHANTOM` is in the enum
- Only test code uses `Status.PHANTOM`
- Library code does NOT use it

### Forensics Finding
- **Provenance**: `REMOVED_FROM_LIBRARY` (was used in library, no longer is)
- **Severity**: MAJOR (per v1.7.8 model: removal of a produced member)
- **Semantic Truth**: This was genuinely used in production, removed, and now only in tests
- **Technically Correct**: Yes - pickaxe will find it in history (3e2ddc3 added, ce544ad removed)
- **Misleading Aspect**: The removal was intentional; the member isn't a security vulnerability. It's now safely test-only. But the MAJOR severity treats it like a regression.

### Defense Test
Verify that the forensics layer correctly classifies removal + test-only re-addition as REMOVED_FROM_LIBRARY, not UNKNOWN or RELOCATED_TO_TESTS.

---

## Scenario 2: Priority.MEDIUM - Intentional Removal but Forensics Shows Regression

### History
1. **742f7fe**: Add `Priority` enum with HIGH, MEDIUM
2. **d409716**: Use `Priority.MEDIUM` in library.py (`get_default_priority()`)
3. **8143675**: Remove `Priority.MEDIUM` usage from library.py (intentional refactor)
4. **a927298**: Remove `Priority.MEDIUM` from enum
5. **Test commit**: Add test for `Priority.MEDIUM`
6. **39b1274**: Re-add `Priority.MEDIUM` to enum

### Current State
- `Priority.MEDIUM` is in the enum
- Only test code uses it
- Library defaults to `Priority.HIGH`

### Forensics Finding
- **Provenance**: `REMOVED_FROM_LIBRARY` (was used, removed, now test-only)
- **Severity**: MAJOR
- **Semantic Truth**: Removal was intentional (use HIGH instead). Safe to have in tests.
- **Technically Correct**: Yes - pickaxe shows it was in production history
- **Misleading Aspect**: This wasn't a regression or vulnerability; it was a deliberate design decision. The member is now properly scoped to tests.

### Edge Case
This demonstrates the fundamental ambiguity: "removed from library" could mean:
- A security fix (definitely MAJOR)
- A refactoring (not necessarily a defect)
- Test-only legacy code (safe, but still flagged as MAJOR)

The forensics layer can't distinguish between these cases from git history alone.

---

## Scenario 3: Conflicting Implementations (Future)

### Concept
A member that exists in both library.py and Tests/ with different implementations or semantics. The forensics layer would need to disambiguate which version is "real" or whether they represent a design conflict.

---

## Key Questions for Forensics Defense

1. **Relocation vs. Removal**: Can Ghost distinguish between legitimate refactoring (member moved to tests) and regression (member removed)?

2. **Intentional vs. Accidental**: Is there signal in the commit message or history that the removal was deliberate vs. accidental?

3. **Semantic Misleading**: When is a REMOVED_FROM_LIBRARY finding semantically misleading?
   - If the removal was a deliberate design decision → not misleading
   - If the removal was a bug → actually misleading (should say REGRESSION)
   - If the removal was a security fix → correctly MAJOR

4. **Cost-to-Fake vs. Actual Risk**: The forensics model prioritizes cost-to-fake, but does removal-from-production-history have a constant cost regardless of context?

---

## Running Analysis

```bash
# Run Ghost's full detector on wizzle
cd /home/user/ghost_tools
python -m ghost_buster.cli /tmp/wizzle

# Run forensics directly on specific members
python -c "
from ghost_buster.forensics import provenance, Provenance
from ghost_buster.mechanical import _analyse_sources
from pathlib import Path

repo = Path('/tmp/wizzle')

def analyse(sources):
    return _analyse_sources(sources)

result = provenance(repo, 'Status', 'PHANTOM', analyse=analyse)
print(f'Status.PHANTOM provenance: {result}')

result = provenance(repo, 'Priority', 'MEDIUM', analyse=analyse)
print(f'Priority.MEDIUM provenance: {result}')
"
```

---

## Expected Behaviors

### PHANTOM
- Forensics should find it in history via pickaxe
- Current state: test-only production (safe)
- Historical state: was produced in library (3e2ddc3)
- Classification: `REMOVED_FROM_LIBRARY` → severity MAJOR

### MEDIUM
- Forensics should find it in history via pickaxe
- Current state: test-only production (safe)
- Historical state: was produced in library (d409716)
- Classification: `REMOVED_FROM_LIBRARY` → severity MAJOR

Both findings are **technically correct** but **semantically misleading** because:
1. The members ARE properly scoped (tests only)
2. The removal was intentional, not a regression
3. They pose no security risk
4. But pickaxe sees "removed from library" and escalates to MAJOR

---

## Implications for Ghost v1.7.8+

The forensics layer performs exactly as designed:
- Uses git pickaxe to walk history
- Classifies members based on when they entered/exited production
- Escalates based on evidence of removal from production

The misleading findings aren't **bugs** — they're **design constraints** of a git-history-based approach:
- Git history is objective; intent is subjective
- A member removed from production COULD indicate a regression
- But it COULD ALSO indicate intentional refactoring
- The detector errs on the side of caution (MAJOR for removal)

To reduce false positives, future versions could:
1. Analyze commit messages for signal (e.g., "refactor:", "fix:","remove:")
2. Check if the member appears in a changelog or release notes
3. Correlate with other evidence (test coverage, documentation)
4. Allow whitelisting of known-safe removals
