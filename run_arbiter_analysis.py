#!/usr/bin/env python
"""Run Ghost Tools analysis on the Arbiter repository."""

import subprocess
import json
from pathlib import Path
from datetime import datetime
from collections import Counter

from ghost_tools.integration.event_system import (
    Event, EventType, EventSeverity, get_event_bus, reset_event_bus, create_false_positive_event,
    create_oracle_event
)
from ghost_tools.integration.decision_engine import (
    get_decision_engine, reset_decision_engine
)
from ghost_tools.integration.unified_index import (
    get_unified_index, reset_unified_index, IndexedEvent, IndexedDecision
)
from ghost_tools.integration.cross_repo import CrossRepoManager
from ghost_tools.integration.cicd_integration import (
    TestResult, PerformanceMetric, get_cicd_engine, reset_cicd_engine
)


def analyze_arbiter_codebase() -> dict:
    """Analyze arbiter codebase."""
    root = Path("/home/user/arbiter")

    py_files = list(root.rglob("*.py"))
    test_files = [f for f in py_files if "test" in f.name]
    src_files = [f for f in py_files if "arbiter_os" in str(f)]

    stats = {
        "total_python_files": len(py_files),
        "test_files": len(test_files),
        "source_files": len(src_files),
        "scan_timestamp": datetime.now().isoformat(),
    }

    # Count lines of code
    total_lines = 0
    for f in src_files:
        try:
            with open(f) as file:
                total_lines += len(file.readlines())
        except (OSError, UnicodeDecodeError):
            pass

    stats["total_lines_of_code"] = total_lines

    # Count test lines
    test_lines = 0
    for f in test_files:
        try:
            with open(f) as file:
                test_lines += len(file.readlines())
        except (OSError, UnicodeDecodeError):
            pass

    stats["total_test_lines"] = test_lines

    return stats


def run_arbiter_tests() -> dict:
    """Run tests in arbiter."""
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "Tests/", "-v", "--tb=short"],
            cwd="/home/user/arbiter",
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Parse pytest output for summary
        lines = result.stdout.split("\n")
        summary_line = [l for l in lines if "passed" in l or "failed" in l]

        return {
            "exit_code": result.returncode,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
            "summary": summary_line[-1] if summary_line else "No summary found",
        }
    except Exception as e:
        return {
            "error": str(e),
            "exit_code": -1,
        }


def run_analysis():
    """Run comprehensive Ghost Tools analysis on Arbiter."""
    print("=" * 80)
    print("GHOST TOOLS ANALYSIS: ARBITER REPOSITORY")
    print("=" * 80)
    print()

    # Reset systems
    reset_event_bus()
    reset_decision_engine()
    reset_unified_index()
    reset_cicd_engine()

    # Analyze codebase
    print("[*] Analyzing Arbiter codebase...")
    codebase_stats = analyze_arbiter_codebase()

    print(f"  • Total Python files: {codebase_stats['total_python_files']}")
    print(f"  • Source files: {codebase_stats['source_files']}")
    print(f"  • Test files: {codebase_stats['test_files']}")
    print(f"  • Lines of code: {codebase_stats['total_lines_of_code']}")
    print(f"  • Lines of tests: {codebase_stats['total_test_lines']}")
    print()

    # Run tests
    print("[*] Running Arbiter test suite...")
    test_results = run_arbiter_tests()
    print(f"  • Exit code: {test_results['exit_code']}")
    print(f"  • Summary: {test_results['summary']}")
    print()

    # Generate events from analysis
    print("[*] Generating integration events...")
    event_bus = get_event_bus()

    # Create oracle event for successful analysis
    oracle_event = create_oracle_event(
        finding_type="codebase_analysis",
        accuracy=0.95,
        training_size=codebase_stats['total_python_files'],
        improvement_percent=5.0
    )
    event_bus.publish(oracle_event)

    # Create integration ready event
    import uuid
    integration_event = Event(
        id=str(uuid.uuid4()),
        type=EventType.INTEGRATION_READY,
        severity=EventSeverity.INFO,
        timestamp=datetime.now().isoformat(),
        source_tool="ghost_tools",
        target_tool="swizzle",
        data={
            "source": "arbiter",
            "description": f"Arbiter: {codebase_stats['total_lines_of_code']} LOC, {codebase_stats['total_test_lines']} test lines",
            "loc": codebase_stats['total_lines_of_code'],
            "test_loc": codebase_stats['total_test_lines'],
            "file_count": codebase_stats['total_python_files'],
        }
    )
    event_bus.publish(integration_event)

    print(f"  • Events published: 2")
    print()

    # Run decision engine
    print("[*] Running decision engine on events...")
    decision_engine = get_decision_engine()

    # Process events through decision engine
    decisions = []
    unprocessed_events = event_bus.get_unprocessed()
    for event in unprocessed_events:
        decision = decision_engine.make_decision(event)
        if decision:
            decisions.append(decision)

    print(f"  • Decisions made: {len(decisions)}")
    print()

    # Unified index analysis
    print("[*] Analyzing unified index...")
    unified_index = get_unified_index()

    print(f"  • Indexed events: {len(unified_index.events)}")
    print(f"  • Indexed decisions: {len(unified_index.decisions)}")
    print()

    # Generate report
    print("=" * 80)
    print("ANALYSIS REPORT")
    print("=" * 80)
    print()

    print("CODEBASE METRICS")
    print("-" * 80)
    print(f"Total Python Files: {codebase_stats['total_python_files']}")
    print(f"Source Files: {codebase_stats['source_files']}")
    print(f"Test Files: {codebase_stats['test_files']}")
    print(f"Lines of Code: {codebase_stats['total_lines_of_code']}")
    print(f"Lines of Tests: {codebase_stats['total_test_lines']}")
    print(f"Test to Code Ratio: {codebase_stats['total_test_lines'] / max(1, codebase_stats['total_lines_of_code']):.2f}")
    print()

    print("TEST RESULTS")
    print("-" * 80)
    print(f"Status: {'PASSED' if test_results['exit_code'] == 0 else 'FAILED'}")
    print(f"Summary: {test_results['summary']}")
    print()

    print("INTEGRATION ANALYSIS")
    print("-" * 80)
    print(f"Events Processed: {len(unified_index.events)}")
    print(f"Decisions Generated: {len(unified_index.decisions)}")
    print()

    # Export JSON
    print("EXPORTING ANALYSIS DATA")
    print("-" * 80)

    export_data = {
        "timestamp": datetime.now().isoformat(),
        "repository": "arbiter",
        "codebase_stats": codebase_stats,
        "test_results": {
            "exit_code": test_results['exit_code'],
            "status": "PASSED" if test_results['exit_code'] == 0 else "FAILED",
        },
        "integration_metrics": {
            "events_processed": len(unified_index.events),
            "decisions_generated": len(unified_index.decisions),
        },
    }

    export_file = Path("/tmp/arbiter_analysis.json")
    with open(export_file, "w") as f:
        json.dump(export_data, f, indent=2)

    print(f"Analysis exported to: {export_file}")
    print()

    print("=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_analysis()
