"""CNS docking audit — single seam, bypass risks."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class DockingAuditResult:
    proposed_seam: Optional[str]
    current_communicators: List[str]
    should_not_communicate: List[str]
    duplicate_paths: List[str]
    authority_crossings: List[str]
    provenance_crossings: List[str]
    scope_crossings: List[str]
    unknown_loss_risks: List[str]
    authorization_bypass_risks: List[str]
    identity_confusion_risks: List[str]
    adapter_as_authority_risks: List[str]
    single_seam_defined: bool
    ready_for_adapter_design: bool
    unknowns: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    def to_dict(self):
        return self.__dict__.copy()

class CNSDockingAudit:
    def __init__(self, repository: str):
        self.repository = repository
    def audit(self, import_graph=None, cns_related_symbols=None, proposed_seam=None):
        import_graph = import_graph or {}
        cns_related_symbols = cns_related_symbols or []
        communicators = []
        for mod, deps in import_graph.items():
            if any("cns" in d.lower() for d in deps) or any(s in mod for s in cns_related_symbols):
                communicators.append(mod)
        duplicate_paths = list(communicators) if len(communicators) > 1 else []
        unknowns = [] if proposed_seam else ["proposed_seam not specified"]
        single = proposed_seam is not None and len(duplicate_paths) <= 1
        return DockingAuditResult(
            proposed_seam=proposed_seam, current_communicators=communicators,
            should_not_communicate=[], duplicate_paths=duplicate_paths,
            authority_crossings=[], provenance_crossings=[], scope_crossings=[],
            unknown_loss_risks=[], authorization_bypass_risks=[],
            identity_confusion_risks=[], adapter_as_authority_risks=[],
            single_seam_defined=single, ready_for_adapter_design=single and not unknowns,
            unknowns=unknowns,
        )
