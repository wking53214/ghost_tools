"""Tests for autonomous decision engine.

Validates decision creation, risk assessment, auto-approval, and execution.
"""

import pytest
from pathlib import Path
from datetime import datetime

from swizzle.integration.decision_engine import (
    DecisionEngine, DecisionPolicy, DecisionType, RiskLevel, ConfidenceSource,
    AutomatedDecision, ConfidenceScore, get_decision_engine, reset_decision_engine,
)
from swizzle.integration.decision_handlers import setup_decision_handlers
from swizzle.integration.event_system import (
    create_false_positive_event, create_violation_event, create_regression_event,
    create_mutation_event, create_oracle_event, reset_event_bus, get_event_bus,
)
from swizzle.integration.event_evaluator import (
    setup_event_evaluation, get_event_evaluator, reset_event_evaluator,
)
from swizzle.integration.unified_index import reset_unified_index


class TestDecisionPolicy:
    """Test decision policy and thresholds."""

    def test_policy_thresholds(self):
        """Verify policy thresholds are set."""
        policy = DecisionPolicy()

        assert policy.auto_apply_thresholds[RiskLevel.LOW] == 0.85
        assert policy.auto_apply_thresholds[RiskLevel.MEDIUM] == 0.95
        assert policy.auto_apply_thresholds[RiskLevel.HIGH] == 1.0
        assert policy.auto_apply_thresholds[RiskLevel.CRITICAL] == 1.0

    def test_auto_approvable_types(self):
        """Verify auto-approvable decision types."""
        policy = DecisionPolicy()

        low_approvable = policy.auto_approvable_types[RiskLevel.LOW]
        assert DecisionType.APPLY_FILTER_PATTERN in low_approvable
        assert DecisionType.UPDATE_ORACLE_TRAINING in low_approvable
        assert DecisionType.ADD_TEST_CASE in low_approvable

        high_approvable = policy.auto_approvable_types[RiskLevel.HIGH]
        assert len(high_approvable) == 0

    def test_should_auto_approve_low_risk(self):
        """Verify low-risk decisions are auto-approvable."""
        policy = DecisionPolicy()

        assert policy.should_auto_approve(
            DecisionType.APPLY_FILTER_PATTERN,
            RiskLevel.LOW,
            0.90,  # Above 0.85 threshold
        )

    def test_should_not_auto_approve_low_confidence(self):
        """Verify low confidence prevents auto-approval."""
        policy = DecisionPolicy()

        assert not policy.should_auto_approve(
            DecisionType.APPLY_FILTER_PATTERN,
            RiskLevel.LOW,
            0.80,  # Below 0.85 threshold
        )

    def test_should_not_auto_approve_high_risk(self):
        """Verify high-risk decisions are never auto-approvable."""
        policy = DecisionPolicy()

        assert not policy.should_auto_approve(
            DecisionType.ESCALATE_VIOLATION,
            RiskLevel.HIGH,
            1.0,  # Perfect confidence still not enough
        )

    def test_should_escalate(self):
        """Verify escalation policy."""
        policy = DecisionPolicy()

        assert policy.should_escalate(RiskLevel.HIGH)
        assert policy.should_escalate(RiskLevel.CRITICAL)
        assert not policy.should_escalate(RiskLevel.LOW)
        assert not policy.should_escalate(RiskLevel.MEDIUM)


