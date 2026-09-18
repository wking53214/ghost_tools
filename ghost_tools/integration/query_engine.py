"""Query engine for cross-repository analytics."""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from .unified_index import UnifiedIndex, get_unified_index
from .trend_analyzer import TrendAnalyzer, create_trend_analyzer


class QueryType(str, Enum):
    """Query types."""
    STATS = "stats"
    TRENDS = "trends"
    ANOMALIES = "anomalies"
    PATTERNS = "patterns"
    TIMELINE = "timeline"


@dataclass
class QueryResult:
    """Result from a query."""
    type: QueryType
    data: Dict[str, Any]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class QueryEngine:
    """High-level query interface for analytics."""

    def __init__(self, index: Optional[UnifiedIndex] = None):
        self.index = index or get_unified_index()
        self.analyzer = create_trend_analyzer(self.index)

    def query_stats(self, repo: Optional[str] = None, metric: Optional[str] = None) -> Dict[str, Any]:
        """Query statistics."""
        stats = {
            "decisions": self.index.get_approval_stats(repo),
            "confidence_distribution": self.index.get_confidence_distribution(repo),
            "event_counts": {
                "total": len(self.index.events),
                "by_repo": dict(self.index.repo_event_counts),
            },
            "decision_counts": {
                "total": len(self.index.decisions),
                "by_repo": dict(self.index.repo_decision_counts),
            },
            "most_common_decisions": self.index.get_most_common_decision_types(repo),
            "most_common_events": self.index.get_most_common_event_types(repo),
            "regression_summary": self.index.get_regression_summary(),
            "mutation_effectiveness": self.index.get_mutation_effectiveness(),
        }

        if metric:
            return stats.get(metric, {})

        return stats

    def query_trends(self, hours: int = 24) -> Dict[str, Any]:
        """Query trends."""
        trends = []

        confidence_trend = self.analyzer.analyze_confidence_trend(hours)
        if confidence_trend:
            trends.append(confidence_trend.__dict__)

        approval_trend = self.analyzer.analyze_approval_rate_trend(hours)
        if approval_trend:
            trends.append(approval_trend.__dict__)

        regression_trend = self.analyzer.analyze_regression_trend(hours)
        if regression_trend:
            trends.append(regression_trend.__dict__)

        return {
            "period_hours": hours,
            "trends": trends,
            "trend_count": len(trends),
        }

    def query_anomalies(self) -> Dict[str, Any]:
        """Query detected anomalies."""
        anomalies = self.analyzer.detect_anomalies()

        return {
            "anomalies": [a.__dict__ for a in anomalies],
            "anomaly_count": len(anomalies),
            "severity_summary": {
                "critical": sum(1 for a in anomalies if a.severity == "critical"),
                "high": sum(1 for a in anomalies if a.severity == "high"),
                "medium": sum(1 for a in anomalies if a.severity == "medium"),
                "low": sum(1 for a in anomalies if a.severity == "low"),
            },
        }

    def query_patterns(self) -> Dict[str, Any]:
        """Query top patterns."""
        return {
            "false_positive_patterns": self.analyzer.get_top_patterns(),
            "decision_success_rates": {
                decision_type: self.index.get_decision_success_rate(decision_type)
                for decision_type, _ in self.index.get_most_common_decision_types(limit=5)
            },
        }

    def query_timeline(self, hours: int = 24) -> Dict[str, Any]:
        """Query event timeline."""
        timeline = self.index.get_event_timeline(hours)

        return {
            "period_hours": hours,
            "timeline": timeline,
            "total_events": sum(timeline.values()),
        }

    def query_repo_comparison(self) -> Dict[str, Any]:
        """Compare metrics across repositories."""
        repos = list(set(
            list(self.index.repo_decision_counts.keys()) +
            list(self.index.repo_event_counts.keys())
        ))

        comparison = {}
        for repo in repos:
            comparison[repo] = {
                "events": {
                    "total": self.index.repo_event_counts.get(repo, 0),
                    "types": dict(self.index.get_most_common_event_types(repo, limit=5)),
                },
                "decisions": {
                    "total": self.index.repo_decision_counts.get(repo, 0),
                    **self.index.get_approval_stats(repo),
                    "types": dict(self.index.get_most_common_decision_types(repo, limit=5)),
                },
            }

        return {
            "repositories": comparison,
            "repo_count": len(repos),
        }

    def query_risk_distribution(self) -> Dict[str, Any]:
        """Get distribution of decisions by risk level."""
        risk_levels = ["low", "medium", "high", "critical"]
        distribution = {}

        for risk in risk_levels:
            decisions = self.index.query_decisions_by_risk(risk)
            distribution[risk] = {
                "count": len(decisions),
                "approved": sum(1 for d in decisions if d.approved),
                "executed": sum(1 for d in decisions if d.executed),
            }

        return distribution

    def generate_summary_report(self) -> Dict[str, Any]:
        """Generate comprehensive summary report."""
        return {
            "summary": {
                "total_events": len(self.index.events),
                "total_decisions": len(self.index.decisions),
                "repositories": list(set(
                    list(self.index.repo_decision_counts.keys()) +
                    list(self.index.repo_event_counts.keys())
                )),
            },
            "stats": self.query_stats(),
            "trends": self.query_trends(hours=24),
            "anomalies": self.query_anomalies(),
            "patterns": self.query_patterns(),
            "risk_distribution": self.query_risk_distribution(),
            "repo_comparison": self.query_repo_comparison(),
        }


def create_query_engine(index: Optional[UnifiedIndex] = None) -> QueryEngine:
    """Factory for query engine."""
    return QueryEngine(index)
