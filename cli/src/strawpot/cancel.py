"""Agent cancellation types and tree traversal utilities."""

from enum import StrEnum


class AgentState(StrEnum):
    """Lifecycle state of an agent in a session."""

    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class CancelReason(StrEnum):
    """Why an agent was cancelled."""

    USER = "user"  # Explicit user cancel (CLI/GUI)
    PARENT = "parent"  # Parent was cancelled
    ANCESTOR = "ancestor"  # Ancestor was cancelled (grandparent+)
    TIMEOUT = "timeout"  # Delegation timeout
