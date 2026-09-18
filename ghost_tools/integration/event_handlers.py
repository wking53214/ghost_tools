"""Event handlers that bind events to orchestrator actions.

Handlers process incoming events and update the integration models accordingly.
Each event type has a corresponding handler that knows how to process it.
"""

from typing import Optional, Callable, Dict, Any
from datetime import datetime
import uuid

from .event_system import Event, EventType, get_event_bus
from .triage_ledger import TriageEntry, Decision, Severity as TriageSeverity


class EventHandler:
    """Base event handler that processes events and updates models."""

    def handle_triage_event(self, event: Event) -> None:
        """Process a finding_triaged event from Ghost.

        Creates a TriageEntry in the ledger for future oracle training.
        """
        data = event.data

        severity_map = {
            "CRITICAL": TriageSeverity.CRITICAL,
            "HIGH": TriageSeverity.HIGH,
            "MEDIUM": TriageSeverity.MEDIUM,
            "LOW": TriageSeverity.LOW,
        }

        decision_map = {
            "true": Decision.TRUE,
            "false": Decision.FALSE,
            "deferred": Decision.DEFERRED,
            "suppressed": Decision.SUPPRESSED,
        }

        # Import here to avoid circular deps
        from .triage_ledger import DEFAULT_LEDGER

        entry = TriageEntry(
            id=data["finding_id"],
            finding_type=data["finding_type"],
            location="",  # Not in event data
            description=data.get("reasoning", ""),
            severity_initial=severity_map.get(data.get("severity", "MEDIUM"), TriageSeverity.MEDIUM),
            decision=decision_map.get(data["decision"], Decision.DEFERRED),
            decided_by="ghost_tools",
            decided_at=event.timestamp,
            reasoning=data.get("reasoning", ""),
        )

        DEFAULT_LEDGER.add_entry(entry)

    def handle_violation_event(self, event: Event) -> None:
        """Process a violation_detected event from Swizzle.

        Records architecture violation in Ghost's audit for reference.
        """
        data = event.data

        # This is informational - Ghost can log this but doesn't act on it
        print(f"Architecture violation detected: {data['violation_type']} in {data['boundary_id']}")

    def handle_regression_event(self, event: Event) -> None:
        """Process a performance_regressed event.

        Logs regression for alerting and trends analysis.
        """
        data = event.data

        regression_msg = (
            f"Performance regression in {data['contract_id']}: "
            f"{data['metric_name']} regressed {data['regression_percent']:.1f}% "
            f"({data['baseline_value']:.2f} -> {data['current_value']:.2f})"
        )
        print(regression_msg)

    def handle_false_positive_event(self, event: Event) -> None:
        """Process a false_positive_confirmed event.

        Updates feedback patterns with confirmed false positive indicators.
        """
        data = event.data

        # Import here to avoid circular deps
        from .feedback_loop import DEFAULT_FEEDBACK_REPORT, FalsePositivePattern, FindingType

        finding_type_map = {
            "dated_claim": FindingType.DATED_CLAIM,
            "prose_deleted": FindingType.PROSE_DELETED,
            "boundary_violated": FindingType.BOUNDARY_VIOLATED,
        }

        pattern = FalsePositivePattern(
            id=f"pattern_{data['false_positive_id']}",
            finding_type=finding_type_map.get(data["finding_type"], FindingType.DATED_CLAIM),
            description=f"False positive pattern for {data['finding_type']}",
            indicators=data.get("indicators", []),
            confidence=data.get("confidence", 0.8),
        )

        # Add to feedback report if not already there
        if pattern.id not in DEFAULT_FEEDBACK_REPORT.false_positive_patterns:
            DEFAULT_FEEDBACK_REPORT.false_positive_patterns[pattern.id] = pattern

    def handle_mutation_event(self, event: Event) -> None:
        """Process a mutation_case_discovered event.

        Adds minimized test cases to Ghost's mutation testing suite.
        """
        data = event.data

        # Import here to avoid circular deps
        from .mutation_transfer import DEFAULT_MUTATION_CATALOG, MutationCase

        case = MutationCase(
            id=data["case_id"],
            hypothesis=data["hypothesis"],
            severity=data["severity"],
            minimized=data.get("minimized", True),
            repository_mutations={},  # Will be set separately
            expected_outcome="",  # Will be set separately
        )

        if case.id not in DEFAULT_MUTATION_CATALOG.cases:
            DEFAULT_MUTATION_CATALOG.cases[case.id] = case

    def handle_oracle_event(self, event: Event) -> None:
        """Process an oracle_training_improved event.

        Records oracle accuracy improvements for monitoring.
        """
        data = event.data

        improvement_msg = (
            f"Oracle improved for {data['finding_type']}: "
            f"accuracy={data['accuracy']:.2%}, "
            f"training_size={data['training_size']}, "
            f"improvement={data['improvement_percent']:.1f}%"
        )
        print(improvement_msg)


class EventHandlerRegistry:
    """Registry that binds handlers to event types."""

    def __init__(self):
        self.handlers: Dict[EventType, Callable[[Event], None]] = {}
        self._handler = EventHandler()
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Register all event handlers."""
        self.handlers[EventType.FINDING_TRIAGED] = self._handler.handle_triage_event
        self.handlers[EventType.VIOLATION_DETECTED] = self._handler.handle_violation_event
        self.handlers[EventType.PERFORMANCE_REGRESSED] = self._handler.handle_regression_event
        self.handlers[EventType.FALSE_POSITIVE_CONFIRMED] = self._handler.handle_false_positive_event
        self.handlers[EventType.MUTATION_CASE_DISCOVERED] = self._handler.handle_mutation_event
        self.handlers[EventType.ORACLE_TRAINING_IMPROVED] = self._handler.handle_oracle_event

    def register(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        """Register a custom handler for an event type."""
        self.handlers[event_type] = handler

    def get(self, event_type: EventType) -> Optional[Callable[[Event], None]]:
        """Get handler for event type."""
        return self.handlers.get(event_type)

    def handle(self, event: Event) -> None:
        """Process an event using its registered handler."""
        handler = self.get(event.type)
        if handler:
            handler(event)


# Global registry instance
_registry: Optional[EventHandlerRegistry] = None


def get_handler_registry() -> EventHandlerRegistry:
    """Get or create the global handler registry."""
    global _registry
    if _registry is None:
        _registry = EventHandlerRegistry()
    return _registry


def reset_handlers() -> None:
    """Reset to fresh registry (for testing)."""
    global _registry
    _registry = EventHandlerRegistry()


def setup_event_handlers() -> None:
    """Set up the default event handlers on the event bus."""
    bus = get_event_bus()
    registry = get_handler_registry()

    for event_type, handler in registry.handlers.items():
        bus.subscribe(event_type, handler)
