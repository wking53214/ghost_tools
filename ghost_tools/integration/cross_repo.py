"""Cross-repository integration and analytics orchestration."""

from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import json

from .unified_index import UnifiedIndex, get_unified_index
from .query_engine import QueryEngine, create_query_engine


class CrossRepoManager:
    """Manages cross-repository integration and analytics."""

    def __init__(self, workspace_dir: Path):
        self.workspace = workspace_dir
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.index = get_unified_index()
        self.query_engine = create_query_engine(self.index)
        self.index_path = self.workspace / "unified_index.json"

    def sync_index(self) -> None:
        """Sync index to disk."""
        self.index.save(self.index_path)

    def load_index(self) -> None:
        """Load index from disk."""
        self.index.load(self.index_path)

    def get_query_engine(self) -> QueryEngine:
        """Get query engine."""
        return self.query_engine

    def run_analytics(self) -> Dict[str, Any]:
        """Run full analytics suite."""
        self.sync_index()

        report = {
            "timestamp": datetime.now().isoformat(),
            "summary_report": self.query_engine.generate_summary_report(),
            "index_snapshot": {
                "total_events": len(self.index.events),
                "total_decisions": len(self.index.decisions),
                "events_by_repo": dict(self.index.repo_event_counts),
                "decisions_by_repo": dict(self.index.repo_decision_counts),
            },
        }

        report_path = self.workspace / f"analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path.write_text(json.dumps(report, indent=2))

        return report

    def export_for_dashboarding(self) -> Dict[str, Any]:
        """Export data formatted for dashboards."""
        return {
            "timestamp": datetime.now().isoformat(),
            "stats": self.query_engine.query_stats(),
            "trends": self.query_engine.query_trends(),
            "anomalies": self.query_engine.query_anomalies(),
            "patterns": self.query_engine.query_patterns(),
            "timeline": self.query_engine.query_timeline(),
            "risk_distribution": self.query_engine.query_risk_distribution(),
            "repo_comparison": self.query_engine.query_repo_comparison(),
        }

    def generate_html_report(self) -> str:
        """Generate HTML report for viewing in browser."""
        data = self.export_for_dashboarding()

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Swizzle-Ghost Tools Analytics Dashboard</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
        }}
        .section {{
            background: white;
            padding: 20px;
            margin-bottom: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .section h2 {{
            margin-top: 0;
            color: #333;
        }}
        .metric {{
            display: inline-block;
            padding: 15px 25px;
            margin: 10px 10px 10px 0;
            background: #f8f8f8;
            border-left: 4px solid #667eea;
            border-radius: 4px;
        }}
        .metric-label {{
            font-size: 0.85em;
            color: #666;
            text-transform: uppercase;
        }}
        .metric-value {{
            font-size: 1.8em;
            font-weight: bold;
            color: #333;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background: #f8f8f8;
            font-weight: 600;
            color: #333;
        }}
        .timestamp {{
            color: #999;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔍 Swizzle-Ghost Tools Analytics Dashboard</h1>
        <p>Real-time cross-repository integration analytics and insights</p>
        <p class="timestamp">Generated: {data['timestamp']}</p>
    </div>

    <div class="section">
        <h2>📊 Overview</h2>
        <div class="metric">
            <div class="metric-label">Total Events</div>
            <div class="metric-value">{data['stats']['event_counts']['total']}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Total Decisions</div>
            <div class="metric-value">{data['stats']['decision_counts']['total']}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Approval Rate</div>
            <div class="metric-value">{data['stats']['decisions']['approval_rate']*100:.1f}%</div>
        </div>
        <div class="metric">
            <div class="metric-label">Execution Rate</div>
            <div class="metric-value">{data['stats']['decisions']['execution_rate']*100:.1f}%</div>
        </div>
    </div>
</body>
</html>
"""
        return html

    def save_html_report(self, filepath: Optional[Path] = None) -> Path:
        """Save HTML report to file."""
        if filepath is None:
            filepath = self.workspace / f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(self.generate_html_report())
        return filepath
