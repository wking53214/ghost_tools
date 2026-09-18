"""Tests for CI/CD pipeline integration."""

import pytest
from datetime import datetime

from swizzle.integration.cicd_integration import (
    TestResult, PerformanceMetric, GateDecision, PerformanceThresholdManager,
    CIDDIntegrationEngine, get_cicd_engine, reset_cicd_engine,
)
from swizzle.integration.unified_index import reset_unified_index
from swizzle.integration.decision_engine import reset_decision_engine


class TestTestResult:
    """Test TestResult data class."""

    def test_create_test_result(self):
        """Verify test result creation."""
        result = TestResult(
            test_id="t1",
            test_name="test_foo",
            passed=True,
            duration_seconds=1.23,
        )

        assert result.test_id == "t1"
        assert result.test_name == "test_foo"
        assert result.passed is True
        assert result.duration_seconds == 1.23


class TestPerformanceMetric:
    """Test performance metric evaluation."""

    def test_metric_within_threshold(self):
        """Verify metric within threshold."""
        metric = PerformanceMetric(
            metric_name="response_time",
            value=50.0,
            threshold=100.0,
            unit="ms",
        )

        assert not metric.exceeds_threshold()
        assert metric.regression_percent() == -50.0

    def test_metric_exceeds_threshold(self):
        """Verify metric exceeding threshold."""
        metric = PerformanceMetric(
            metric_name="response_time",
            value=150.0,
            threshold=100.0,
            unit="ms",
        )

        assert metric.exceeds_threshold()
        assert metric.regression_percent() == 50.0

    def test_regression_percent_calculation(self):
        """Verify regression percentage calculation."""
        metric = PerformanceMetric(
            metric_name="error_rate",
            value=0.15,
            threshold=0.10,
            unit="percent",
        )

        # Use approximate comparison for floating point
        assert abs(metric.regression_percent() - 50.0) < 0.001


class TestPerformanceThresholdManager:
    """Test threshold management."""

    def test_set_baseline_threshold(self):
        """Verify baseline threshold setting."""
        reset_unified_index()
        from swizzle.integration.unified_index import get_unified_index
        index = get_unified_index()
        manager = PerformanceThresholdManager(index)

        manager.set_baseline_threshold("response_time", 100.0)

        assert manager.get_threshold("response_time") == 100.0

    def test_adjust_threshold(self):
        """Verify threshold adjustment."""
        reset_unified_index()
        from swizzle.integration.unified_index import get_unified_index
        index = get_unified_index()
        manager = PerformanceThresholdManager(index)

        manager.set_baseline_threshold("response_time", 100.0)
        manager.adjust_threshold("response_time", 120.0, "Loosening due to high load")

        assert manager.get_threshold("response_time") == 120.0
        assert len(manager.adjustment_history) == 1

    def test_suggest_adjustment_for_relaxation(self):
        """Verify threshold relaxation suggestion."""
        reset_unified_index()
        from swizzle.integration.unified_index import get_unified_index
        index = get_unified_index()
        manager = PerformanceThresholdManager(index)

        manager.set_baseline_threshold("response_time", 100.0)
        recent_values = [110.0, 115.0, 120.0]  # Consistently above threshold

        suggestion = manager.suggest_adjustment("response_time", recent_values)

        assert suggestion is not None
        new_threshold, reason = suggestion
        assert new_threshold > 100.0
        assert "relaxing" in reason.lower()

    def test_suggest_adjustment_for_tightening(self):
        """Verify threshold tightening suggestion."""
        reset_unified_index()
        from swizzle.integration.unified_index import get_unified_index
        index = get_unified_index()
        manager = PerformanceThresholdManager(index)

        manager.set_baseline_threshold("response_time", 100.0)
        recent_values = [70.0, 75.0, 80.0]  # Consistently below threshold

        suggestion = manager.suggest_adjustment("response_time", recent_values)

        assert suggestion is not None
        new_threshold, reason = suggestion
        assert new_threshold < 100.0
        assert "tightening" in reason.lower()


