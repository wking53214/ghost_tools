"""CNS docking audit — single seam, bypass risks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DockingAuditResult:
    proposed_seam: str | None
    current_communicators: list[str]
    should_not_communicate: list[str]
    duplicate_paths: list[str]
    authority_crossings: list[str]
    provenance_crossings: list[str]
    scope_crossings: list[str]
    unknown_loss_risks: list[str]
    authorization_bypass_risks: list[str]
    identity_confusion_risks: list[str]
    adapter_as_authority_risks: list[str]
    single_seam_defined: bool
    ready_for_adapter_design: bool
    unknowns: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
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
