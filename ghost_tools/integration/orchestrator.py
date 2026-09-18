"""Integration orchestrator for Swizzle and Ghost Tools.

Coordinates data flow between the two tools using the shared models.
Now with event-driven streaming via the event bus for real-time feedback.
"""

from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import json

from .invariant_model import DEFAULT_INVARIANTS
from .triage_ledger import TriageLedger
from .mutation_transfer import DEFAULT_MUTATION_CATALOG
from .performance_contract import DEFAULT_PERFORMANCE_REPORT
from .architecture_audit import SWIZZLE_AUDIT, GHOST_AUDIT
from .feedback_loop import DEFAULT_FEEDBACK_REPORT
from .event_system import get_event_bus, Event, EventType
from .event_handlers import setup_event_handlers
from .hooks import HookManager
from .decision_engine import get_decision_engine
from .decision_handlers import setup_decision_handlers
from .event_evaluator import setup_event_evaluation, get_event_evaluator


class IntegrationOrchestrator:
    """Coordinates all integration bridges between Swizzle and Ghost Tools.

    Supports both batch and streaming modes:
    - Batch: export_all() generates static bundles for import
    - Streaming: event bus publishes real-time events as changes occur
    """

    def __init__(self, workspace_dir: Path, repo_path: Optional[Path] = None):
        self.workspace = workspace_dir
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.repo_path = repo_path

        # Load or initialize all shared models
        self.invariants = DEFAULT_INVARIANTS
        self.mutations = DEFAULT_MUTATION_CATALOG
        self.performance = DEFAULT_PERFORMANCE_REPORT
        self.swizzle_architecture = SWIZZLE_AUDIT
        self.ghost_architecture = GHOST_AUDIT
        self.feedback = DEFAULT_FEEDBACK_REPORT
        self.triage_ledger: Optional[TriageLedger] = None

        # Event bus for streaming mode
        self.event_bus = get_event_bus()
        setup_event_handlers()

        # Decision engine for autonomous decisions
        self.decision_engine = get_decision_engine()
        setup_decision_handlers()
        setup_event_evaluation()

        # Event evaluator for stats
        self.event_evaluator = get_event_evaluator()

        # Hook manager for post-commit events
        self.hook_manager: Optional[HookManager] = None
        if repo_path:
            self.hook_manager = HookManager(repo_path)
            self.install_hooks()

    def export_all(self) -> None:
        """Export all integration data to disk."""
        self.invariants.save(self.workspace / "invariants.json")
        self.mutations.save(self.workspace / "mutations.json")
        self.performance.save(self.workspace / "performance.json")
        self.swizzle_architecture.save(self.workspace / "swizzle-architecture.json")
        self.ghost_architecture.save(self.workspace / "ghost-architecture.json")
        self.feedback.save(self.workspace / "feedback.json")
        if self.triage_ledger:
            self.triage_ledger.save(self.workspace / "triage-ledger.json")

    def import_ghost_casefile(self, casefile_path: Path) -> None:
        """Import Ghost's triage casefile as training data."""
        from .triage_ledger import import_ghost_casefile
        self.triage_ledger = import_ghost_casefile(casefile_path)
        self.triage_ledger.save(self.workspace / "triage-ledger-from-ghost.json")

    def generate_ghost_integration_bundle(self) -> Dict[str, str]:
        """Generate all data Ghost Tools should consume.

        Returns mapping of file_name -> json_content.
        """
        bundle = {
            "invariants.json": self.invariants.to_json(),
            "mutations.json": self.mutations.to_json(),
            "performance-contracts.json": self.performance.to_json(),
            "feedback-patterns.json": self.feedback.export_for_ghost_filter_update(),
            "architecture-rules.json": self.ghost_architecture.to_json(),
        }
        return bundle

    def generate_swizzle_integration_bundle(self) -> Dict[str, str]:
        """Generate all data Swizzle should consume.

        Returns mapping of file_name -> json_content.
        """
        bundle = {
            "invariants.json": self.invariants.to_json(),
            "mutations.json": self.mutations.to_json(),
            "performance-contracts.json": self.performance.to_json(),
            "oracle-training-data.json": self.feedback.export_for_swizzle_oracle_update(),
            "architecture-rules.json": self.swizzle_architecture.to_json(),
        }
        if self.triage_ledger:
            bundle["triage-training-data.json"] = self.triage_ledger.export_for_swizzle_oracle_training()
        return bundle

    def publish_ghost_integration_bundle(self, target_dir: Path) -> None:
        """Write Ghost integration bundle to target directory."""
        target_dir.mkdir(parents=True, exist_ok=True)
        bundle = self.generate_ghost_integration_bundle()
        for filename, content in bundle.items():
            (target_dir / filename).write_text(content)

    def publish_swizzle_integration_bundle(self, target_dir: Path) -> None:
        """Write Swizzle integration bundle to target directory."""
        target_dir.mkdir(parents=True, exist_ok=True)
        bundle = self.generate_swizzle_integration_bundle()
        for filename, content in bundle.items():
            (target_dir / filename).write_text(content)

    def install_hooks(self) -> None:
        """Install git hooks for real-time event triggering."""
        if self.hook_manager:
            self.hook_manager.install_hooks()

    def publish_event(self, event: Event) -> None:
        """Publish an event to the event bus."""
        self.event_bus.publish(event)

    def get_unprocessed_events(self, event_type: Optional[EventType] = None) -> List[Event]:
        """Get events that haven't been processed yet."""
        return self.event_bus.get_unprocessed(event_type)

    def save_event_log(self) -> None:
        """Persist event log to disk."""
        self.event_bus.save_log(self.workspace / "event-log.json")

    def load_event_log(self) -> None:
        """Load event log from disk."""
        self.event_bus.load_log(self.workspace / "event-log.json")

    def get_pending_decisions(self):
        """Get decisions pending human review."""
        return self.decision_engine.pending_review()

    def approve_decision(self, decision_id: str, approved_by: str, reason: Optional[str] = None) -> bool:
        """Approve a pending decision."""
        return self.decision_engine.approve_decision(decision_id, approved_by, reason)

    def reject_decision(self, decision_id: str, rejected_by: str, reason: str) -> bool:
        """Reject a pending decision."""
        return self.decision_engine.reject_decision(decision_id, rejected_by, reason)

    def generate_integration_report(self) -> str:
        """Generate a report of all integration capabilities."""
        report = {
            "title": "Swizzle-Ghost Tools Integration Report",
            "generated": datetime.now().isoformat(),
            "capabilities": {
                "invariant_model": {
                    "description": "Shared invariant schema for both tools",
                    "count": len(self.invariants.invariants),
                    "invariants": list(self.invariants.invariants.keys()),
                },
                "mutation_transfer": {
                    "description": "Adversarial cases shared as mutation tests",
                    "count": len(self.mutations.cases),
                    "cases": list(self.mutations.cases.keys()),
                },
                "triage_ledger": {
                    "description": "Triage decisions as shared learning data",
                    "entries": len(self.triage_ledger.entries) if self.triage_ledger else 0,
                },
                "performance_contracts": {
                    "description": "Performance regression detection",
                    "contracts": len(self.performance.contracts),
                    "contract_ids": list(self.performance.contracts.keys()),
                },
                "architecture_audit": {
                    "description": "Cross-tool architecture validation",
                    "swizzle_boundaries": len(self.swizzle_architecture.boundaries),
                    "ghost_boundaries": len(self.ghost_architecture.boundaries),
                },
                "feedback_loop": {
                    "description": "False positive and oracle training data",
                    "patterns": len(self.feedback.false_positive_patterns),
                    "training_datapoints": len(self.feedback.oracle_training_data),
                },
                "event_system": {
                    "description": "Real-time event streaming",
                    "events_published": len(self.event_bus.event_log),
                    "events_processed": len([e for e in self.event_bus.event_log if e.processed]),
                    "hooks_installed": self.hook_manager is not None,
                },
                "decision_engine": {
                    "description": "Autonomous decision-making",
                    "status": "active",
                    **self.decision_engine.get_execution_report(),
                },
            },
            "files_generated": [
                "invariants.json",
                "mutations.json",
                "performance.json",
                "swizzle-architecture.json",
                "ghost-architecture.json",
                "feedback.json",
                "event-log.json",
                "triage-ledger.json" if self.triage_ledger else None,
            ],
        }
        return json.dumps(report, indent=2)
