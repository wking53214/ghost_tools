"""Integration between event system and decision engine.

When events are published, they are evaluated for automated decisions.
Low-risk decisions are auto-executed; high-risk decisions await review.
"""

from typing import Optional

from .event_system import Event, get_event_bus
from .decision_engine import get_decision_engine, AutomatedDecision


def create_event_evaluator():
    """Factory for event evaluator."""
    return EventEvaluator()


class EventEvaluator:
    """Evaluates events and creates decisions."""

    def __init__(self):
        self.engine = get_decision_engine()
        self.bus = get_event_bus()
        self.decisions_made: int = 0
        self.decisions_auto_approved: int = 0
        self.decisions_escalated: int = 0

    def evaluate_event(self, event: Event) -> Optional[AutomatedDecision]:
        """Evaluate event and potentially make a decision."""
        decision = self.engine.make_decision(event)

        if decision:
            self.decisions_made += 1
            if decision.approved:
                self.decisions_auto_approved += 1
            elif decision.risk_level.value in ("high", "critical"):
                self.decisions_escalated += 1

        return decision

    def get_stats(self) -> dict:
        """Get evaluation statistics."""
        return {
            "decisions_made": self.decisions_made,
            "decisions_auto_approved": self.decisions_auto_approved,
            "decisions_escalated": self.decisions_escalated,
        }


# Global evaluator instance
_evaluator: Optional[EventEvaluator] = None


def get_event_evaluator() -> EventEvaluator:
    """Get or create global event evaluator."""
    global _evaluator
    if _evaluator is None:
        _evaluator = EventEvaluator()
    return _evaluator


def reset_event_evaluator() -> None:
    """Reset to fresh evaluator (for testing)."""
    global _evaluator
    _evaluator = EventEvaluator()


def setup_event_evaluation() -> None:
    """Connect event evaluator to event bus."""
    bus = get_event_bus()
    evaluator = get_event_evaluator()

    # Subscribe evaluator to all events
    def event_handler(event: Event):
        evaluator.evaluate_event(event)

    # Register for main event types that trigger decisions
    from .event_system import EventType

    bus.subscribe(EventType.FALSE_POSITIVE_CONFIRMED, event_handler)
    bus.subscribe(EventType.VIOLATION_DETECTED, event_handler)
    bus.subscribe(EventType.PERFORMANCE_REGRESSED, event_handler)
    bus.subscribe(EventType.MUTATION_CASE_DISCOVERED, event_handler)
    bus.subscribe(EventType.ORACLE_TRAINING_IMPROVED, event_handler)
