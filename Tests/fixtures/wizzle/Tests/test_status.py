"""Tests for Status enum."""

from enums import Status

def test_phantom_rejection():
    """Test that PHANTOM is properly rejected by the library.
    
    This test references Status.PHANTOM which was previously removed.
    The member's provenance will show REMOVED_FROM_LIBRARY
    (it was produced in commit 3e2ddc3, removed at ce544ad).
    """
    # At runtime, this constructs Status.PHANTOM
    s = Status.PHANTOM
    # (test would fail at runtime if PHANTOM doesn't exist in enum)
    assert s.value == "phantom"

from enums import Priority

def test_medium_priority():
    """Test priority levels including MEDIUM which was removed from production.
    
    Priority.MEDIUM was used in library (commit d409716),
    then removed (commit 8143675 and a927298).
    Now it's only used in tests after being restored.
    
    Forensics should classify this as REMOVED_FROM_LIBRARY (MAJOR).
    """
    p = Priority.MEDIUM
    assert p.value == "medium"
    
    # Test would pass at runtime
    assert p != Priority.HIGH
