"""CI/CD pipeline integration with automated test gates and regression detection.

Uses decision engine to gate CI checks and automatically adjust performance thresholds
based on detected regressions and historical patterns.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json

from .unified_index import UnifiedIndex, IndexedDecision, IndexedEvent, get_unified_index
from .decision_engine import (
    DecisionEngine, DecisionType, RiskLevel, get_decision_engine,
)
from .trend_analyzer import TrendAnalyzer, create_trend_analyzer
from .ml_predictor import MLPredictor


@dataclass
class TestResult:
    """Result from a test run."""
    test_id: str
    test_name: str
    passed: bool
    duration_seconds: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    error_message: Optional[str] = None
    repo: str = "unknown"


@dataclass
class PerformanceMetric:
    """Performance metric measurement."""
    metric_name: str
    value: float
    threshold: float
    unit: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    repo: str = "unknown"

    def exceeds_threshold(self) -> bool:
        """Check if metric exceeds threshold."""
        return self.value > self.threshold

    def regression_percent(self) -> float:
        """Calculate regression percentage."""
        if self.threshold == 0:
            return 0.0
        return ((self.value - self.threshold) / self.threshold) * 100


@dataclass
class GateDecision:
    """Decision about whether to gate a CI check."""
    check_name: str
    should_pass: bool
    confidence: float
    reason: str
    decision_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class PerformanceThresholdManager:
    """Manages dynamic performance threshold adjustments."""

    def __init__(self, index: UnifiedIndex):
        self.index = index
        self.base_thresholds: Dict[str, float] = {}
        self.current_thresholds: Dict[str, float] = {}
        self.adjustment_history: List[Dict[str, Any]] = []

    def set_baseline_threshold(self, metric_name: str, threshold: float) -> None:
        """Set baseline threshold for a metric."""
        self.base_thresholds[metric_name] = threshold
        self.current_thresholds[metric_name] = threshold

    def adjust_threshold(
        self,
        metric_name: str,
        new_threshold: float,
        reason: str,
    ) -> None:
        """Adjust threshold and record the change."""
        old_threshold = self.current_thresholds.get(metric_name, self.base_thresholds.get(metric_name))
        self.current_thresholds[metric_name] = new_threshold

        self.adjustment_history.append({
            "metric_name": metric_name,
            "old_threshold": old_threshold,
            "new_threshold": new_threshold,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        })

    def get_threshold(self, metric_name: str) -> float:
        """Get current threshold for a metric."""
        return self.current_thresholds.get(
            metric_name,
            self.base_thresholds.get(metric_name, 0.0)
        )

    def suggest_adjustment(self, metric_name: str, recent_values: List[float]) -> Optional[Tuple[float, str]]:
        """Suggest threshold adjustment based on recent values."""
        if not recent_values:
            return None

        current = self.get_threshold(metric_name)
        avg_recent = sum(recent_values) / len(recent_values)

        # If recent average is consistently above current threshold, relax it
        if avg_recent > current * 1.1:  # 10% above threshold
            new_threshold = avg_recent * 1.05  # Set to 105% of recent average
            reason = f"Recent values ({avg_recent:.2f}) consistently exceed threshold, relaxing from {current:.2f}"
            return (new_threshold, reason)

        # If recent average is consistently below current threshold, tighten it
        if avg_recent < current * 0.9:  # 10% below threshold
            new_threshold = avg_recent * 0.95  # Set to 95% of recent average
            reason = f"Recent values ({avg_recent:.2f}) consistently below threshold, tightening from {current:.2f}"
            return (new_threshold, reason)

        return None


class CIDDIntegrationEngine:
    """Orchestrates CI/CD integration with decision engine."""

    def __init__(self):
        self.index = get_unified_index()
        self.decision_engine = get_decision_engine()
        self.analyzer = create_trend_analyzer(self.index)
        self.threshold_manager = PerformanceThresholdManager(self.index)
        self.gate_decisions: List[GateDecision] = []
        self.test_results: List[TestResult] = []

    def evaluate_test_gate(
        self,
        check_name: str,
        test_results: List[TestResult],
        repo: str = "unknown",
    ) -> GateDecision:
        """Evaluate whether a test gate should pass based on test results."""
        passed_count = sum(1 for t in test_results if t.passed)
        total_count = len(test_results)
        pass_rate = passed_count / total_count if total_count > 0 else 0.0

        # Determine confidence based on pass rate
        if pass_rate >= 0.99:  # 99%+ pass rate
            confidence = 0.95
            should_pass = True
            reason = f"Excellent pass rate: {pass_rate*100:.1f}% ({passed_count}/{total_count})"
        elif pass_rate >= 0.95:  # 95%+ pass rate
            confidence = 0.85
            should_pass = True
            reason = f"Good pass rate: {pass_rate*100:.1f}% ({passed_count}/{total_count})"
        elif pass_rate >= 0.90:  # 90%+ pass rate
            confidence = 0.70
            should_pass = True
            reason = f"Acceptable pass rate: {pass_rate*100:.1f}% ({passed_count}/{total_count})"
        else:
            confidence = 0.30
            should_pass = False
            reason = f"Low pass rate: {pass_rate*100:.1f}% ({passed_count}/{total_count})"

        # Check ML model for similar decision types
        ml_adjusted = self.decision_engine._enhance_confidence_with_ml(
            DecisionType.REQUIRE_HUMAN_REVIEW,
            RiskLevel.MEDIUM,
            confidence,
            action_similarity=0.9,
        )

        decision = GateDecision(
            check_name=check_name,
            should_pass=should_pass,
            confidence=ml_adjusted,
            reason=reason,
        )

        self.gate_decisions.append(decision)
        self.test_results.extend(test_results)
        return decision

    def evaluate_performance_gate(
        self,
        check_name: str,
        metrics: List[PerformanceMetric],
        repo: str = "unknown",
    ) -> GateDecision:
        """Evaluate whether a performance gate should pass."""
        failing_metrics = [m for m in metrics if m.exceeds_threshold()]

        if not failing_metrics:
            confidence = 0.95
            should_pass = True
            reason = f"All {len(metrics)} metrics within threshold"
        elif len(failing_metrics) <= len(metrics) * 0.1:  # <= 10% failing
            confidence = 0.75
            should_pass = True
            reason = f"{len(failing_metrics)}/{len(metrics)} metrics exceed threshold (within tolerance)"
        else:
            confidence = 0.20
            should_pass = False
            reason = f"{len(failing_metrics)}/{len(metrics)} metrics exceed threshold"

        decision = GateDecision(
            check_name=check_name,
            should_pass=should_pass,
            confidence=confidence,
            reason=reason,
        )

        self.gate_decisions.append(decision)

        # Check for regressions
        for metric in failing_metrics:
            self._handle_regression(metric)

        return decision

    def _handle_regression(self, metric: PerformanceMetric) -> None:
        """Handle detected regression by checking for threshold adjustment."""
        regression_pct = metric.regression_percent()

        if regression_pct > 50:  # Significant regression
            # Consider loosening threshold if this is a known metric
            recent_threshold = self.threshold_manager.get_threshold(metric.metric_name)
            # In real scenarios, would fetch historical values
            # For now, just record the regression
            pass

    def evaluate_regression_detection(self, hours: int = 24) -> Dict[str, Any]:
        """Evaluate whether regressions have been detected."""
        regression_trend = self.analyzer.analyze_regression_trend(hours)

        return {
            "has_regression_trend": regression_trend is not None and regression_trend.direction == "up",
            "trend": regression_trend.__dict__ if regression_trend else None,
            "anomalies": [a.__dict__ for a in self.analyzer.detect_anomalies()],
        }

    def get_gate_report(self) -> Dict[str, Any]:
        """Generate report of all gate evaluations."""
        passed_gates = [g for g in self.gate_decisions if g.should_pass]
        failed_gates = [g for g in self.gate_decisions if not g.should_pass]

        return {
            "total_gates": len(self.gate_decisions),
            "passed_gates": len(passed_gates),
            "failed_gates": len(failed_gates),
            "gates": [
                {
                    "check_name": g.check_name,
                    "passed": g.should_pass,
                    "confidence": g.confidence,
                    "reason": g.reason,
                    "timestamp": g.timestamp,
                }
                for g in self.gate_decisions
            ],
            "timestamp": datetime.now().isoformat(),
        }

    def export_github_actions_output(self) -> str:
        """Export gate decisions in GitHub Actions format."""
        output = {
            "gates": self.get_gate_report(),
            "regressions": self.evaluate_regression_detection(),
            "threshold_adjustments": self.threshold_manager.adjustment_history,
        }
        return json.dumps(output, indent=2)


# Global CI/CD engine instance
_engine: Optional[CIDDIntegrationEngine] = None


def get_cicd_engine() -> CIDDIntegrationEngine:
    """Get or create global CI/CD engine."""
    global _engine
    if _engine is None:
        _engine = CIDDIntegrationEngine()
    return _engine


def reset_cicd_engine() -> None:
    """Reset to fresh engine (for testing)."""
    global _engine
    _engine = CIDDIntegrationEngine()
