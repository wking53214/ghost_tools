"""Test track for experimental improvements before committing to main codebase.

Allows safe experimentation with rollback capability and A/B testing.
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
from pathlib import Path


class ExperimentStatus(str, Enum):
    """Status of an experiment."""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    PROMOTED = "promoted"


@dataclass
class Metric:
    """A measured metric from an experiment."""
    name: str
    value: float
    unit: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ExperimentResult:
    """Result of running an experiment."""
    experiment_id: str
    status: ExperimentStatus
    baseline_metrics: List[Metric]
    experiment_metrics: List[Metric]
    improvements: Dict[str, float]  # metric_name -> improvement_percent
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def net_improvement(self) -> float:
        """Calculate net improvement across all metrics."""
        if not self.improvements:
            return 0.0
        return sum(self.improvements.values()) / len(self.improvements)

    def is_net_positive(self) -> bool:
        """Check if experiment resulted in net improvement."""
        return self.net_improvement() > 0


class TestTrack:
    """Manages experimental features and rollback."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.experiments: Dict[str, ExperimentResult] = {}
        self.baseline_metrics: Dict[str, List[Metric]] = {}
        self.load_experiments()

    def load_experiments(self) -> None:
        """Load previous experiments from storage."""
        experiments_file = self.workspace / "experiments.json"
        if experiments_file.exists():
            with open(experiments_file) as f:
                data = json.load(f)
                for exp_id, result_dict in data.items():
                    # Reconstruct experiment results
                    self.experiments[exp_id] = ExperimentResult(
                        experiment_id=exp_id,
                        status=ExperimentStatus(result_dict["status"]),
                        baseline_metrics=[
                            Metric(**m) for m in result_dict.get("baseline_metrics", [])
                        ],
                        experiment_metrics=[
                            Metric(**m) for m in result_dict.get("experiment_metrics", [])
                        ],
                        improvements=result_dict.get("improvements", {}),
                        timestamp=result_dict.get("timestamp", datetime.now().isoformat()),
                    )

    def save_experiments(self) -> None:
        """Save experiments to storage."""
        experiments_file = self.workspace / "experiments.json"
        data = {}
        for exp_id, result in self.experiments.items():
            data[exp_id] = {
                "status": result.status.value,
                "baseline_metrics": [
                    {"name": m.name, "value": m.value, "unit": m.unit, "timestamp": m.timestamp}
                    for m in result.baseline_metrics
                ],
                "experiment_metrics": [
                    {"name": m.name, "value": m.value, "unit": m.unit, "timestamp": m.timestamp}
                    for m in result.experiment_metrics
                ],
                "improvements": result.improvements,
                "timestamp": result.timestamp,
            }
        with open(experiments_file, "w") as f:
            json.dump(data, f, indent=2)

    def record_baseline(self, metrics: List[Metric]) -> None:
        """Record baseline metrics before experiment."""
        metric_key = f"baseline_{datetime.now().isoformat()}"
        self.baseline_metrics[metric_key] = metrics

    def create_experiment(self, experiment_id: str, description: str) -> str:
        """Create a new experiment."""
        self.experiments[experiment_id] = ExperimentResult(
            experiment_id=experiment_id,
            status=ExperimentStatus.PENDING,
            baseline_metrics=[],
            experiment_metrics=[],
            improvements={},
        )
        return experiment_id

    def record_experiment_run(
        self,
        experiment_id: str,
        baseline_metrics: List[Metric],
        experiment_metrics: List[Metric],
    ) -> ExperimentResult:
        """Record the results of running an experiment."""
        if experiment_id not in self.experiments:
            self.create_experiment(experiment_id, "Auto-created experiment")

        # Calculate improvements
        improvements = {}
        for baseline, experiment in zip(baseline_metrics, experiment_metrics):
            if baseline.name == experiment.name:
                if baseline.value == 0:
                    improvement = 0.0
                else:
                    improvement = ((experiment.value - baseline.value) / baseline.value) * 100

                improvements[baseline.name] = improvement

        result = ExperimentResult(
            experiment_id=experiment_id,
            status=ExperimentStatus.RUNNING,
            baseline_metrics=baseline_metrics,
            experiment_metrics=experiment_metrics,
            improvements=improvements,
        )

        self.experiments[experiment_id] = result
        self.save_experiments()
        return result

    def evaluate_experiment(self, experiment_id: str, threshold: float = 0.0) -> bool:
        """Evaluate if experiment passed threshold."""
        if experiment_id not in self.experiments:
            return False

        result = self.experiments[experiment_id]
        net_improvement = result.net_improvement()

        if net_improvement >= threshold:
            result.status = ExperimentStatus.PASSED
            return True
        else:
            result.status = ExperimentStatus.FAILED
            return False

    def promote_experiment(self, experiment_id: str) -> bool:
        """Promote experiment to main codebase."""
        if experiment_id not in self.experiments:
            return False

        result = self.experiments[experiment_id]
        if result.status == ExperimentStatus.PASSED:
            result.status = ExperimentStatus.PROMOTED
            self.save_experiments()
            return True

        return False

    def rollback_experiment(self, experiment_id: str) -> bool:
        """Rollback an experiment."""
        if experiment_id not in self.experiments:
            return False

        result = self.experiments[experiment_id]
        result.status = ExperimentStatus.ROLLED_BACK
        self.save_experiments()
        return True

    def get_passed_experiments(self) -> List[ExperimentResult]:
        """Get all passed experiments."""
        return [
            r for r in self.experiments.values()
            if r.status == ExperimentStatus.PASSED
        ]

    def get_experiment_history(self) -> Dict[str, Any]:
        """Get complete experiment history."""
        return {
            "total_experiments": len(self.experiments),
            "passed": len([e for e in self.experiments.values() if e.status == ExperimentStatus.PASSED]),
            "failed": len([e for e in self.experiments.values() if e.status == ExperimentStatus.FAILED]),
            "promoted": len([e for e in self.experiments.values() if e.status == ExperimentStatus.PROMOTED]),
            "experiments": {
                exp_id: {
                    "status": result.status.value,
                    "net_improvement": result.net_improvement(),
                    "improvements": result.improvements,
                }
                for exp_id, result in self.experiments.items()
            },
        }
