"""Continuous improvement loop orchestrator between repositories.

Drives iterative improvements between Swizzle and Ghost Tools.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
from pathlib import Path


class LoopStatus(str, Enum):
    """Status of the improvement loop."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CONVERGED = "converged"
    STALLED = "stalled"


@dataclass
class LoopIteration:
    """Record of one iteration in the improvement loop."""
    iteration_number: int
    sender_repo: str
    receiver_repo: str
    improvement_id: str
    accepted: bool
    net_improvement: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class LoopState:
    """State of the improvement loop."""
    status: LoopStatus
    iterations: List[LoopIteration]
    convergence_threshold: float = 0.01  # Stop when improvement < 1%
    max_iterations: int = 20
    current_iteration: int = 0
    total_improvement: float = 0.0
    converged: bool = False

    def should_continue(self) -> bool:
        """Determine if loop should continue."""
        if self.current_iteration >= self.max_iterations:
            return False

        if not self.iterations:
            return True

        # Check if recent improvements are diminishing
        if len(self.iterations) >= 3:
            recent = self.iterations[-3:]
            avg_recent = sum(i.net_improvement for i in recent) / len(recent)
            return abs(avg_recent) > self.convergence_threshold

        return True

    def mark_converged(self) -> None:
        """Mark loop as converged."""
        self.converged = True
        self.status = LoopStatus.CONVERGED


class LoopOrchestrator:
    """Orchestrates continuous improvement loop between repositories."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.loop_state = LoopState(
            status=LoopStatus.IDLE,
            iterations=[],
        )
        self.acceptance_history: Dict[str, float] = {}  # repo -> acceptance_rate
        self.load_state()

    def load_state(self) -> None:
        """Load previous loop state."""
        state_file = self.workspace / "loop_state.json"
        if state_file.exists():
            with open(state_file) as f:
                data = json.load(f)
                self.loop_state.status = LoopStatus(data["status"])
                self.loop_state.converged = data.get("converged", False)
                self.loop_state.current_iteration = data.get("current_iteration", 0)
                self.loop_state.total_improvement = data.get("total_improvement", 0.0)
                self.loop_state.iterations = [
                    LoopIteration(
                        iteration_number=i["iteration_number"],
                        sender_repo=i["sender_repo"],
                        receiver_repo=i["receiver_repo"],
                        improvement_id=i["improvement_id"],
                        accepted=i["accepted"],
                        net_improvement=i["net_improvement"],
                        timestamp=i["timestamp"],
                    )
                    for i in data.get("iterations", [])
                ]

    def save_state(self) -> None:
        """Save loop state to disk."""
        state_file = self.workspace / "loop_state.json"
        data = {
            "status": self.loop_state.status.value,
            "converged": self.loop_state.converged,
            "current_iteration": self.loop_state.current_iteration,
            "total_improvement": self.loop_state.total_improvement,
            "iterations": [
                {
                    "iteration_number": i.iteration_number,
                    "sender_repo": i.sender_repo,
                    "receiver_repo": i.receiver_repo,
                    "improvement_id": i.improvement_id,
                    "accepted": i.accepted,
                    "net_improvement": i.net_improvement,
                    "timestamp": i.timestamp,
                }
                for i in self.loop_state.iterations
            ],
        }
        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)

    def start_loop(self) -> None:
        """Start the improvement loop."""
        self.loop_state.status = LoopStatus.RUNNING
        self.loop_state.converged = False
        self.loop_state.current_iteration = 0
        self.save_state()

    def pause_loop(self) -> None:
        """Pause the improvement loop."""
        self.loop_state.status = LoopStatus.PAUSED
        self.save_state()

    def resume_loop(self) -> None:
        """Resume the improvement loop."""
        if self.loop_state.status == LoopStatus.PAUSED:
            self.loop_state.status = LoopStatus.RUNNING
            self.save_state()

    def record_iteration(
        self,
        sender_repo: str,
        receiver_repo: str,
        improvement_id: str,
        accepted: bool,
        net_improvement: float,
    ) -> None:
        """Record one iteration of the improvement loop."""
        iteration = LoopIteration(
            iteration_number=self.loop_state.current_iteration,
            sender_repo=sender_repo,
            receiver_repo=receiver_repo,
            improvement_id=improvement_id,
            accepted=accepted,
            net_improvement=net_improvement,
        )

        self.loop_state.iterations.append(iteration)
        self.loop_state.current_iteration += 1

        if accepted:
            self.loop_state.total_improvement += net_improvement

        # Check convergence
        if not self.loop_state.should_continue():
            self.loop_state.mark_converged()
            self.loop_state.status = LoopStatus.CONVERGED

        self.save_state()

    def get_loop_status(self) -> Dict[str, Any]:
        """Get current loop status."""
        accepted = sum(1 for i in self.loop_state.iterations if i.accepted)
        rejected = len(self.loop_state.iterations) - accepted

        return {
            "status": self.loop_state.status.value,
            "converged": self.loop_state.converged,
            "current_iteration": self.loop_state.current_iteration,
            "max_iterations": self.loop_state.max_iterations,
            "total_iterations": len(self.loop_state.iterations),
            "accepted_improvements": accepted,
            "rejected_improvements": rejected,
            "total_improvement": self.loop_state.total_improvement,
            "acceptance_rate": accepted / max(1, len(self.loop_state.iterations)),
            "last_iteration": {
                "sender": self.loop_state.iterations[-1].sender_repo if self.loop_state.iterations else None,
                "receiver": self.loop_state.iterations[-1].receiver_repo if self.loop_state.iterations else None,
                "accepted": self.loop_state.iterations[-1].accepted if self.loop_state.iterations else None,
                "improvement": self.loop_state.iterations[-1].net_improvement if self.loop_state.iterations else None,
            } if self.loop_state.iterations else {},
        }

    def get_loop_report(self) -> str:
        """Generate comprehensive loop report."""
        status = self.get_loop_status()

        report = f"""
╔════════════════════════════════════════════════════════════════╗
║        CONTINUOUS IMPROVEMENT LOOP STATUS REPORT              ║
╚════════════════════════════════════════════════════════════════╝

Loop Status: {status['status'].upper()}
Converged: {'✓ YES' if status['converged'] else '✗ NO'}

Iterations:
  • Total: {status['total_iterations']}/{status['max_iterations']}
  • Accepted: {status['accepted_improvements']}
  • Rejected: {status['rejected_improvements']}
  • Acceptance rate: {status['acceptance_rate']*100:.1f}%

Improvement:
  • Total cumulative: {status['total_improvement']*100:+.2f}%
  • Current iteration: {status['current_iteration']}

Last Iteration:
  • Sender: {status['last_iteration'].get('sender', 'N/A')}
  • Receiver: {status['last_iteration'].get('receiver', 'N/A')}
  • Accepted: {'✓' if status['last_iteration'].get('accepted') else '✗'}
  • Improvement: {status['last_iteration'].get('improvement', 0)*100:+.2f}%

Convergence Status:
  • Threshold: {self.loop_state.convergence_threshold*100:.2f}%
  • Should continue: {'YES' if self.loop_state.should_continue() else 'NO'}
"""
        return report