class TestDecisionEngine:
    """Test decision engine evaluation and execution."""

    def test_engine_singleton(self):
        """Verify engine is singleton."""
        reset_decision_engine()
        eng1 = get_decision_engine()
        eng2 = get_decision_engine()
        assert eng1 is eng2

    def test_evaluate_false_positive_event(self):
        """Verify FP events create decisions."""
        reset_unified_index()
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_false_positive_event(
            false_positive_id="fp1",
            finding_type="dated_claim",
            confidence=0.95,
            indicators=["generated on"],
        )

        decision = engine.evaluate_event(event)
        assert decision is not None
        assert decision.type == DecisionType.APPLY_FILTER_PATTERN
        assert decision.risk_level == RiskLevel.LOW
        # Confidence may be ML-enhanced if historical data exists, so check approximate
        assert 0.93 <= decision.confidence.value <= 0.96

    def test_evaluate_violation_event(self):
        """Verify violation events create decisions."""
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_violation_event(
            violation_id="v1",
            violation_type="boundary_violation",
            boundary_id="lab_independence",
            location="swizzle/lab/test.py:42",
            severity="CRITICAL",
        )

        decision = engine.evaluate_event(event)
        assert decision is not None
        assert decision.type == DecisionType.ESCALATE_VIOLATION
        assert decision.risk_level == RiskLevel.HIGH
        assert decision.confidence.value == 1.0

    def test_evaluate_regression_event(self):
        """Verify regression events create decisions."""
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_regression_event(
            contract_id="ghost_scan_per_file",
            case_id="case_1",
            metric_name="wall_time",
            baseline_value=50.0,
            current_value=60.0,
            regression_percent=10.0,
        )

        decision = engine.evaluate_event(event)
        assert decision is not None
        assert decision.risk_level == RiskLevel.LOW
        assert decision.confidence.value == 0.80

    def test_evaluate_mutation_event(self):
        """Verify mutation events create decisions."""
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_mutation_event(
            case_id="symlink_escape",
            hypothesis="tool fails on symlinks escaping repo",
            severity="CRITICAL",
            minimized=True,
        )

        decision = engine.evaluate_event(event)
        assert decision is not None
        assert decision.type == DecisionType.ADD_TEST_CASE
        assert decision.risk_level == RiskLevel.LOW
        assert decision.confidence.value == 0.95

    def test_evaluate_oracle_event(self):
        """Verify oracle events create decisions."""
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_oracle_event(
            finding_type="dated_claim",
            accuracy=0.92,
            training_size=150,
            improvement_percent=5.0,
        )

        decision = engine.evaluate_event(event)
        assert decision is not None
        assert decision.type == DecisionType.UPDATE_ORACLE_TRAINING
        assert decision.risk_level == RiskLevel.LOW

    def test_make_decision_auto_approves_low_risk(self):
        """Verify low-risk decisions are auto-approved."""
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_false_positive_event(
            false_positive_id="fp1",
            finding_type="dated_claim",
            confidence=0.95,
            indicators=["generated on"],
        )

        decision = engine.make_decision(event)
        assert decision is not None
        assert decision.approved
        assert decision.approval_reason == "Auto-approved by policy"

    def test_make_decision_does_not_auto_approve_high_risk(self):
        """Verify high-risk decisions are not auto-approved."""
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_violation_event(
            violation_id="v1",
            violation_type="boundary_violation",
            boundary_id="lab_independence",
            location="swizzle/lab/test.py:42",
            severity="CRITICAL",
        )

        decision = engine.make_decision(event)
        assert decision is not None
        assert not decision.approved

    def test_register_and_execute_handler(self):
        """Verify handlers can be registered and executed."""
        reset_decision_engine()
        engine = get_decision_engine()
        setup_decision_handlers()

        event = create_mutation_event(
            case_id="test_case",
            hypothesis="test hypothesis",
            severity="HIGH",
            minimized=True,
        )

        decision = engine.make_decision(event)
        assert decision is not None
        assert decision.executed

        # Verify the case was added to the catalog
        from swizzle.integration.mutation_transfer import DEFAULT_MUTATION_CATALOG
        assert "test_case" in DEFAULT_MUTATION_CATALOG.cases

    def test_approve_decision_by_id(self):
        """Verify decisions can be approved by ID."""
        reset_decision_engine()
        engine = get_decision_engine()
        setup_decision_handlers()

        event = create_violation_event(
            violation_id="v1",
            violation_type="boundary_violation",
            boundary_id="lab_independence",
            location="swizzle/lab/test.py:42",
            severity="HIGH",
        )

        decision = engine.make_decision(event)
        decision_id = decision.id

        assert not decision.executed
        result = engine.approve_decision(decision_id, "reviewer", "Looks good")

        assert result
        assert decision.executed
        assert decision.reviewed_by == "reviewer"

    def test_reject_decision_by_id(self):
        """Verify decisions can be rejected by ID."""
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_violation_event(
            violation_id="v1",
            violation_type="boundary_violation",
            boundary_id="lab_independence",
            location="swizzle/lab/test.py:42",
            severity="HIGH",
        )

        decision = engine.make_decision(event)
        decision_id = decision.id

        result = engine.reject_decision(decision_id, "reviewer", "Too risky")

        assert result
        assert not decision.executed
        assert decision.reviewed_by == "reviewer"

    def test_pending_review(self):
        """Verify pending review list is correct."""
        reset_decision_engine()
        engine = get_decision_engine()

        # Create high-risk event that won't auto-approve
        event = create_violation_event(
            violation_id="v1",
            violation_type="boundary_violation",
            boundary_id="lab_independence",
            location="swizzle/lab/test.py:42",
            severity="HIGH",
        )

        engine.make_decision(event)

        pending = engine.pending_review()
        assert len(pending) >= 1
        assert all(not d.approved for d in pending)

    def test_execution_report(self):
        """Verify execution report generation."""
        reset_decision_engine()
        engine = get_decision_engine()
        setup_decision_handlers()

        # Create multiple events
        fp_event = create_false_positive_event("fp1", "dated_claim", 0.95, [])
        mutation_event = create_mutation_event("case1", "hypothesis", "HIGH", True)

        engine.make_decision(fp_event)
        engine.make_decision(mutation_event)

        report = engine.get_execution_report()

        assert report["total_decisions"] == 2
        assert report["auto_approved"] == 2
        # Both should execute as they're low-risk
        assert report["executed"] >= 1


