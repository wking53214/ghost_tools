# Continuous Improvement Loop and Arbiter

## Overview

Ghost Tools implements a continuous improvement ecosystem between Swizzle and Ghost Tools repositories. The system uses two core components:

1. **Loop Orchestrator** - Manages iterative improvement cycles
2. **Arbiter** - Validates improvements through metrics-based decision making

Together, they create a feedback loop where both repositories analyze each other, propose improvements, and validate them against established criteria.

## The Continuous Improvement Loop

### Architecture

The loop operates across two repositories:
- **Swizzle**: Ecosystem arbitration and verification system
- **Ghost Tools**: Surgical improvement and analysis tools

### Loop Lifecycle

#### 1. Initialization
- Loop starts in IDLE state
- Convergence threshold set to 1% (improvements below this end the loop)
- Maximum iterations limit set (typically 20)
- Loop state persisted in `loop_state.json`

#### 2. Iteration Cycle
Each iteration follows this sequence:

```
Send Improvement → Arbiter Validates → Accept/Reject → Record → Check Convergence
```

**Phase 1: Generate Improvements**
- Source repository (A) analyzes target repository (B)
- Identifies enhancement opportunities through mechanical scans
- Proposes improvements with improvement IDs

**Phase 2: Arbiter Validation**
- Arbiter evaluates proposed improvements against:
  - Critical metrics (must not regress)
  - Weighted improvement scores
  - Acceptance thresholds
- Returns `ValidationVerdict` with confidence score

**Phase 3: Accept or Reject**
- Improvements with ACCEPT verdict → applied to target
- Improvements with CONDITIONAL verdict → flagged for review
- Improvements with REJECT verdict → discarded
- All verdicts recorded with reasoning

**Phase 4: Record Iteration**
- Iteration number tracked
- Sender/receiver repos recorded
- Net improvement percentage calculated
- Timestamp recorded
- Acceptance rate updated

**Phase 5: Convergence Check**
- If last 3 iterations average < 1% improvement → converged
- If reached max iterations → halts
- Otherwise → continues to next iteration

### Loop State Management

```python
class LoopState:
    status: LoopStatus  # IDLE, RUNNING, PAUSED, CONVERGED, STALLED
    iterations: List[LoopIteration]  # History of all iterations
    convergence_threshold: float  # 0.01 = 1%
    max_iterations: int  # Typical: 20
    current_iteration: int
    total_improvement: float
    converged: bool
```

#### Status Transitions
- `IDLE` → `RUNNING` (via `start_loop()`)
- `RUNNING` → `PAUSED` (via `pause_loop()`)
- `PAUSED` → `RUNNING` (via `resume_loop()`)
- `RUNNING` → `CONVERGED` (when improvements < threshold)
- `RUNNING` → `STALLED` (when no progress made)

### Acceptance Rates

The loop tracks acceptance rates per repository:
- **Perfect acceptance**: 100% of proposed improvements accepted
- **High acceptance**: 80-100%
- **Selective acceptance**: 50-80%
- **Low acceptance**: Below 50%

This metric reveals the quality of improvement proposals and alignment between systems.

## The Arbiter System

### Purpose

The Arbiter acts as referee between repositories. Its role:
1. **Evaluate** improvements against concrete metrics
2. **Measure** impact on critical quality signals
3. **Decide** whether to accept, conditionally accept, or reject
4. **Record** all verdicts with confidence scores for auditability

### Validation Metrics

Each improvement is measured against one or more metrics:

```python
class ValidationMetric:
    name: str              # e.g., "test_pass_rate"
    before_value: float    # Baseline measurement
    after_value: float     # Post-improvement measurement
    unit: str             # e.g., "%", "seconds"
    importance: float     # Weight in overall decision (0-1)
```

#### Common Metrics
- **Test pass rate**: Percentage of tests passing (critical)
- **Code coverage**: Line coverage percentage
- **Performance**: Execution time in seconds
- **Code quality**: Static analysis findings count
- **Security**: Vulnerability count

### Verdict Types

```python
class ValidationVerdictType(str, Enum):
    ACCEPT = "accept"              # Clear improvement, apply immediately
    REJECT = "reject"              # Regression or no improvement
    NEEDS_REVIEW = "needs_review"  # Marginal, needs human judgment
    CONDITIONAL = "conditional"    # Meets threshold but with caveats
```

### Verdict Decision Logic

```
If any critical metric regressed:
    → REJECT (confidence: 0.95)

Else calculate weighted score:
    weighted_score = (sum of metric_improvements × metric_importance) / total_importance

If weighted_score >= acceptance_threshold (default 0.0):
    → ACCEPT (confidence: 0.5 + weighted_score, capped at 0.99)

Else if weighted_score >= threshold × 0.5:
    → CONDITIONAL (confidence: 0.7)
    Reason: "Marginal improvement, needs review"

Else:
    → REJECT (confidence: 0.9)
    Reason: "No improvement or regression"
```

### Critical Metrics

Metrics can be marked as "critical", meaning they must not regress:

```python
arbiter.add_critical_metric("test_pass_rate")
arbiter.add_critical_metric("committed_secrets_count")
```

Any improvement that causes a critical metric to regress is automatically rejected regardless of overall weighted score.

### Acceptance Thresholds

Repositories can set individual acceptance thresholds:

```python
arbiter.set_acceptance_threshold(0.05)  # 5% minimum improvement
```

