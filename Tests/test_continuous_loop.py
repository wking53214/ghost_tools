"""Tests for continuous improvement loop and validation."""

import pytest
from pathlib import Path
import tempfile

from swizzle.integration.test_track import TestTrack, ExperimentStatus, Metric
from swizzle.integration.arbiter import Arbiter, ValidationMetric, ValidationVerdictType
from swizzle.integration.loop_orchestrator import LoopOrchestrator, LoopStatus


class TestTrackTests:
    """Test experiment tracking and validation."""

    def test_create_experiment(self):
        """Verify experiment creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            track = TestTrack(Path(tmpdir))

            exp_id = track.create_experiment("exp_001", "Test experiment")

            assert exp_id in track.experiments
            assert track.experiments[exp_id].status == ExperimentStatus.PENDING

    def test_record_experiment_run(self):
        """Verify recording experiment results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            track = TestTrack(Path(tmpdir))

            baseline = [
                Metric(name="accuracy", value=0.90, unit="percent"),
                Metric(name="latency", value=100.0, unit="ms"),
            ]

            experiment = [
                Metric(name="accuracy", value=0.95, unit="percent"),
                Metric(name="latency", value=80.0, unit="ms"),
            ]

            result = track.record_experiment_run("exp_001", baseline, experiment)

            assert result.status == ExperimentStatus.RUNNING
            assert result.improvements["accuracy"] == pytest.approx(5.56, rel=0.01)
            assert result.improvements["latency"] == pytest.approx(-20.0, rel=0.01)

    def test_evaluate_experiment_passed(self):
        """Verify experiment evaluation for positive result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            track = TestTrack(Path(tmpdir))

            baseline = [Metric(name="score", value=100.0, unit="points")]
            experiment = [Metric(name="score", value=110.0, unit="points")]

            track.record_experiment_run("exp_001", baseline, experiment)
            passed = track.evaluate_experiment("exp_001", threshold=0.0)

            assert passed is True
            assert track.experiments["exp_001"].status == ExperimentStatus.PASSED

    def test_evaluate_experiment_failed(self):
        """Verify experiment evaluation for negative result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            track = TestTrack(Path(tmpdir))

            baseline = [Metric(name="score", value=100.0, unit="points")]
            experiment = [Metric(name="score", value=95.0, unit="points")]

            track.record_experiment_run("exp_001", baseline, experiment)
            passed = track.evaluate_experiment("exp_001", threshold=0.0)

            assert passed is False
            assert track.experiments["exp_001"].status == ExperimentStatus.FAILED

    def test_promote_experiment(self):
        """Verify promoting passed experiment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            track = TestTrack(Path(tmpdir))

            baseline = [Metric(name="score", value=100.0, unit="points")]
            experiment = [Metric(name="score", value=110.0, unit="points")]

            track.record_experiment_run("exp_001", baseline, experiment)
            track.evaluate_experiment("exp_001")
            promoted = track.promote_experiment("exp_001")

            assert promoted is True
            assert track.experiments["exp_001"].status == ExperimentStatus.PROMOTED

    def test_net_improvement_calculation(self):
        """Verify net improvement calculation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            track = TestTrack(Path(tmpdir))

            baseline = [
                Metric(name="accuracy", value=0.90, unit="percent"),
                Metric(name="throughput", value=100.0, unit="req/s"),
            ]

            experiment = [
                Metric(name="accuracy", value=0.95, unit="percent"),
                Metric(name="throughput", value=110.0, unit="req/s"),
            ]

            result = track.record_experiment_run("exp_001", baseline, experiment)

            # accuracy improved 5.56%, throughput improved 10%
            # average = (5.56 + 10) / 2 = 7.78%
            assert result.net_improvement() > 0
            assert result.is_net_positive()


