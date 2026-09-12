"""Production library."""

from enums import Status, Priority

def get_user_status():
    """Return current status."""
    return Status.ACTIVE

def check_if_active(s):
    """Check if a status is active."""
    if s == Status.ACTIVE:
        return True
    return False

def get_default_priority():
    """Return the default priority - HIGH only."""
    return Priority.HIGH