This allows different repos to have different quality bars based on their needs.

## Integration with Event System

The continuous loop integrates with Ghost Tools' event system:

### Events Published

**Integration Events:**
- `INTEGRATION_READY` - Improvement proposal ready for evaluation
- `ORACLE_TRAINING_IMPROVED` - Model learned from accepted improvement

**Decision Events:**
- `DECISION_MADE` - Arbiter rendered verdict
- `VERDICT_RECORDED` - Verdict persisted to history

### Event Flow

```
Repository A                Event Bus              Arbiter
    ↓                          ↓                      ↓
Analyze B ──→ IMPROVEMENT_PROPOSED ─→ validate() ─→ VERDICT_RECORDED
              (with metrics)                         
                                       ↓
                              Feedback to A
```

## Loop + Arbiter Integration Example

### Scenario: Swizzle Improving Ghost Tools

1. **Loop starts**
   ```
   LoopOrchestrator.start_loop()
   Status: RUNNING, Iteration: 0
   ```

2. **Swizzle analyzes Ghost Tools**
   ```
   - Scans codebase
   - Finds: "loop_invariant_call" optimization opportunity
   - Proposes improvement with ID: "swizzle-gt-001"
   ```

3. **Arbiter evaluates**
   ```
   Metrics proposed:
   - test_pass_rate: 98% → 98% (no regression) ✓
   - execution_time: 4.2s → 3.8s (9.5% improvement) ✓
   
   Weighted score: 9.5% (above threshold of 0%)
   Verdict: ACCEPT (confidence: 0.80)
   ```

4. **Ghost Tools applies improvement**
   ```
   - Modifies 2 lines in loop_orchestrator.py
   - Re-runs tests: 98% still passing
   - Commits improvement
   ```

5. **Loop records iteration**
   ```
   Iteration 1:
   - sender: swizzle
   - receiver: ghost_tools
   - improvement_id: swizzle-gt-001
   - accepted: true
   - net_improvement: 9.5%
   - acceptance_rate: 100%
   ```

6. **Ghost Tools analyzes Swizzle**
   ```
   - Proposes improvement to Swizzle
   - Arbiter validates
   - Feedback loop continues
   ```

7. **Convergence**
   ```
   After 10 iterations:
   - Last 3 improvements: 1.2%, 0.8%, 0.5%
   - Average: 0.83% (< 1% threshold)
   - Loop converges: both systems optimized
   ```

## Configuration

### Loop Parameters

```python
loop_orchestrator = LoopOrchestrator(workspace=Path("./loop_workspace"))

# Adjust convergence
loop_orchestrator.loop_state.convergence_threshold = 0.01  # 1%
loop_orchestrator.loop_state.max_iterations = 20
```

### Arbiter Parameters

```python
arbiter = Arbiter(repo_name="ghost_tools")

# Set acceptance bar
arbiter.set_acceptance_threshold(0.05)  # 5% minimum improvement

# Mark critical metrics
arbiter.add_critical_metric("test_pass_rate")
arbiter.add_critical_metric("parsing_errors_count")
```

## Outputs and History

### Loop State File
Location: `<workspace>/loop_state.json`

Contains:
- Current status (IDLE, RUNNING, PAUSED, CONVERGED)
- All iteration records
- Total improvement tracked
- Convergence status

### Iteration History

Each iteration records:
- Iteration number
- Source and target repository
- Improvement ID
- Acceptance decision
- Net improvement percentage
- Timestamp

### Verdict History

Each verdict records:
- Source and target repositories
- Improvement being evaluated
- Verdict type (ACCEPT/REJECT/CONDITIONAL)
- Confidence score (0.0-1.0)
- Reason for decision
- All evaluated metrics and their values
- Timestamp

## Success Criteria

The loop is considered successful when:

1. **Convergence achieved**: Improvements drop below 1% threshold
2. **High acceptance rates**: Both repos maintaining >80% acceptance
3. **Quality maintained**: All critical metrics passing
4. **Productivity gains**: Total improvement > initial baseline by threshold

Example success metrics:
- Started: 100 code quality findings
- After 10 iterations: 30 findings (-70%)
- All tests passing throughout
- No security issues introduced
- Acceptance rate: 93%

## Failure Modes and Recovery

### Stalled Loop
**Cause**: No improvements proposed for multiple iterations
**Recovery**: 
- Check if repos have reached optimal state (expected)
- Or increase convergence threshold
- Or reset and analyze different improvement areas

### High Rejection Rate
**Cause**: Proposed improvements fail arbiter validation
**Recovery**:
- Review rejection reasons
- Adjust critical metrics (if too strict)
- Adjust acceptance threshold
- Improve improvement proposal quality

### Regression Detection
**Cause**: Accepted improvement caused test failures in next iteration
**Recovery**:
- Arbiter automatically catches in next iteration
- Previous improvement rejected in analysis
- Quality gate prevents repeated regressions

## Best Practices

1. **Set reasonable thresholds**: 1-5% convergence, 0-5% acceptance
2. **Mark truly critical metrics**: Only those that must never regress
3. **Monitor acceptance rates**: Should stay >75% to indicate healthy loop
4. **Review first iterations**: Validate that first improvements are sensible
5. **Persist loop state**: Always save to enable resume capability
6. **Log verdicts**: Record all verdicts for audit trail and learning
