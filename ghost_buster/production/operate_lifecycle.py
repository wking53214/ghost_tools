"""Operate lifecycle — no inspect→delete shortcut."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

class LifecyclePhase(str, Enum):
    INSPECT = "INSPECT"
    CLASSIFY = "CLASSIFY"
    PROPOSE = "PROPOSE"
    ADVERSARIAL_REVIEW = "ADVERSARIAL_REVIEW"
    HUMAN_AUTHORIZATION = "HUMAN_AUTHORIZATION"
    OPERATE = "OPERATE"
    REINSPECT = "REINSPECT"
    DIFFERENTIAL_TEST = "DIFFERENTIAL_TEST"
    RECORD = "RECORD"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DEFER = "DEFER"

@dataclass
class PhaseRecord:
    phase: LifecyclePhase
    timestamp: str
    result: str
    details: Dict[str, Any] = field(default_factory=dict)

class OperateLifecycle:
    def __init__(self):
        self.history: List[PhaseRecord] = []
        self._authorized = False
        self._adversarial_ok = False
    def _require_prior(self, needed):
        if needed not in {r.phase for r in self.history}:
            raise RuntimeError(f"Required prior phase {needed.value} not completed")
    def inspect(self, result="ok", details=None):
        self.history.append(PhaseRecord(LifecyclePhase.INSPECT, datetime.now(timezone.utc).isoformat(), result, details or {}))
    def classify(self, result="ok", details=None):
        self._require_prior(LifecyclePhase.INSPECT)
        self.history.append(PhaseRecord(LifecyclePhase.CLASSIFY, datetime.now(timezone.utc).isoformat(), result, details or {}))
    def propose(self, result="ok", details=None):
        self._require_prior(LifecyclePhase.CLASSIFY)
        self.history.append(PhaseRecord(LifecyclePhase.PROPOSE, datetime.now(timezone.utc).isoformat(), result, details or {}))
    def adversarial_review(self, passed, details=None):
        self._require_prior(LifecyclePhase.PROPOSE)
        self._adversarial_ok = passed
        self.history.append(PhaseRecord(LifecyclePhase.ADVERSARIAL_REVIEW, datetime.now(timezone.utc).isoformat(),
                                        "PASSED" if passed else "FAILED", details or {}))
    def human_authorization(self, granted, actor, details=None):
        self._require_prior(LifecyclePhase.ADVERSARIAL_REVIEW)
        if not self._adversarial_ok and granted:
            raise RuntimeError("Cannot authorize: adversarial review did not pass")
        self._authorized = granted
        self.history.append(PhaseRecord(LifecyclePhase.HUMAN_AUTHORIZATION, datetime.now(timezone.utc).isoformat(),
                                        "GRANTED" if granted else "DENIED", {**(details or {}), "actor": actor}))
    def operate(self, result="ok", details=None):
        self._require_prior(LifecyclePhase.HUMAN_AUTHORIZATION)
        if not self._authorized:
            raise RuntimeError("REFUSED: no human authorization")
        self.history.append(PhaseRecord(LifecyclePhase.OPERATE, datetime.now(timezone.utc).isoformat(), result, details or {}))
    def reinspect(self, result="ok", details=None):
        self._require_prior(LifecyclePhase.OPERATE)
        self.history.append(PhaseRecord(LifecyclePhase.REINSPECT, datetime.now(timezone.utc).isoformat(), result, details or {}))
    def differential_test(self, result="ok", details=None):
        self._require_prior(LifecyclePhase.REINSPECT)
        self.history.append(PhaseRecord(LifecyclePhase.DIFFERENTIAL_TEST, datetime.now(timezone.utc).isoformat(), result, details or {}))
    def record(self, result="ok", details=None):
        self._require_prior(LifecyclePhase.DIFFERENTIAL_TEST)
        self.history.append(PhaseRecord(LifecyclePhase.RECORD, datetime.now(timezone.utc).isoformat(), result, details or {}))
    def finalize(self, decision):
        decision = decision.upper()
        if decision not in ("ACCEPT", "REJECT", "DEFER"):
            raise ValueError("decision must be ACCEPT, REJECT, or DEFER")
        self.history.append(PhaseRecord(LifecyclePhase[decision], datetime.now(timezone.utc).isoformat(), decision, {}))
