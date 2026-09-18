"""Handlers that execute automated decisions.

Each handler implements the action for a decision type, updating the
appropriate integration models when decisions are executed.
"""

from typing import Dict, Any
from datetime import datetime

from .decision_engine import AutomatedDecision, DecisionType, get_decision_engine


class DecisionHandlers:
    """Handlers for executing automated decisions."""

    @staticmethod
    def handle_apply_filter_pattern(decision: AutomatedDecision) -> None:
        """Apply a false positive filter pattern."""
        from .feedback_loop import DEFAULT_FEEDBACK_REPORT, FalsePositivePattern, FindingType

        data = decision.action_data

        finding_type_map = {
            "dated_claim": FindingType.DATED_CLAIM,
            "prose_deleted": FindingType.PROSE_DELETED,
            "boundary_violated": FindingType.BOUNDARY_VIOLATED,
        }

        pattern = FalsePositivePattern(
            id=f"pattern_{data['false_positive_id']}",
            finding_type=finding_type_map.get(data["finding_type"], FindingType.DATED_CLAIM),
            description=f"Auto-applied FP pattern from {decision.triggered_by.source_tool}",
            indicators=data.get("indicators", []),
            confidence=decision.confidence.value,
        )

        if pattern.id not in DEFAULT_FEEDBACK_REPORT.false_positive_patterns:
            DEFAULT_FEEDBACK_REPORT.false_positive_patterns[pattern.id] = pattern

    @staticmethod
    def handle_reject_filter_pattern(decision: AutomatedDecision) -> None:
        """Reject an overly-aggressive false positive pattern."""
        # This would remove a pattern if it's causing too many false negatives
        from .feedback_loop import DEFAULT_FEEDBACK_REPORT

        pattern_id = f"pattern_{decision.action_data.get('false_positive_id')}"
        if pattern_id in DEFAULT_FEEDBACK_REPORT.false_positive_patterns:
            del DEFAULT_FEEDBACK_REPORT.false_positive_patterns[pattern_id]

    @staticmethod
    def handle_update_oracle_training(decision: AutomatedDecision) -> None:
        """Update oracle training with new finding type data."""
        from .feedback_loop import DEFAULT_FEEDBACK_REPORT, OracleTrainingDatapoint, FindingType

        data = decision.action_data

        finding_type_map = {
            "dated_claim": FindingType.DATED_CLAIM,
            "prose_deleted": FindingType.PROSE_DELETED,
            "boundary_violated": FindingType.BOUNDARY_VIOLATED,
        }

        # Create training datapoint for oracle
        dp = OracleTrainingDatapoint(
            finding_id=f"auto_{decision.id}",
            finding_type=finding_type_map.get(data["finding_type"], FindingType.DATED_CLAIM),
            repository_features={},
            tool_claim="Oracle training update",
            ground_truth=True,  # Improvement implies accuracy
            oracle_confidence=decision.confidence.value,
            verified_by="decision_engine",
            verified_at=datetime.now().isoformat(),
        )

        DEFAULT_FEEDBACK_REPORT.add_training_datapoint(dp)

    @staticmethod
    def handle_escalate_violation(decision: AutomatedDecision) -> None:
        """Log an architecture violation for review."""
        # This is mostly logging - actual fix requires code changes
        data = decision.action_data
        print(f"[ESCALATED] Architecture violation in {data['boundary_id']}: {data['location']}")

    @staticmethod
    def handle_adjust_performance_threshold(decision: AutomatedDecision) -> None:
        """Loosen a performance contract threshold slightly."""
        from .performance_contract import DEFAULT_PERFORMANCE_REPORT

        data = decision.action_data
        contract_id = data.get("contract_id")

        if contract_id in DEFAULT_PERFORMANCE_REPORT.contracts:
            contract = DEFAULT_PERFORMANCE_REPORT.contracts[contract_id]
            regression_pct = data.get("regression_percent", 0)

            # Adjust threshold up by 10-20% of regression
            if regression_pct < 15:
                adjustment = 1.05  # 5% increase
            else:
                adjustment = 1.10  # 10% increase

            contract.threshold_value *= adjustment

    @staticmethod
    def handle_add_test_case(decision: AutomatedDecision) -> None:
        """Add a mutation case to test suite."""
        from .mutation_transfer import DEFAULT_MUTATION_CATALOG, MutationCase

        data = decision.action_data

        case = MutationCase(
            id=data["case_id"],
            hypothesis=data["hypothesis"],
            severity=data["severity"],
            minimized=True,
            repository_mutations={},
            expected_outcome="",
        )

        if case.id not in DEFAULT_MUTATION_CATALOG.cases:
            DEFAULT_MUTATION_CATALOG.cases[case.id] = case

    @staticmethod
    def handle_suppress_finding(decision: AutomatedDecision) -> None:
        """Suppress a recurrent false positive finding."""
        # This would add finding to suppress list
        data = decision.action_data
        print(f"[SUPPRESSED] Finding {data.get('finding_id', 'unknown')}")

    @staticmethod
    def handle_require_human_review(decision: AutomatedDecision) -> None:
        """Mark decision as requiring human review (no-op handler)."""
        # This decision is handled by the orchestrator
        pass


def setup_decision_handlers() -> None:
    """Register all decision handlers with the engine."""
    engine = get_decision_engine()

    engine.register_handler(
        DecisionType.APPLY_FILTER_PATTERN,
        DecisionHandlers.handle_apply_filter_pattern,
    )

    engine.register_handler(
        DecisionType.REJECT_FILTER_PATTERN,
        DecisionHandlers.handle_reject_filter_pattern,
    )

    engine.register_handler(
        DecisionType.UPDATE_ORACLE_TRAINING,
        DecisionHandlers.handle_update_oracle_training,
    )

    engine.register_handler(
        DecisionType.ESCALATE_VIOLATION,
        DecisionHandlers.handle_escalate_violation,
    )

    engine.register_handler(
        DecisionType.ADJUST_PERFORMANCE_THRESHOLD,
        DecisionHandlers.handle_adjust_performance_threshold,
    )

    engine.register_handler(
        DecisionType.ADD_TEST_CASE,
        DecisionHandlers.handle_add_test_case,
    )

    engine.register_handler(
        DecisionType.SUPPRESS_FINDING,
        DecisionHandlers.handle_suppress_finding,
    )

    engine.register_handler(
        DecisionType.REQUIRE_HUMAN_REVIEW,
        DecisionHandlers.handle_require_human_review,
    )
