"""Arbitration system for validating improvements from other repositories.

Acts as referee: accepts or rejects improvements based on validation.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ValidationVerdictType(str, Enum):
    """Verdict on a proposed improvement."""
    ACCEPT = "accept"
    REJECT = "reject"
    NEEDS_REVIEW = "needs_review"
    CONDITIONAL = "conditional"


@dataclass
class ValidationMetric:
    """Metric used for validation."""
    name: str
    before_value: float
    after_value: float
    unit: str
    importance: float = 1.0  # Weight in overall decision (0-1)

    def improved(self) -> bool:
        """Check if metric improved."""
        return self.after_value > self.before_value

    def regression_percent(self) -> float:
        """Calculate improvement/regression percentage."""
        if self.before_value == 0:
            return 0.0
        return ((self.after_value - self.before_value) / self.before_value) * 100


@dataclass
class ValidationVerdict:
    """Decision on whether to accept an improvement."""
    source_repo: str
    target_repo: str
    improvement_id: str
    verdict: ValidationVerdictType
    confidence: float
    reason: str
    metrics: List[ValidationMetric]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def weighted_score(self) -> float:
        """Calculate weighted improvement score."""
        total_weight = sum(m.importance for m in self.metrics)
        if total_weight == 0:
            return 0.0

        weighted_sum = sum(
            (m.regression_percent() / 100.0) * m.importance
            for m in self.metrics
        )
        return weighted_sum / total_weight

    def should_accept(self, threshold: float = 0.0) -> bool:
        """Determine if verdict should be accept based on score."""
        if self.verdict == ValidationVerdictType.ACCEPT:
            return True
        if self.verdict == ValidationVerdictType.REJECT:
            return False
        if self.verdict == ValidationVerdictType.CONDITIONAL:
            return self.weighted_score() >= threshold
        return False


class Arbiter:
    """Validates improvements between repositories."""

    def __init__(self, repo_name: str):
        self.repo_name = repo_name
        self.verdicts: Dict[str, ValidationVerdict] = {}
        self.acceptance_threshold = 0.0  # Min weighted score to accept
        self.critical_metrics = set()  # Metrics that must improve
        self.acceptance_rate = 0.0

    def set_acceptance_threshold(self, threshold: float) -> None:
        """Set minimum improvement threshold for acceptance."""
        self.acceptance_threshold = threshold

    def add_critical_metric(self, metric_name: str) -> None:
        """Mark a metric as critical (must not regress)."""
        self.critical_metrics.add(metric_name)

    def validate_improvement(
        self,
        source_repo: str,
        improvement_id: str,
        metrics: List[ValidationMetric],
    ) -> ValidationVerdict:
        """Validate an improvement from another repo."""

        # Check critical metrics
        critical_regressions = [
            m for m in metrics
            if m.name in self.critical_metrics and not m.improved()
        ]

        if critical_regressions:
            verdict = ValidationVerdict(
                source_repo=source_repo,
                target_repo=self.repo_name,
                improvement_id=improvement_id,
                verdict=ValidationVerdictType.REJECT,
                confidence=0.95,
                reason=f"Critical metrics regressed: {[m.name for m in critical_regressions]}",
                metrics=metrics,
            )
            self.verdicts[improvement_id] = verdict
            return verdict

        # Calculate weighted score
        total_weight = sum(m.importance for m in metrics)
        if total_weight > 0:
            weighted_score = sum(
                (m.regression_percent() / 100.0) * m.importance
                for m in metrics
            ) / total_weight
        else:
            weighted_score = 0.0

        # Determine verdict
        if weighted_score >= self.acceptance_threshold:
            verdict_type = ValidationVerdictType.ACCEPT
            reason = f"Net improvement of {weighted_score*100:.1f}%"
            confidence = min(0.99, 0.5 + weighted_score)
        elif weighted_score >= self.acceptance_threshold * 0.5:
            verdict_type = ValidationVerdictType.CONDITIONAL
            reason = f"Marginal improvement of {weighted_score*100:.1f}%, needs review"
            confidence = 0.7
        else:
            verdict_type = ValidationVerdictType.REJECT
            reason = f"No improvement or regression of {weighted_score*100:.1f}%"
            confidence = 0.9

        verdict = ValidationVerdict(
            source_repo=source_repo,
            target_repo=self.repo_name,
            improvement_id=improvement_id,
            verdict=verdict_type,
            confidence=confidence,
            reason=reason,
            metrics=metrics,
        )

        self.verdicts[improvement_id] = verdict
        return verdict

    def get_acceptance_rate(self) -> float:
        """Calculate acceptance rate for improvements."""
        if not self.verdicts:
            return 0.0

        accepted = sum(
            1 for v in self.verdicts.values()
            if v.verdict == ValidationVerdictType.ACCEPT
        )
        return accepted / len(self.verdicts)

    def get_validation_report(self) -> Dict[str, Any]:
        """Generate validation report."""
        accepted = [v for v in self.verdicts.values() if v.verdict == ValidationVerdictType.ACCEPT]
        rejected = [v for v in self.verdicts.values() if v.verdict == ValidationVerdictType.REJECT]
        conditional = [v for v in self.verdicts.values() if v.verdict == ValidationVerdictType.CONDITIONAL]

        return {
            "repo": self.repo_name,
            "total_validations": len(self.verdicts),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "conditional": len(conditional),
            "acceptance_rate": self.get_acceptance_rate(),
            "verdicts": {
                improvement_id: {
                    "verdict": v.verdict.value,
                    "confidence": v.confidence,
                    "reason": v.reason,
                    "weighted_score": v.weighted_score(),
                }
                for improvement_id, v in self.verdicts.items()
            },
        }
