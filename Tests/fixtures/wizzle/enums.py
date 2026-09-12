"""Enumeration module."""

from enum import Enum

class Status(str, Enum):
    """Status values used in the application."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PHANTOM = "phantom"

class Priority(Enum):
    """Priority levels."""
    HIGH = "high"
    MEDIUM = "medium"