class TestCIDDIntegrationEngine:
    """Test CI/CD integration engine."""

    def test_engine_creation(self):
        """Verify engine can be created."""
        reset_unified_index()
        reset_decision_engine()
        reset_cicd_engine()

        engine = get_cicd_engine()
        assert engine is not None
        assert engine.decision_engine is not None

    def test_evaluate_test_gate_all_pass(self):
        """Verify test gate with all passing tests."""
        reset_unified_index()
        reset_decision_engine()
        reset_cicd_engine()

        engine = get_cicd_engine()

        results = [
            TestResult(test_id="t1", test_name="test_a", passed=True, duration_seconds=1.0),
            TestResult(test_id="t2", test_name="test_b", passed=True, duration_seconds=1.0),
            TestResult(test_id="t3", test_name="test_c", passed=True, duration_seconds=1.0),
        ]

        decision = engine.evaluate_test_gate("unit_tests", results)

        assert decision.should_pass is True
        assert decision.confidence >= 0.85

    def test_evaluate_test_gate_some_failures(self):
        """Verify test gate with minor failures (91% pass rate)."""
        reset_unified_index()
        reset_decision_engine()
        reset_cicd_engine()

        engine = get_cicd_engine()

        # 10 passed, 1 failed = 91% pass rate (above 90% threshold)
        results = [
            TestResult(test_id=f"t{i}", test_name=f"test_{i}", passed=True, duration_seconds=1.0)
            for i in range(10)
        ]
        results.append(TestResult(test_id="t_fail", test_name="test_fail", passed=False, duration_seconds=1.0, error_message="Assertion failed"))

        decision = engine.evaluate_test_gate("unit_tests", results)

        assert decision.should_pass is True  # 10/11 = 91%, acceptable
        assert decision.confidence >= 0.70

    def test_evaluate_test_gate_many_failures(self):
        """Verify test gate with many failing tests."""
        reset_unified_index()
        reset_decision_engine()
        reset_cicd_engine()

        engine = get_cicd_engine()

        results = [
            TestResult(test_id="t1", test_name="test_a", passed=False, duration_seconds=1.0),
            TestResult(test_id="t2", test_name="test_b", passed=False, duration_seconds=1.0),
            TestResult(test_id="t3", test_name="test_c", passed=True, duration_seconds=1.0),
        ]

        decision = engine.evaluate_test_gate("unit_tests", results)

        assert decision.should_pass is False  # 1/3 = 33%, too low
        assert decision.confidence <= 0.30

    def test_evaluate_performance_gate_all_pass(self):
        """Verify performance gate with all metrics passing."""
        reset_unified_index()
        reset_decision_engine()
        reset_cicd_engine()

        engine = get_cicd_engine()

        metrics = [
            PerformanceMetric(metric_name="response_time", value=50.0, threshold=100.0, unit="ms"),
            PerformanceMetric(metric_name="error_rate", value=0.01, threshold=0.05, unit="percent"),
        ]

        decision = engine.evaluate_performance_gate("performance_tests", metrics)

        assert decision.should_pass is True
        assert decision.confidence >= 0.85
        assert "All" in decision.reason

    def test_evaluate_performance_gate_some_failures(self):
        """Verify performance gate with some metrics failing."""
        reset_unified_index()
        reset_decision_engine()
        reset_cicd_engine()

        engine = get_cicd_engine()

        metrics = [
            PerformanceMetric(metric_name="response_time", value=150.0, threshold=100.0, unit="ms"),
            PerformanceMetric(metric_name="error_rate", value=0.01, threshold=0.05, unit="percent"),
        ]

        decision = engine.evaluate_performance_gate("performance_tests", metrics)

        # 1/2 = 50%, which is > 10%, so should fail
        assert decision.should_pass is False

    def test_regression_detection(self):
        """Verify regression detection evaluation."""
        reset_unified_index()
        reset_decision_engine()
        reset_cicd_engine()

        engine = get_cicd_engine()

        result = engine.evaluate_regression_detection(hours=24)

        assert "has_regression_trend" in result
        assert "trend" in result
        assert "anomalies" in result

    def test_gate_report_generation(self):
        """Verify gate report generation."""
        reset_unified_index()
        reset_decision_engine()
        reset_cicd_engine()

        engine = get_cicd_engine()

        # Create some gate decisions
        results = [
            TestResult(test_id="t1", test_name="test_a", passed=True, duration_seconds=1.0),
            TestResult(test_id="t2", test_name="test_b", passed=True, duration_seconds=1.0),
        ]
        engine.evaluate_test_gate("unit_tests", results)

        report = engine.get_gate_report()

        assert report["total_gates"] == 1
        assert report["passed_gates"] == 1
        assert report["failed_gates"] == 0
        assert len(report["gates"]) == 1

    def test_github_actions_export(self):
        """Verify GitHub Actions export."""
        reset_unified_index()
        reset_decision_engine()
        reset_cicd_engine()

        engine = get_cicd_engine()

        results = [
            TestResult(test_id="t1", test_name="test_a", passed=True, duration_seconds=1.0),
        ]
        engine.evaluate_test_gate("unit_tests", results)

        output = engine.export_github_actions_output()

        assert isinstance(output, str)
        assert "gates" in output
        assert "regressions" in output
        assert "threshold_adjustments" in output


class TestGateDecision:
    """Test gate decision data class."""

    def test_create_gate_decision(self):
        """Verify gate decision creation."""
        decision = GateDecision(
            check_name="unit_tests",
            should_pass=True,
            confidence=0.95,
            reason="All tests passed",
        )

        assert decision.check_name == "unit_tests"
        assert decision.should_pass is True
        assert decision.confidence == 0.95
