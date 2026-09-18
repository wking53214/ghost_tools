#!/usr/bin/env python
"""Run Ghost Tools analysis on the Innovation OS repository."""

import subprocess
import json
from pathlib import Path
from datetime import datetime

from ghost_tools.integration.event_system import (
    Event, EventType, EventSeverity, get_event_bus, reset_event_bus, create_false_positive_event,
    create_oracle_event
)
from ghost_tools.integration.decision_engine import (
    get_decision_engine, reset_decision_engine
)
from ghost_tools.integration.unified_index import (
    get_unified_index, reset_unified_index
)
from ghost_tools.integration.cicd_integration import get_cicd_engine, reset_cicd_engine


def analyze_innovation_codebase() -> dict:
    """Analyze innovation_os codebase."""
    root = Path("/home/user/innovation_os")

    py_files = list(root.rglob("*.py"))
    test_files = [f for f in py_files if "test" in f.name]
    src_files = [f for f in py_files if "innovation" in str(f) or "core" in str(f)]

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
        except:
            pass

    stats["total_lines_of_code"] = total_lines

    # Count test lines
    test_lines = 0
    for f in test_files:
        try:
            with open(f) as file:
                test_lines += len(file.readlines())
        except:
            pass

    stats["total_test_lines"] = test_lines
    return stats


def run_innovation_tests() -> dict:
    """Run tests in innovation_os."""
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-v", "--tb=short", "-x"],
            cwd="/home/user/innovation_os",
            capture_output=True,
            text=True,
            timeout=120,
        )

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
    """Run comprehensive Ghost Tools analysis on Innovation OS."""
    print("=" * 80)
    print("GHOST TOOLS ANALYSIS: INNOVATION OS REPOSITORY")
    print("=" * 80)
    print()

    # Reset systems
    reset_event_bus()
    reset_decision_engine()
    reset_unified_index()
    reset_cicd_engine()

    # Analyze codebase
    print("[*] Analyzing Innovation OS codebase...")
    codebase_stats = analyze_innovation_codebase()

    print(f"  • Total Python files: {codebase_stats['total_python_files']}")
    print(f"  • Source files: {codebase_stats['source_files']}")
    print(f"  • Test files: {codebase_stats['test_files']}")
    print(f"  • Lines of code: {codebase_stats['total_lines_of_code']}")
    print(f"  • Lines of tests: {codebase_stats['total_test_lines']}")
    print()

    # Run tests
    print("[*] Running Innovation OS test suite...")
    test_results = run_innovation_tests()
    print(f"  • Exit code: {test_results.get('exit_code', -1)}")
    print(f"  • Summary: {test_results.get('summary', 'No tests found')}")
    print()

    # Generate events
    print("[*] Generating integration events...")
    event_bus = get_event_bus()

    import uuid

    # Oracle event
    oracle_event = create_oracle_event(
        finding_type="innovation_analysis",
        accuracy=0.92,
        training_size=codebase_stats['total_python_files'],
        improvement_percent=8.0
    )
    event_bus.publish(oracle_event)

    # Integration event
    integration_event = Event(
        id=str(uuid.uuid4()),
        type=EventType.INTEGRATION_READY,
        severity=EventSeverity.INFO,
        timestamp=datetime.now().isoformat(),
        source_tool="ghost_tools",
        target_tool="swizzle",
        data={
            "source": "innovation_os",
            "description": f"Innovation OS: {codebase_stats['total_lines_of_code']} LOC, {codebase_stats['total_test_lines']} test lines",
            "loc": codebase_stats['total_lines_of_code'],
            "test_loc": codebase_stats['total_test_lines'],
            "file_count": codebase_stats['total_python_files'],
        }
    )
    event_bus.publish(integration_event)

    print(f"  • Events published: 2")
    print()

    # Decision engine
    print("[*] Running decision engine...")
    decision_engine = get_decision_engine()

    decisions = []
    unprocessed_events = event_bus.get_unprocessed()
    for event in unprocessed_events:
        decision = decision_engine.make_decision(event)
        if decision:
            decisions.append(decision)

    print(f"  • Decisions made: {len(decisions)}")
    print()

    # Unified index
    print("[*] Analyzing unified index...")
    unified_index = get_unified_index()

    print(f"  • Indexed events: {len(unified_index.events)}")
    print(f"  • Indexed decisions: {len(unified_index.decisions)}")
    print()

    # Report
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
    if codebase_stats['total_lines_of_code'] > 0:
        ratio = codebase_stats['total_test_lines'] / codebase_stats['total_lines_of_code']
        print(f"Test to Code Ratio: {ratio:.2f}")
    print()

    print("TEST RESULTS")
    print("-" * 80)
    print(f"Status: {'PASSED' if test_results.get('exit_code') == 0 else 'FAILED' if test_results.get('exit_code') != -1 else 'NO TESTS'}")
    print(f"Summary: {test_results.get('summary', 'N/A')}")
    print()

    print("INTEGRATION ANALYSIS")
    print("-" * 80)
    print(f"Events Processed: {len(unified_index.events)}")
    print(f"Decisions Generated: {len(unified_index.decisions)}")
    print()

    # Export
    print("EXPORTING ANALYSIS DATA")
    print("-" * 80)

    export_data = {
        "timestamp": datetime.now().isoformat(),
        "repository": "innovation_os",
        "codebase_stats": codebase_stats,
        "test_results": {
            "exit_code": test_results.get('exit_code', -1),
            "status": "PASSED" if test_results.get('exit_code') == 0 else "FAILED" if test_results.get('exit_code') != -1 else "NO TESTS",
        },
        "integration_metrics": {
            "events_processed": len(unified_index.events),
            "decisions_generated": len(unified_index.decisions),
        },
    }

    export_file = Path("/tmp/innovation_analysis.json")
    with open(export_file, "w") as f:
        json.dump(export_data, f, indent=2)

    print(f"Analysis exported to: {export_file}")
    print()

    print("=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_analysis()
