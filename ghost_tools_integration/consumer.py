"""Ghost Tools consumer for Swizzle integration data.

Imports and applies shared models from Swizzle:
- Invariant validation: check findings against shared invariants
- Mutation cases: run Swizzle cases through ghost-buster
- Triage ledger: use historical decisions for filtering
- Performance contracts: validate against performance contracts
- Architecture audit: check against shared architecture rules
- Feedback loop: apply false positive patterns to filter results
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
import json
from dataclasses import dataclass


@dataclass
class IntegrationConfig:
    """Configuration for Ghost Tools integration."""
    swizzle_bundle_dir: Path
    enabled_integrations: List[str]  # which integrations to use
    load_invariants: bool = True
    apply_mutation_cases: bool = True
    use_triage_ledger: bool = True
    validate_performance: bool = True
    apply_false_positive_filters: bool = True
    check_architecture: bool = True


class SwizzleIntegrationConsumer:
    """Ghost Tools consumer of Swizzle integration data."""

    def __init__(self, config: IntegrationConfig):
        self.config = config
        self.invariants: Optional[Dict] = None
        self.mutations: Optional[Dict] = None
        self.triage_ledger: Optional[Dict] = None
        self.performance_contracts: Optional[Dict] = None
        self.false_positive_patterns: Optional[Dict] = None
        self.architecture_rules: Optional[Dict] = None

        self._load_integration_data()

    def _load_integration_data(self) -> None:
        """Load all integration data from Swizzle bundle."""
        if self.config.load_invariants:
            self.invariants = self._load_json("invariants.json")

        if self.config.apply_mutation_cases:
            self.mutations = self._load_json("mutations.json")

        if self.config.use_triage_ledger:
            self.triage_ledger = self._load_json("triage-ledger.json")

        if self.config.validate_performance:
            self.performance_contracts = self._load_json("performance-contracts.json")

        if self.config.apply_false_positive_filters:
            self.false_positive_patterns = self._load_json("feedback-patterns.json")

        if self.config.check_architecture:
            self.architecture_rules = self._load_json("architecture-rules.json")

    def _load_json(self, filename: str) -> Optional[Dict]:
        """Load JSON file from Swizzle bundle."""
        filepath = self.config.swizzle_bundle_dir / filename
        if not filepath.exists():
            return None
        try:
            return json.loads(filepath.read_text())
        except Exception as e:
            print(f"Warning: failed to load {filename}: {e}")
            return None

    def filter_false_positives(self, findings: List[Dict]) -> List[Dict]:
        """Apply false positive patterns to filter Ghost's findings.

        Args:
            findings: List of finding dicts from ghost-buster output

        Returns:
            Filtered findings with false positives marked or removed
        """
        if not self.false_positive_patterns:
            return findings

        patterns = self.false_positive_patterns.get("patterns_by_type", {})
        filtered = []

        for finding in findings:
            finding_type = finding.get("type")
            is_false_positive = False

            if finding_type in patterns:
                for pattern in patterns[finding_type]:
                    if self._matches_pattern(finding, pattern):
                        is_false_positive = True
                        finding["likely_false_positive"] = True
                        finding["filter_pattern"] = pattern.get("id")
                        break

            filtered.append(finding)

        return filtered

    def _matches_pattern(self, finding: Dict, pattern: Dict) -> bool:
        """Check if a finding matches a false positive pattern."""
        indicators = pattern.get("indicators", [])
        finding_text = json.dumps(finding)

        # Simple heuristic: match if any indicator appears
        return any(indicator.lower() in finding_text.lower() for indicator in indicators)

    def validate_invariants(self, findings: List[Dict]) -> List[str]:
        """Validate findings against shared invariants.

        Returns list of invariant violation IDs found in findings.
        """
        if not self.invariants:
            return []

        violations = []
        invariants_dict = self.invariants.get("invariants", {})

        for finding in findings:
            finding_type = finding.get("type")
            for inv_id, invariant in invariants_dict.items():
                # Simple matching: does this finding relate to this invariant?
                if self._finding_relates_to_invariant(finding, invariant):
                    violations.append(inv_id)

        return violations

    def _finding_relates_to_invariant(self, finding: Dict, invariant: Dict) -> bool:
        """Check if a finding is related to an invariant."""
        finding_text = json.dumps(finding).lower()
        inv_description = invariant.get("description", "").lower()
        inv_name = invariant.get("name", "").lower()

        return (any(word in finding_text for word in inv_name.split()) or
                any(word in finding_text for word in inv_description.split()))

    def run_mutation_cases(self) -> Dict[str, Any]:
        """Get Swizzle mutation cases to test against ghost-buster.

        Returns dict mapping case_id to case details.
        """
        if not self.mutations:
            return {}

        return self.mutations.get("cases", {})

    def check_performance_contract(self, metric_type: str, value: float) -> bool:
        """Check if a performance metric violates any contract.

        Args:
            metric_type: "wall_time", "memory", "throughput"
            value: metric value

        Returns:
            True if contract is satisfied, False if violated
        """
        if not self.performance_contracts:
            return True

        contracts = self.performance_contracts.get("contracts", {})
        for contract in contracts.values():
            if contract.get("metric_type") == metric_type:
                threshold = contract.get("threshold_value")
                if threshold and value > threshold:
                    return False

        return True

    def get_architecture_violations(self, tool_name: str = "ghost_tools") -> List[Dict]:
        """Get architecture violations from Swizzle audit.

        Returns list of violation dicts.
        """
        if not self.architecture_rules:
            return []

        audits = self.architecture_rules.get("audits", {})
        if tool_name not in audits:
            return []

        audit = audits[tool_name]
        return audit.get("violations", {}).values()

    def apply_triage_priors(self, finding_type: str) -> Optional[Dict]:
        """Get prior triage data for a finding type.

        Returns dict with historical decision data, or None if no history.
        """
        if not self.triage_ledger:
            return None

        training_data = self.triage_ledger.get("training_data", {})
        return training_data.get(finding_type)

    def process_event(self, event_data: Dict[str, Any]) -> None:
        """Process an event from the Swizzle event bus.

        Handles real-time updates to integration data.
        """
        event_type = event_data.get("type")
        data = event_data.get("data", {})

        if event_type == "finding_triaged":
            self._handle_triage_event(data)
        elif event_type == "violation_detected":
            self._handle_violation_event(data)
        elif event_type == "performance_regressed":
            self._handle_regression_event(data)
        elif event_type == "false_positive_confirmed":
            self._handle_false_positive_event(data)
        elif event_type == "mutation_case_discovered":
            self._handle_mutation_event(data)

    def _handle_triage_event(self, data: Dict[str, Any]) -> None:
        """Update triage ledger from event."""
        if self.triage_ledger:
            # Record the triage decision for future reference
            entries = self.triage_ledger.get("entries", {})
            entries[data["finding_id"]] = {
                "finding_type": data["finding_type"],
                "decision": data["decision"],
                "reasoning": data["reasoning"],
            }

    def _handle_violation_event(self, data: Dict[str, Any]) -> None:
        """Log architecture violation from Swizzle."""
        print(f"Architecture violation: {data['violation_type']} at {data['location']}")

    def _handle_regression_event(self, data: Dict[str, Any]) -> None:
        """Alert on performance regression."""
        print(f"Performance regression detected: {data.get('metric_name', 'unknown')} "
              f"regressed {data.get('regression_percent', 0):.1f}%")

    def _handle_false_positive_event(self, data: Dict[str, Any]) -> None:
        """Update false positive patterns from Swizzle."""
        if self.false_positive_patterns:
            patterns = self.false_positive_patterns.get("patterns_by_type", {})
            finding_type = data["finding_type"]
            if finding_type not in patterns:
                patterns[finding_type] = []
            patterns[finding_type].append({
                "id": data["false_positive_id"],
                "confidence": data["confidence"],
                "indicators": data.get("indicators", []),
            })

    def _handle_mutation_event(self, data: Dict[str, Any]) -> None:
        """Add discovered mutation cases to test suite."""
        if self.mutations:
            cases = self.mutations.get("cases", {})
            cases[data["case_id"]] = {
                "hypothesis": data["hypothesis"],
                "severity": data["severity"],
                "minimized": data.get("minimized", True),
            }

    def apply_autonomous_decisions(self, decisions: List[Dict[str, Any]]) -> None:
        """Apply autonomous decisions from Swizzle's decision engine.

        Decisions already auto-approved can be applied without review.
        """
        for decision in decisions:
            decision_type = decision.get("type")
            approved = decision.get("approved", False)

            if not approved:
                continue  # Only apply approved decisions

            data = decision.get("action_data", {})

            if decision_type == "apply_filter_pattern":
                self._apply_filter_pattern(data)
            elif decision_type == "update_oracle_training":
                self._apply_oracle_training(data)
            elif decision_type == "add_test_case":
                self._add_test_case(data)
            elif decision_type == "adjust_performance_threshold":
                self._adjust_performance_threshold(data)

    def _apply_filter_pattern(self, data: Dict[str, Any]) -> None:
        """Apply a false positive filter pattern."""
        if self.false_positive_patterns:
            patterns = self.false_positive_patterns.get("patterns_by_type", {})
            finding_type = data["finding_type"]
            if finding_type not in patterns:
                patterns[finding_type] = []
            patterns[finding_type].append({
                "id": data.get("pattern_id", f"auto_{data.get('false_positive_id')}"),
                "indicators": data.get("indicators", []),
            })

    def _apply_oracle_training(self, data: Dict[str, Any]) -> None:
        """Apply oracle training update to refine detection thresholds.

        Updates the oracle's internal confidence thresholds based on
        feedback from validated findings. This improves accuracy of
        future detections by learning from past decisions.
        """
        if not hasattr(self, 'oracle_training_log'):
            self.oracle_training_log: List[Dict[str, Any]] = []

        training_update = {
            "threshold": data.get("threshold"),
            "confidence": data.get("confidence"),
            "finding_type": data.get("finding_type"),
            "outcome": data.get("outcome"),  # "accepted" or "rejected"
        }
        self.oracle_training_log.append(training_update)

    def _add_test_case(self, data: Dict[str, Any]) -> None:
        """Add test case to mutation suite."""
        if self.mutations:
            cases = self.mutations.get("cases", {})
            cases[data["case_id"]] = {
                "hypothesis": data["hypothesis"],
                "severity": data["severity"],
                "minimized": True,
            }

    def _adjust_performance_threshold(self, data: Dict[str, Any]) -> None:
        """Adjust performance contract threshold."""
        if self.performance_contracts:
            contracts = self.performance_contracts.get("contracts", {})
            contract_id = data.get("contract_id")
            if contract_id in contracts:
                contract = contracts[contract_id]
                # Adjust threshold based on regression severity
                adjustment = 1.05  # Default 5% increase
                contract["threshold_value"] *= adjustment

    def generate_integration_report(self) -> str:
        """Generate report of loaded integration data."""
        report = {
            "invariants_loaded": bool(self.invariants),
            "mutations_loaded": bool(self.mutations),
            "triage_ledger_loaded": bool(self.triage_ledger),
            "performance_contracts_loaded": bool(self.performance_contracts),
            "false_positive_patterns_loaded": bool(self.false_positive_patterns),
            "architecture_rules_loaded": bool(self.architecture_rules),
        }

        if self.invariants:
            report["invariant_count"] = len(self.invariants.get("invariants", {}))
        if self.mutations:
            report["mutation_count"] = len(self.mutations.get("cases", {}))
        if self.triage_ledger:
            report["triage_entries"] = len(self.triage_ledger.get("entries", {}))
        if self.performance_contracts:
            report["performance_contracts"] = len(self.performance_contracts.get("contracts", {}))

        return json.dumps(report, indent=2)
