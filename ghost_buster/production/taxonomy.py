"""Repository-state taxonomy. Zero static refs = DEAD_CANDIDATE, not DEAD."""
from __future__ import annotations

from enum import Enum


class RepositoryStateClass(str, Enum):
    ACTIVE = "ACTIVE"
    REQUIRED = "REQUIRED"
    REDUNDANT = "REDUNDANT"
    DEAD = "DEAD"
    DEAD_CANDIDATE = "DEAD_CANDIDATE"
    ABANDONED_DEAD_END = "ABANDONED_DEAD_END"
    CONFLICTING = "CONFLICTING"
    OBSOLETE = "OBSOLETE"
    CNS_INCOMPATIBLE = "CNS_INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"

def classify_finding(static_ref_count, dynamic_ref_possible, has_tests, documented_as_required,
                     conflicts_with=None, obsolete_marker=False, cns_leak=False):
    if cns_leak:
        return RepositoryStateClass.CNS_INCOMPATIBLE
    if conflicts_with:
        return RepositoryStateClass.CONFLICTING
    if obsolete_marker:
        return RepositoryStateClass.OBSOLETE
    if documented_as_required or has_tests:
        return RepositoryStateClass.REQUIRED if documented_as_required else RepositoryStateClass.ACTIVE
    if static_ref_count == 0:
        return RepositoryStateClass.DEAD_CANDIDATE
    if static_ref_count > 0:
        return RepositoryStateClass.ACTIVE
    return RepositoryStateClass.UNKNOWN
