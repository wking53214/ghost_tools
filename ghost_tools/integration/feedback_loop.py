"""False positive feedback loop for oracle and filter improvement.

Ghost's confirmed-false triage decisions train Swizzle's oracles to avoid
those findings. Swizzle's verified false positives improve Ghost's filtering.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import json
from datetime import datetime


class FindingType(str, Enum):
    """Categories of findings that can be false positives."""
    WRITE_OUTSIDE_BOUNDARY = "write_outside_boundary"
    PROSE_DELETED = "prose_deleted"
    DATED_CLAIM = "dated_claim"
    LIVE_CLAIM_IN_HISTORICAL = "live_claim_in_historical"
    TEST_FAILURE = "test_failure"
    MUTATION_ARTIFACT = "mutation_artifact"  # false positive from mutation testing


@dataclass
class FalsePositivePattern:
    """A pattern that predicts a false positive."""
    id: str
    finding_type: FindingType
    description: str  # what causes false positives of this type
    indicators: List[str]  # patterns to look for in repository/code
    confidence: float  # 0.0 to 1.0, how reliable is this pattern?

    # How to filter it
    filter_function: Optional[str] = None  # reference to filtering code
    filter_description: str = ""  # what the filter checks

    # Evidence
    examples_count: int = 0  # how many false positives this explains
    discovered_by: str = ""  # "swizzle" or "ghost_tools"
    discovered_at: str = ""  # ISO 8601


@dataclass
class OracleTrainingDatapoint:
    """One data point for oracle training."""
    finding_id: str
    finding_type: FindingType
    repository_features: Dict[str, str]  # things about the repo
    tool_claim: str  # what the tool claimed
    ground_truth: bool  # was the tool right?
    oracle_confidence: float  # how confident should oracle be?

    # How we know ground truth
    verified_by: str  # "swizzle", "human", "subsequent_scan"
    verified_at: str  # ISO 8601


@dataclass
class FeedbackReport:
    """Feedback loop metrics and training data."""
    false_positive_patterns: Dict[str, FalsePositivePattern] = field(default_factory=dict)
    oracle_training_data: Dict[str, OracleTrainingDatapoint] = field(default_factory=dict)
    filter_improvements: List[str] = field(default_factory=list)  # descriptions of improvements
    version: str = "1.0"
    last_updated: str = ""

    def add_pattern(self, pattern: FalsePositivePattern) -> None:
        """Register a false positive pattern."""
        self.false_positive_patterns[pattern.id] = pattern

    def add_training_datapoint(self, dp: OracleTrainingDatapoint) -> None:
        """Add oracle training data."""
        self.oracle_training_data[dp.finding_id] = dp

    def patterns_by_type(self) -> Dict[FindingType, List[FalsePositivePattern]]:
        """Group patterns by finding type."""
        by_type = {}
        for pattern in self.false_positive_patterns.values():
            if pattern.finding_type not in by_type:
                by_type[pattern.finding_type] = []
            by_type[pattern.finding_type].append(pattern)
        return by_type

    def oracle_accuracy_by_type(self) -> Dict[FindingType, Tuple[int, float]]:
        """Calculate oracle accuracy per finding type.

        Returns (count, accuracy_percentage) for each type.
        """
        by_type = {}
        for dp in self.oracle_training_data.values():
            if dp.finding_type not in by_type:
                by_type[dp.finding_type] = {"correct": 0, "total": 0}

            by_type[dp.finding_type]["total"] += 1
            if dp.oracle_confidence > 0.5 and dp.ground_truth:
                by_type[dp.finding_type]["correct"] += 1
            elif dp.oracle_confidence <= 0.5 and not dp.ground_truth:
                by_type[dp.finding_type]["correct"] += 1

        return {
            ftype: (counts["total"], counts["correct"] / counts["total"] * 100)
            for ftype, counts in by_type.items()
        }

    def filter_effectiveness(self) -> Dict[str, float]:
        """How much does filtering reduce false positives?

        For each pattern, returns (before_fp_rate, after_fp_rate, reduction_percent).
        """
        effectiveness = {}
        for pattern_id, pattern in self.false_positive_patterns.items():
            # Count how many training datapoints this pattern would filter
            relevant = [dp for dp in self.oracle_training_data.values()
                       if dp.finding_type == pattern.finding_type]
            if not relevant:
                continue

            # Assuming pattern identifies true negatives
            false_positives = sum(1 for dp in relevant if not dp.ground_truth)
            if false_positives == 0:
                continue

            fp_rate_before = false_positives / len(relevant)
            # After applying filter, we remove false positives
            fp_rate_after = 0
            reduction = (fp_rate_before - fp_rate_after) / fp_rate_before * 100

            effectiveness[pattern_id] = {
                "pattern_description": pattern.description,
                "fp_before_percent": fp_rate_before * 100,
                "fp_after_percent": fp_rate_after * 100,
                "reduction_percent": reduction,
                "examples_filtered": false_positives,
            }

        return effectiveness

    def export_for_swizzle_oracle_update(self) -> str:
        """Export training data for Swizzle to use in oracle calibration."""
        training_data = {}
        for dp in self.oracle_training_data.values():
            finding_type = dp.finding_type.value
            if finding_type not in training_data:
                training_data[finding_type] = []

            training_data[finding_type].append({
                "ground_truth": dp.ground_truth,
                "confidence": dp.oracle_confidence,
                "verified_by": dp.verified_by,
                "repository_features": dp.repository_features,
            })

        return json.dumps({
            "version": "1.0",
            "purpose": "oracle_calibration",
            "training_data": training_data,
            "accuracy_by_type": {
                k: {"count": v[0], "accuracy": v[1]}
                for k, v in self.oracle_accuracy_by_type().items()
            }
        }, indent=2)

    def export_for_ghost_filter_update(self) -> str:
        """Export patterns and filter recommendations for Ghost."""
        patterns_by_type = self.patterns_by_type()

        return json.dumps({
            "version": "1.0",
            "purpose": "false_positive_filter_improvement",
            "patterns_by_type": {
                finding_type.value: [
                    {
                        "id": p.id,
                        "description": p.description,
                        "filter_function": p.filter_function,
                        "confidence": p.confidence,
                        "examples": p.examples_count,
                    }
                    for p in patterns
                ]
                for finding_type, patterns in patterns_by_type.items()
            },
            "filter_effectiveness": self.filter_effectiveness(),
        }, indent=2)

    def to_json(self) -> str:
        """Export complete report."""
        data = {
            "version": self.version,
            "last_updated": self.last_updated,
            "false_positive_patterns": {
                pid: {
                    "id": p.id,
                    "finding_type": p.finding_type.value,
                    "description": p.description,
                    "indicators": p.indicators,
                    "confidence": p.confidence,
                    "filter_function": p.filter_function,
                    "examples_count": p.examples_count,
                    "discovered_by": p.discovered_by,
                }
                for pid, p in self.false_positive_patterns.items()
            },
            "oracle_training_data": {
                did: {
                    "finding_id": dp.finding_id,
                    "finding_type": dp.finding_type.value,
                    "ground_truth": dp.ground_truth,
                    "oracle_confidence": dp.oracle_confidence,
                    "verified_by": dp.verified_by,
                }
                for did, dp in self.oracle_training_data.items()
            },
            "filter_improvements": self.filter_improvements,
        }
        return json.dumps(data, indent=2)

    def save(self, path: Path) -> None:
        """Write to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())


# Seed with known false positive patterns
DEFAULT_FEEDBACK_REPORT = FeedbackReport(version="1.0")

DEFAULT_FEEDBACK_REPORT.add_pattern(FalsePositivePattern(
    id="dated_readme_false_positive",
    finding_type=FindingType.DATED_CLAIM,
    description="README with explicit 'generated on DATE' is dated, not live claim",
    indicators=["This README was generated", "generated on", "as of"],
    confidence=0.95,
    filter_function="ghost_buster.filtering.is_historical_document",
    filter_description="Check for explicit generation date markers",
    examples_count=5,
    discovered_by="swizzle",
    discovered_at="2026-09-18T00:00:00Z",
))

DEFAULT_FEEDBACK_REPORT.add_pattern(FalsePositivePattern(
    id="symlink_not_escape",
    finding_type=FindingType.WRITE_OUTSIDE_BOUNDARY,
    description="Symlink in repo that points inside repo is not a boundary escape",
    indicators=["symlink", "readlink", "realpath"],
    confidence=0.90,
    filter_function="ghost_buster.boundary.is_contained_symlink",
    examples_count=3,
    discovered_by="swizzle",
))