class TestArbiterTests:
    """Test validation and acceptance logic."""

    def test_arbiter_accept_improvement(self):
        """Verify accepting positive improvement."""
        arbiter = Arbiter("ghost_tools")
        arbiter.set_acceptance_threshold(0.0)

        metrics = [
            ValidationMetric(name="accuracy", before_value=0.90, after_value=0.95, unit="percent"),
        ]

        verdict = arbiter.validate_improvement("swizzle", "imp_001", metrics)

        assert verdict.verdict == ValidationVerdictType.ACCEPT
        assert verdict.confidence > 0.5

    def test_arbiter_reject_regression(self):
        """Verify rejecting regression."""
        arbiter = Arbiter("ghost_tools")
        arbiter.set_acceptance_threshold(0.0)

        metrics = [
            ValidationMetric(name="accuracy", before_value=0.95, after_value=0.90, unit="percent"),
        ]

        verdict = arbiter.validate_improvement("swizzle", "imp_001", metrics)

        assert verdict.verdict == ValidationVerdictType.REJECT

    def test_arbiter_critical_metric_rejection(self):
        """Verify rejecting when critical metric regresses."""
        arbiter = Arbiter("ghost_tools")
        arbiter.add_critical_metric("test_pass_rate")

        metrics = [
            ValidationMetric(name="test_pass_rate", before_value=1.0, after_value=0.95, unit="percent"),
            ValidationMetric(name="latency", before_value=100.0, after_value=90.0, unit="ms"),
        ]

        verdict = arbiter.validate_improvement("swizzle", "imp_001", metrics)

        assert verdict.verdict == ValidationVerdictType.REJECT
        assert "critical" in verdict.reason.lower()

    def test_arbiter_weighted_score(self):
        """Verify weighted scoring of improvements."""
        arbiter = Arbiter("ghost_tools")

        metrics = [
            ValidationMetric(name="accuracy", before_value=0.90, after_value=0.95, unit="percent", importance=2.0),
            ValidationMetric(name="latency", before_value=100.0, after_value=110.0, unit="ms", importance=1.0),
        ]

        verdict = arbiter.validate_improvement("swizzle", "imp_001", metrics)

        # accuracy improved 5.56%, latency regressed 10%
        # weighted = (5.56*2 + (-10)*1) / 3 = 0.37%
        assert verdict.weighted_score() > 0

    def test_arbiter_acceptance_rate(self):
        """Verify acceptance rate tracking."""
        arbiter = Arbiter("ghost_tools")

        metrics_good = [
            ValidationMetric(name="score", before_value=100.0, after_value=110.0, unit="points"),
        ]

        metrics_bad = [
            ValidationMetric(name="score", before_value=100.0, after_value=90.0, unit="points"),
        ]

        arbiter.validate_improvement("swizzle", "imp_001", metrics_good)
        arbiter.validate_improvement("swizzle", "imp_002", metrics_bad)

        rate = arbiter.get_acceptance_rate()
        assert rate == 0.5  # 1 accepted, 1 rejected


class TestLoopOrchestratorTests:
    """Test continuous improvement loop orchestration."""

    def test_loop_creation(self):
        """Verify loop orchestrator creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = LoopOrchestrator(Path(tmpdir))

            assert orchestrator.loop_state.status == LoopStatus.IDLE
            assert orchestrator.loop_state.current_iteration == 0

    def test_loop_start(self):
        """Verify starting the loop."""
        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = LoopOrchestrator(Path(tmpdir))
            orchestrator.start_loop()

            assert orchestrator.loop_state.status == LoopStatus.RUNNING

    def test_record_iteration(self):
        """Verify recording loop iterations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = LoopOrchestrator(Path(tmpdir))
            orchestrator.start_loop()

            orchestrator.record_iteration("swizzle", "ghost_tools", "imp_001", True, 0.05)

            assert len(orchestrator.loop_state.iterations) == 1
            assert orchestrator.loop_state.iterations[0].accepted is True
            assert orchestrator.loop_state.current_iteration == 1

    def test_convergence_detection(self):
        """Verify convergence detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = LoopOrchestrator(Path(tmpdir))
            orchestrator.start_loop()

            # Record many small improvements
            for i in range(25):
                orchestrator.record_iteration(
                    "swizzle" if i % 2 == 0 else "ghost_tools",
                    "ghost_tools" if i % 2 == 0 else "swizzle",
                    f"imp_{i:03d}",
                    True,
                    0.002,  # Very small improvement
                )

            assert orchestrator.loop_state.converged is True
            assert orchestrator.loop_state.status == LoopStatus.CONVERGED

    def test_loop_status_report(self):
        """Verify loop status reporting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = LoopOrchestrator(Path(tmpdir))
            orchestrator.start_loop()

            orchestrator.record_iteration("swizzle", "ghost_tools", "imp_001", True, 0.05)
            orchestrator.record_iteration("ghost_tools", "swizzle", "imp_002", False, 0.0)

            status = orchestrator.get_loop_status()

            assert status["total_iterations"] == 2
            assert status["accepted_improvements"] == 1
            assert status["rejected_improvements"] == 1
            assert status["acceptance_rate"] == 0.5

    def test_loop_pause_resume(self):
        """Verify pausing and resuming loop."""
        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = LoopOrchestrator(Path(tmpdir))
            orchestrator.start_loop()
            orchestrator.pause_loop()

            assert orchestrator.loop_state.status == LoopStatus.PAUSED

            orchestrator.resume_loop()
            assert orchestrator.loop_state.status == LoopStatus.RUNNING

    def test_total_improvement_tracking(self):
        """Verify total improvement accumulation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = LoopOrchestrator(Path(tmpdir))
            orchestrator.start_loop()

            orchestrator.record_iteration("swizzle", "ghost_tools", "imp_001", True, 0.05)
            orchestrator.record_iteration("ghost_tools", "swizzle", "imp_002", True, 0.03)
            orchestrator.record_iteration("swizzle", "ghost_tools", "imp_003", False, 0.02)

            # Only accepted improvements count
            assert orchestrator.loop_state.total_improvement == pytest.approx(0.08, rel=0.01)
