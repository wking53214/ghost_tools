"""Trend analysis across repositories."""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import statistics

from .unified_index import UnifiedIndex


@dataclass
class Trend:
    """A detected trend."""
    name: str
    metric: str
    current_value: float
    previous_value: float
    change_percent: float
    direction: str
    significance: str
    timestamp: str


@dataclass
class Anomaly:
    """A detected anomaly."""
    type: str
    description: str
    severity: str
    affected_repos: List[str]
    data: Dict[str, Any]
    detected_at: str


class TrendAnalyzer:
    """Analyzes trends and anomalies in unified index."""
    
    def __init__(self, index: UnifiedIndex):
        self.index = index
        self.trends: List[Trend] = []
        self.anomalies: List[Anomaly] = []
    
    def analyze_confidence_trend(self, hours: int = 24) -> Optional[Trend]:
        """Analyze confidence score trend over time."""
        now = datetime.fromisoformat(datetime.now().isoformat().replace('Z', '+00:00').split('+')[0])
        cutoff_recent = now - timedelta(hours=hours // 2)
        cutoff_older = now - timedelta(hours=hours)
        
        recent_scores = []
        older_scores = []
        
        for decision in self.index.decisions.values():
            try:
                decision_time = datetime.fromisoformat(decision.created_at.replace('Z', '+00:00').split('+')[0])
                if decision_time >= cutoff_recent:
                    recent_scores.append(decision.confidence)
                elif decision_time >= cutoff_older:
                    older_scores.append(decision.confidence)
            except (ValueError, AttributeError):
                continue
        
        if not recent_scores or not older_scores:
            return None
        
        recent_avg = statistics.mean(recent_scores)
        older_avg = statistics.mean(older_scores)
        
        if older_avg == 0:
            change_percent = 0.0
        else:
            change_percent = ((recent_avg - older_avg) / older_avg) * 100
        
        direction = "up" if recent_avg > older_avg else "down" if recent_avg < older_avg else "stable"
        significance = self._assess_significance(abs(change_percent))
        
        return Trend(
            name="Confidence Score Trend",
            metric="average_confidence",
            current_value=recent_avg,
            previous_value=older_avg,
            change_percent=change_percent,
            direction=direction,
            significance=significance,
            timestamp=datetime.now().isoformat(),
        )
    
    def analyze_approval_rate_trend(self, hours: int = 24) -> Optional[Trend]:
        """Analyze approval rate trend."""
        now = datetime.fromisoformat(datetime.now().isoformat().replace('Z', '+00:00').split('+')[0])
        cutoff_recent = now - timedelta(hours=hours // 2)
        cutoff_older = now - timedelta(hours=hours)
        
        recent_decisions = [d for d in self.index.decisions.values()
                          if self._is_in_timerange(d.created_at, cutoff_recent, now)]
        older_decisions = [d for d in self.index.decisions.values()
                          if self._is_in_timerange(d.created_at, cutoff_older, cutoff_recent)]
        
        if not recent_decisions or not older_decisions:
            return None
        
        recent_rate = sum(1 for d in recent_decisions if d.approved) / len(recent_decisions)
        older_rate = sum(1 for d in older_decisions if d.approved) / len(older_decisions)
        
        change_percent = ((recent_rate - older_rate) / older_rate * 100) if older_rate > 0 else 0
        direction = "up" if recent_rate > older_rate else "down" if recent_rate < older_rate else "stable"
        significance = self._assess_significance(abs(change_percent))
        
        return Trend(
            name="Approval Rate Trend",
            metric="approval_rate",
            current_value=recent_rate,
            previous_value=older_rate,
            change_percent=change_percent,
            direction=direction,
            significance=significance,
            timestamp=datetime.now().isoformat(),
        )
    
    def analyze_regression_trend(self, hours: int = 24) -> Optional[Trend]:
        """Analyze performance regression trend."""
        now = datetime.fromisoformat(datetime.now().isoformat().replace('Z', '+00:00').split('+')[0])
        cutoff_recent = now - timedelta(hours=hours // 2)
        cutoff_older = now - timedelta(hours=hours)
        
        recent_events = [e for e in self.index.events.values()
                        if e.type == "performance_regressed"
                        and self._is_in_timerange(e.timestamp, cutoff_recent, now)]
        older_events = [e for e in self.index.events.values()
                       if e.type == "performance_regressed"
                       and self._is_in_timerange(e.timestamp, cutoff_older, cutoff_recent)]
        
        if not recent_events and not older_events:
            return None
        
        recent_count = len(recent_events)
        older_count = len(older_events) if older_events else 1
        
        change_percent = ((recent_count - older_count) / older_count * 100)
        direction = "up" if recent_count > older_count else "down" if recent_count < older_count else "stable"
        significance = "critical" if recent_count >= 5 else "high" if recent_count >= 3 else "medium" if recent_count >= 1 else "low"
        
        return Trend(
            name="Regression Event Trend",
            metric="regression_event_count",
            current_value=float(recent_count),
            previous_value=float(older_count),
            change_percent=change_percent,
            direction=direction,
            significance=significance,
            timestamp=datetime.now().isoformat(),
        )
    
    def detect_anomalies(self) -> List[Anomaly]:
        """Detect anomalies in indexed data."""
        anomalies = []
        
        imbalance = self._check_approval_imbalance()
        if imbalance:
            anomalies.append(imbalance)
        
        non_execution = self._check_non_execution_anomaly()
        if non_execution:
            anomalies.append(non_execution)
        
        concentration = self._check_decision_concentration()
        if concentration:
            anomalies.append(concentration)
        
        spike = self._check_regression_spike()
        if spike:
            anomalies.append(spike)
        
        self.anomalies = anomalies
        return anomalies
    
    def _check_approval_imbalance(self) -> Optional[Anomaly]:
        """Check if approval rates differ significantly between repos."""
        stats_by_repo = {}
        for repo in self.index.repo_decision_counts.keys():
            decisions = [d for d in self.index.decisions.values() if d.repo == repo]
            if decisions:
                approved = sum(1 for d in decisions if d.approved)
                stats_by_repo[repo] = approved / len(decisions)
        
        if len(stats_by_repo) < 2:
            return None
        
        rates = list(stats_by_repo.values())
        if max(rates) - min(rates) > 0.3:
            return Anomaly(
                type="approval_imbalance",
                description=f"Approval rate varies significantly between repos: {stats_by_repo}",
                severity="high",
                affected_repos=list(stats_by_repo.keys()),
                data=stats_by_repo,
                detected_at=datetime.now().isoformat(),
            )
        
        return None
    
    def _check_non_execution_anomaly(self) -> Optional[Anomaly]:
        """Check if high-confidence decisions aren't executing."""
        high_confidence = [d for d in self.index.decisions.values()
                          if d.confidence >= 0.9 and d.approved]
        
        if not high_confidence:
            return None
        
        not_executed = sum(1 for d in high_confidence if not d.executed)
        if not_executed / len(high_confidence) > 0.2:
            return Anomaly(
                type="non_execution_anomaly",
                description=f"{not_executed}/{len(high_confidence)} high-confidence decisions not executing",
                severity="medium",
                affected_repos=list(set(d.repo for d in high_confidence if not d.executed)),
                data={"high_confidence_count": len(high_confidence), "not_executed_count": not_executed},
                detected_at=datetime.now().isoformat(),
            )
        
        return None
    
    def _check_decision_concentration(self) -> Optional[Anomaly]:
        """Check if decisions are concentrated in few types."""
        counter = Counter(d.type for d in self.index.decisions.values())
        if not counter:
            return None
        
        total = sum(counter.values())
        top_type_percent = counter.most_common(1)[0][1] / total
        
        if top_type_percent > 0.7:
            return Anomaly(
                type="decision_concentration",
                description=f"{counter.most_common(1)[0][0]} represents {top_type_percent*100:.1f}% of decisions",
                severity="medium",
                affected_repos=list(set(d.repo for d in self.index.decisions.values())),
                data=dict(counter),
                detected_at=datetime.now().isoformat(),
            )
        
        return None
    
    def _check_regression_spike(self) -> Optional[Anomaly]:
        """Check for recent spike in regressions."""
        now = datetime.fromisoformat(datetime.now().isoformat().replace('Z', '+00:00').split('+')[0])
        recent = now - timedelta(hours=2)
        
        recent_regressions = [
            e for e in self.index.events.values()
            if e.type == "performance_regressed"
            and self._is_in_timerange(e.timestamp, recent, now)
        ]
        
        if len(recent_regressions) >= 3:
            return Anomaly(
                type="regression_spike",
                description=f"{len(recent_regressions)} performance regressions in last 2 hours",
                severity="critical" if len(recent_regressions) >= 5 else "high",
                affected_repos=list(set(e.repo for e in recent_regressions)),
                data={"count": len(recent_regressions), "affected_metrics": list(set(
                    e.data.get("metric_name") for e in recent_regressions
                ))},
                detected_at=datetime.now().isoformat(),
            )
        
        return None
    
    def get_top_patterns(self) -> Dict[str, Any]:
        """Get top false positive patterns by effectiveness."""
        patterns = self.index.get_false_positive_patterns()
        if not patterns:
            return {}
        
        by_type = defaultdict(list)
        for pattern in patterns:
            finding_type = pattern.get("finding_type", "unknown")
            by_type[finding_type].append(pattern.get("confidence", 0))
        
        result = {}
        for finding_type, confidences in by_type.items():
            result[finding_type] = {
                "count": len(confidences),
                "avg_confidence": statistics.mean(confidences),
                "max_confidence": max(confidences),
                "min_confidence": min(confidences),
            }
        
        return dict(sorted(result.items(), key=lambda x: x[1]["count"], reverse=True))
    
    def _is_in_timerange(self, timestamp_str: str, start: datetime, end: datetime) -> bool:
        """Check if timestamp is in range."""
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00').split('+')[0])
            return start <= timestamp <= end
        except (ValueError, AttributeError):
            return False
    
    def _assess_significance(self, change_percent: float) -> str:
        """Assess significance of change."""
        abs_change = abs(change_percent)
        if abs_change >= 50:
            return "critical"
        elif abs_change >= 25:
            return "high"
        elif abs_change >= 10:
            return "medium"
        else:
            return "low"


def create_trend_analyzer(index: UnifiedIndex) -> TrendAnalyzer:
    """Factory for trend analyzer."""
    return TrendAnalyzer(index)