class TestEventEvaluator:
    """Test integration between events and decisions."""

    def test_event_evaluator_singleton(self):
        """Verify evaluator is singleton."""
        reset_event_evaluator()
        ev1 = get_event_evaluator()
        ev2 = get_event_evaluator()
        assert ev1 is ev2

    def test_event_triggers_decision(self):
        """Verify events trigger decision evaluation."""
        reset_event_bus()
        reset_decision_engine()
        reset_event_evaluator()

        setup_decision_handlers()
        setup_event_evaluation()

        evaluator = get_event_evaluator()
        bus = get_event_bus()

        # Publish event
        event = create_false_positive_event("fp1", "dated_claim", 0.95, [])
        bus.publish(event)

        # Stats should show decision was made
        stats = evaluator.get_stats()
        assert stats["decisions_made"] >= 1
        assert stats["decisions_auto_approved"] >= 1

    def test_multiple_events_create_decisions(self):
        """Verify multiple events create multiple decisions."""
        reset_event_bus()
        reset_decision_engine()
        reset_event_evaluator()

        setup_decision_handlers()
        setup_event_evaluation()

        evaluator = get_event_evaluator()
        bus = get_event_bus()

        # Publish multiple events
        for i in range(3):
            event = create_false_positive_event(f"fp{i}", "dated_claim", 0.95, [])
            bus.publish(event)

        stats = evaluator.get_stats()
        assert stats["decisions_made"] == 3
        assert stats["decisions_auto_approved"] == 3


class TestDecisionTypes:
    """Test all decision type evaluations."""

    def test_apply_filter_pattern_decision(self):
        """Verify FP filter pattern decision."""
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_false_positive_event("fp1", "dated_claim", 0.95, ["generated"])
        decision = engine.evaluate_event(event)

        assert decision.type == DecisionType.APPLY_FILTER_PATTERN
        assert decision.action_data["finding_type"] == "dated_claim"
        assert len(decision.action_data["indicators"]) > 0

    def test_escalate_violation_decision(self):
        """Verify violation escalation decision."""
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_violation_event("v1", "boundary_violation", "lab", "file:1", "CRITICAL")
        decision = engine.evaluate_event(event)

        assert decision.type == DecisionType.ESCALATE_VIOLATION
        assert decision.action_data["boundary_id"] == "lab"

    def test_update_oracle_training_decision(self):
        """Verify oracle training update decision."""
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_oracle_event("dated_claim", 0.92, 150, 5.0)
        decision = engine.evaluate_event(event)

        assert decision.type == DecisionType.UPDATE_ORACLE_TRAINING
        assert decision.action_data["finding_type"] == "dated_claim"

    def test_add_test_case_decision(self):
        """Verify test case addition decision."""
        reset_decision_engine()
        engine = get_decision_engine()

        event = create_mutation_event("case1", "hypothesis", "CRITICAL", True)
        decision = engine.evaluate_event(event)

        assert decision.type == DecisionType.ADD_TEST_CASE
        assert decision.action_data["case_id"] == "case1"
