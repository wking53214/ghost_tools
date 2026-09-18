"""Unified index for cross-repository analytics.

Aggregates events and decisions from all monitored repositories,
enabling pattern detection, trending analysis, and unified queries.
"""

from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import json


@dataclass
class IndexedEvent:
    """An event in the unified index."""
    event_id: str
    repo: str  # "swizzle" or "ghost_tools"
    type: str
    timestamp: str
    data: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class IndexedDecision:
    """A decision in the unified index."""
    decision_id: str
    repo: str
    type: str
    risk_level: str
    confidence: float
    approved: bool
    executed: bool
    created_at: str
    executed_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class UnifiedIndex:
    """Indexes events and decisions from multiple repositories."""

    def __init__(self):
        self.events: Dict[str, IndexedEvent] = {}
        self.decisions: Dict[str, IndexedDecision] = {}
        self.repo_event_counts: Dict[str, int] = defaultdict(int)
        self.repo_decision_counts: Dict[str, int] = defaultdict(int)
        self.last_sync: Dict[str, datetime] = {}

    def add_event(self, repo: str, event) -> None:
        """Add event to index."""
        # Handle both Event objects and IndexedEvent objects
        if isinstance(event, IndexedEvent):
            self.events[event.event_id] = event
        else:
            # Assume it's an Event object from event_system
            indexed = IndexedEvent(
                event_id=event.id,
                repo=repo,
                type=event.type.value if hasattr(event.type, 'value') else str(event.type),
                timestamp=event.timestamp,
                data=event.data,
            )
            self.events[event.id] = indexed
        self.repo_event_counts[repo] += 1

    def add_decision(self, repo: str, decision) -> None:
        """Add decision to index."""
        # Handle both AutomatedDecision objects and IndexedDecision objects
        if isinstance(decision, IndexedDecision):
            self.decisions[decision.decision_id] = decision
        else:
            # Assume it's an AutomatedDecision object
            indexed = IndexedDecision(
                decision_id=decision.id,
                repo=repo,
                type=decision.type.value if hasattr(decision.type, 'value') else str(decision.type),
                risk_level=decision.risk_level.value if hasattr(decision.risk_level, 'value') else str(decision.risk_level),
                confidence=decision.confidence.value if hasattr(decision.confidence, 'value') else float(decision.confidence),
                approved=decision.approved,
                executed=decision.executed,
                created_at=decision.created_at,
                executed_at=decision.executed_at,
            )
            self.decisions[decision.id] = indexed
        self.repo_decision_counts[repo] += 1

    def query_events_by_type(self, event_type: str, repo: Optional[str] = None) -> List[IndexedEvent]:
        """Query events by type, optionally filtered by repo."""
        results = [e for e in self.events.values() if e.type == event_type]
        if repo:
            results = [e for e in results if e.repo == repo]
        return sorted(results, key=lambda x: x.timestamp, reverse=True)

    def query_decisions_by_type(self, decision_type: str, repo: Optional[str] = None) -> List[IndexedDecision]:
        """Query decisions by type, optionally filtered by repo."""
        results = [d for d in self.decisions.values() if d.type == decision_type]
        if repo:
            results = [d for d in results if d.repo == repo]
        return sorted(results, key=lambda x: x.created_at, reverse=True)

    def query_decisions_by_risk(self, risk_level: str) -> List[IndexedDecision]:
        """Get decisions by risk level."""
        return [d for d in self.decisions.values() if d.risk_level == risk_level]

    def get_approval_stats(self, repo: Optional[str] = None) -> Dict[str, Any]:
        """Get approval statistics."""
        decisions = list(self.decisions.values())
        if repo:
            decisions = [d for d in decisions if d.repo == repo]

        if not decisions:
            return {"total": 0, "approved": 0, "executed": 0, "approval_rate": 0.0, "execution_rate": 0.0}

        total = len(decisions)
        approved = sum(1 for d in decisions if d.approved)
        executed = sum(1 for d in decisions if d.executed)

        return {
            "total": total,
            "approved": approved,
            "executed": executed,
            "approval_rate": approved / total if total > 0 else 0.0,
            "execution_rate": executed / total if total > 0 else 0.0,
        }

    def get_confidence_distribution(self, repo: Optional[str] = None) -> Dict[str, int]:
        """Get distribution of confidence scores."""
        decisions = list(self.decisions.values())
        if repo:
            decisions = [d for d in decisions if d.repo == repo]

        distribution = defaultdict(int)
        for d in decisions:
            bucket = int(d.confidence * 10) / 10  # Round to nearest 0.1
            distribution[bucket] += 1

        return dict(sorted(distribution.items()))

    def get_most_common_decision_types(self, repo: Optional[str] = None, limit: int = 10) -> List[Tuple[str, int]]:
        """Get most common decision types."""
        decisions = list(self.decisions.values())
        if repo:
            decisions = [d for d in decisions if d.repo == repo]

        counter = Counter(d.type for d in decisions)
        return counter.most_common(limit)

    def get_most_common_event_types(self, repo: Optional[str] = None, limit: int = 10) -> List[Tuple[str, int]]:
        """Get most common event types."""
        events = list(self.events.values())
        if repo:
            events = [e for e in events if e.repo == repo]

        counter = Counter(e.type for e in events)
        return counter.most_common(limit)

    def get_event_timeline(self, hours: int = 24) -> Dict[str, int]:
        """Get event counts over time buckets."""
        now = datetime.fromisoformat(datetime.now().isoformat().replace('Z', '+00:00').split('+')[0])
        cutoff = now - timedelta(hours=hours)

        timeline = defaultdict(int)
        for event in self.events.values():
            try:
                event_time = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00').split('+')[0])
                if event_time >= cutoff:
                    # Group by hour
                    hour_key = event_time.strftime("%Y-%m-%d %H:00")
                    timeline[hour_key] += 1
            except (ValueError, AttributeError):
                continue

        return dict(sorted(timeline.items()))

    def get_decision_success_rate(self, decision_type: Optional[str] = None, repo: Optional[str] = None) -> Dict[str, Any]:
        """Get success rate for decisions (approved and executed)."""
        decisions = list(self.decisions.values())
        if repo:
            decisions = [d for d in decisions if d.repo == repo]
        if decision_type:
            decisions = [d for d in decisions if d.type == decision_type]

        if not decisions:
            return {"type": decision_type or "all", "total": 0, "success_rate": 0.0}

        successful = sum(1 for d in decisions if d.approved and d.executed)
        total = len(decisions)

        return {
            "type": decision_type or "all",
            "total": total,
            "successful": successful,
            "success_rate": successful / total if total > 0 else 0.0,
        }

    def get_false_positive_patterns(self) -> List[Dict[str, Any]]:
        """Extract false positive pattern data from indexed events."""
        patterns = []
        for event in self.events.values():
            if event.type == "false_positive_confirmed":
                patterns.append({
                    "id": event.data.get("false_positive_id"),
                    "finding_type": event.data.get("finding_type"),
                    "confidence": event.data.get("confidence"),
                    "repo": event.repo,
                    "timestamp": event.timestamp,
                })
        return patterns

    def get_mutation_effectiveness(self) -> Dict[str, int]:
        """Analyze which mutations are discovered most often."""
        counter = Counter()
        for event in self.events.values():
            if event.type == "mutation_case_discovered":
                severity = event.data.get("severity", "UNKNOWN")
                counter[severity] += 1
        return dict(counter)

    def get_regression_summary(self) -> Dict[str, Any]:
        """Summarize performance regressions."""
        regressions = [
            e for e in self.events.values()
            if e.type == "performance_regressed"
        ]

        if not regressions:
            return {"total": 0, "avg_regression_percent": 0.0, "by_repo": {}}

        by_repo = defaultdict(list)
        all_percents = []

        for regression in regressions:
            repo = regression.repo
            percent = regression.data.get("regression_percent", 0.0)
            by_repo[repo].append(percent)
            all_percents.append(percent)

        return {
            "total": len(regressions),
            "avg_regression_percent": sum(all_percents) / len(all_percents) if all_percents else 0.0,
            "by_repo": {
                repo: sum(percents) / len(percents)
                for repo, percents in by_repo.items()
            },
        }

    def save(self, filepath: Path) -> None:
        """Persist index to disk."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "events": {k: asdict(v) for k, v in self.events.items()},
            "decisions": {k: v.to_dict() for k, v in self.decisions.items()},
            "repo_event_counts": dict(self.repo_event_counts),
            "repo_decision_counts": dict(self.repo_decision_counts),
            "last_sync": {k: v.isoformat() for k, v in self.last_sync.items()},
        }
        filepath.write_text(json.dumps(data, indent=2))

    def load(self, filepath: Path) -> None:
        """Load index from disk."""
        if not filepath.exists():
            return

        data = json.loads(filepath.read_text())

        self.events = {
            k: IndexedEvent(**v)
            for k, v in data.get("events", {}).items()
        }

        self.decisions = {
            k: IndexedDecision(**v)
            for k, v in data.get("decisions", {}).items()
        }

        self.repo_event_counts = defaultdict(int, data.get("repo_event_counts", {}))
        self.repo_decision_counts = defaultdict(int, data.get("repo_decision_counts", {}))

        self.last_sync = {
            k: datetime.fromisoformat(v)
            for k, v in data.get("last_sync", {}).items()
        }


# Global unified index instance
_unified_index: Optional[UnifiedIndex] = None


def get_unified_index() -> UnifiedIndex:
    """Get or create global unified index."""
    global _unified_index
    if _unified_index is None:
        _unified_index = UnifiedIndex()
    return _unified_index


def reset_unified_index() -> None:
    """Reset to fresh index (for testing)."""
    global _unified_index
    _unified_index = UnifiedIndex()
