"""Agent cancellation types and tree traversal utilities."""

from collections import deque
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


# ------------------------------------------------------------------
# Agent tree traversal utilities
# ------------------------------------------------------------------
# Pure functions that operate on the ``agent_info`` dict (same
# structure as ``Session._agent_info``).  Keeping them as free
# functions rather than Session methods makes them easy to test
# without session machinery.

_MAX_ITERATIONS = 100  # Defensive cap to prevent infinite loops on cycles


def get_children(agent_id: str, agent_info: dict[str, dict]) -> list[str]:
    """Return direct children of *agent_id*."""
    return [
        aid for aid, info in agent_info.items()
        if info.get("parent") == agent_id
    ]


def get_descendants(agent_id: str, agent_info: dict[str, dict]) -> list[str]:
    """Return all descendants of *agent_id* in BFS (top-down) order.

    Does **not** include *agent_id* itself.
    """
    result: list[str] = []
    queue: deque[str] = deque(get_children(agent_id, agent_info))
    seen: set[str] = set()
    iterations = 0
    while queue and iterations < _MAX_ITERATIONS:
        iterations += 1
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        result.append(current)
        queue.extend(get_children(current, agent_info))
    return result


def get_subtree_bottom_up(agent_id: str, agent_info: dict[str, dict]) -> list[str]:
    """Return descendants in bottom-up order (leaves first) for cascading cancel.

    Does **not** include *agent_id* itself.  This is the order in which
    agents should be cancelled to avoid orphans.
    """
    top_down = get_descendants(agent_id, agent_info)
    return list(reversed(top_down))


def is_ancestor_of(
    candidate: str, agent_id: str, agent_info: dict[str, dict]
) -> bool:
    """Check if *candidate* is an ancestor of *agent_id*.

    Traverses the parent chain from *agent_id* upward.  Returns
    ``False`` if *candidate* == *agent_id*.
    """
    current = agent_id
    iterations = 0
    while iterations < _MAX_ITERATIONS:
        iterations += 1
        info = agent_info.get(current, {})
        parent = info.get("parent")
        if not parent:
            return False
        if parent == candidate:
            return True
        current = parent
    return False
