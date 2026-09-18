"""Real-time event system for inter-tool communication.

Enables streaming feedback between Swizzle and Ghost Tools via events instead of
batch processing. Events flow through an event bus with typed handlers.

Event types:
- finding_triaged: Ghost triaged a finding as true/false/deferred
- violation_detected: Architecture violation found by Swizzle
- performance_regressed: Performance contract violation detected
- false_positive_confirmed: Verified false positive for filter training
- mutation_case_discovered: New minimized test case from Swizzle
- oracle_training_improved: Oracle accuracy improved
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Callable, Any, Optional
from datetime import datetime
from pathlib import Path
import json


class EventType(str, Enum):
    """Predefined event types for inter-tool communication."""
    FINDING_TRIAGED = "finding_triaged"  # Ghost decision on a finding
    VIOLATION_DETECTED = "violation_detected"  # Architecture violation in audit
    PERFORMANCE_REGRESSED = "performance_regressed"  # Contract breach
    FALSE_POSITIVE_CONFIRMED = "false_positive_confirmed"  # FP verified by human
    MUTATION_CASE_DISCOVERED = "mutation_case_discovered"  # New minimized case
    ORACLE_TRAINING_IMPROVED = "oracle_training_improved"  # Oracle accuracy gain
    INTEGRATION_READY = "integration_ready"  # Bundles ready to publish


class EventSeverity(str, Enum):
    """Severity of event impact."""
    INFO = "info"  # Informational only
    WARN = "warn"  # Should be addressed
    ERROR = "error"  # Blocks operation


@dataclass
class Event:
    """A single event streamed between tools."""
    id: str  # unique event identifier
    type: EventType
    severity: EventSeverity
    timestamp: str  # ISO 8601
    source_tool: str  # "swizzle" or "ghost_tools"
    target_tool: str  # where event should be delivered

    # Event payload - varies by type
    data: Dict[str, Any] = field(default_factory=dict)

    # Tracking
    processed: bool = False
    processed_at: Optional[str] = None
    error: Optional[str] = None

    def to_json(self) -> str:
        """Serialize to JSON for transmission."""
        return json.dumps({
            "id": self.id,
            "type": self.type.value,
            "severity": self.severity.value,
            "timestamp": self.timestamp,
            "source_tool": self.source_tool,
            "target_tool": self.target_tool,
            "data": self.data,
            "processed": self.processed,
            "processed_at": self.processed_at,
            "error": self.error,
        }, indent=2)

    @staticmethod
    def from_json(json_str: str) -> "Event":
        """Deserialize from JSON."""
        data = json.loads(json_str)
        return Event(
            id=data["id"],
            type=EventType(data["type"]),
            severity=EventSeverity(data["severity"]),
            timestamp=data["timestamp"],
            source_tool=data["source_tool"],
            target_tool=data["target_tool"],
            data=data.get("data", {}),
            processed=data.get("processed", False),
            processed_at=data.get("processed_at"),
            error=data.get("error"),
        )


EventHandler = Callable[[Event], None]


class EventBus:
    """Pub-sub event bus for inter-tool communication."""

    def __init__(self):
        self.handlers: Dict[EventType, List[EventHandler]] = {}
        self.event_log: List[Event] = []

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Unregister a handler."""
        if event_type in self.handlers:
            self.handlers[event_type] = [h for h in self.handlers[event_type] if h != handler]

    def publish(self, event: Event) -> None:
        """Publish an event to all registered handlers."""
        self.event_log.append(event)

        if event.type in self.handlers:
            for handler in self.handlers[event.type]:
                try:
                    handler(event)
                    event.processed = True
                    event.processed_at = datetime.now().isoformat()
                except Exception as e:
                    event.error = str(e)

    def get_unprocessed(self, event_type: Optional[EventType] = None) -> List[Event]:
        """Get events that haven't been processed."""
        if event_type:
            return [e for e in self.event_log if e.type == event_type and not e.processed]
        return [e for e in self.event_log if not e.processed]

    def save_log(self, path: Path) -> None:
        """Persist event log to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        events = [json.loads(e.to_json()) for e in self.event_log]
        path.write_text(json.dumps({"events": events}, indent=2))

    def load_log(self, path: Path) -> None:
        """Load event log from disk."""
        if not path.exists():
            return
        data = json.loads(path.read_text())
        for event_data in data.get("events", []):
            event_json = json.dumps(event_data)
            self.event_log.append(Event.from_json(event_json))


# Global event bus instance
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create the global event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    """Reset to fresh event bus (for testing)."""
    global _event_bus
    _event_bus = EventBus()


# Factory functions for creating typed events

def create_triage_event(
    finding_id: str,
    finding_type: str,
    decision: str,
    reasoning: str,
    severity: str,
) -> Event:
    """Create a finding_triaged event from Ghost."""
    import uuid
    return Event(
        id=str(uuid.uuid4()),
        type=EventType.FINDING_TRIAGED,
        severity=EventSeverity.INFO,
        timestamp=datetime.now().isoformat(),
        source_tool="ghost_tools",
        target_tool="swizzle",
        data={
            "finding_id": finding_id,
            "finding_type": finding_type,
            "decision": decision,
            "reasoning": reasoning,
            "severity": severity,
        },
    )


def create_violation_event(
    violation_id: str,
    violation_type: str,
    boundary_id: str,
    location: str,
    severity: str,
) -> Event:
    """Create a violation_detected event from Swizzle."""
    import uuid
    return Event(
        id=str(uuid.uuid4()),
        type=EventType.VIOLATION_DETECTED,
        severity=EventSeverity(
            "error" if severity == "CRITICAL" else "warn"
        ),
        timestamp=datetime.now().isoformat(),
        source_tool="swizzle",
        target_tool="ghost_tools",
        data={
            "violation_id": violation_id,
            "violation_type": violation_type,
            "boundary_id": boundary_id,
            "location": location,
            "severity": severity,
        },
    )


def create_regression_event(
    contract_id: str,
    case_id: str,
    metric_name: str,
    baseline_value: float,
    current_value: float,
    regression_percent: float,
) -> Event:
    """Create a performance_regressed event from performance monitoring."""
    import uuid
    return Event(
        id=str(uuid.uuid4()),
        type=EventType.PERFORMANCE_REGRESSED,
        severity=EventSeverity.ERROR if regression_percent >= 20 else EventSeverity.WARN,
        timestamp=datetime.now().isoformat(),
        source_tool="swizzle",
        target_tool="ghost_tools",
        data={
            "contract_id": contract_id,
            "case_id": case_id,
            "metric_name": metric_name,
            "baseline_value": baseline_value,
            "current_value": current_value,
            "regression_percent": regression_percent,
        },
    )


def create_false_positive_event(
    false_positive_id: str,
    finding_type: str,
    confidence: float,
    indicators: List[str],
) -> Event:
    """Create a false_positive_confirmed event when pattern verified."""
    import uuid
    return Event(
        id=str(uuid.uuid4()),
        type=EventType.FALSE_POSITIVE_CONFIRMED,
        severity=EventSeverity.INFO,
        timestamp=datetime.now().isoformat(),
        source_tool="ghost_tools",
        target_tool="swizzle",
        data={
            "false_positive_id": false_positive_id,
            "finding_type": finding_type,
            "confidence": confidence,
            "indicators": indicators,
        },
    )


def create_mutation_event(
    case_id: str,
    hypothesis: str,
    severity: str,
    minimized: bool,
) -> Event:
    """Create a mutation_case_discovered event from Swizzle."""
    import uuid
    return Event(
        id=str(uuid.uuid4()),
        type=EventType.MUTATION_CASE_DISCOVERED,
        severity=EventSeverity.INFO,
        timestamp=datetime.now().isoformat(),
        source_tool="swizzle",
        target_tool="ghost_tools",
        data={
            "case_id": case_id,
            "hypothesis": hypothesis,
            "severity": severity,
            "minimized": minimized,
        },
    )


def create_oracle_event(
    finding_type: str,
    accuracy: float,
    training_size: int,
    improvement_percent: float,
) -> Event:
    """Create an oracle_training_improved event."""
    import uuid
    return Event(
        id=str(uuid.uuid4()),
        type=EventType.ORACLE_TRAINING_IMPROVED,
        severity=EventSeverity.INFO,
        timestamp=datetime.now().isoformat(),
        source_tool="swizzle",
        target_tool="ghost_tools",
        data={
            "finding_type": finding_type,
            "accuracy": accuracy,
            "training_size": training_size,
            "improvement_percent": improvement_percent,
        },
    )
