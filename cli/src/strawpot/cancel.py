"""Agent cancellation types, tree traversal utilities, and file-based cancel signals."""

import json
import logging
import os
import tempfile
from collections import deque
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)


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


# ------------------------------------------------------------------
# File-based cancel signal protocol
# ------------------------------------------------------------------
# Cancel requests are written as JSON files to
# ``.strawpot/sessions/<run_id>/cancel/<agent_id>.json``
# (or ``_run.json`` for run-level cancel).  The session's cancel
# watcher thread picks them up, triggers ``cancel_agent()``, and
# renames them to ``.done``.


def cancel_dir(session_dir: str) -> str:
    """Return the cancel signal directory for a session."""
    return os.path.join(session_dir, "cancel")


def write_cancel_signal(
    session_dir: str,
    agent_id: str | None,
    *,
    force: bool = False,
    requested_by: str = "cli",
) -> Path:
    """Write a cancel signal file for the session watcher to pick up.

    Args:
        session_dir: Path to ``.strawpot/sessions/<run_id>/``.
        agent_id: Agent to cancel, or ``None`` to cancel the entire run.
        force: Skip graceful shutdown.
        requested_by: Origin of the cancel request (``"cli"`` or ``"gui"``).

    Returns:
        Path to the written signal file.
    """
    cdir = cancel_dir(session_dir)
    os.makedirs(cdir, exist_ok=True)

    filename = f"{agent_id}.json" if agent_id else "_run.json"
    signal_path = os.path.join(cdir, filename)

    data = {
        "agent_id": agent_id,
        "force": force,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "requested_by": requested_by,
    }

    # Atomic write: write to temp file, then rename.
    fd, tmp_path = tempfile.mkstemp(dir=cdir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, signal_path)
    except Exception:
        # Clean up temp file on failure.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return Path(signal_path)


def read_cancel_signals(session_dir: str) -> list[dict]:
    """Read pending cancel signal files from the cancel directory.

    Returns a list of parsed signal dicts.  Each dict includes
    ``"_path"`` with the file path for renaming after processing.
    """
    cdir = cancel_dir(session_dir)
    if not os.path.isdir(cdir):
        return []

    signals: list[dict] = []
    for entry in os.listdir(cdir):
        if not entry.endswith(".json"):
            continue
        path = os.path.join(cdir, entry)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data["_path"] = path
            signals.append(data)
        except (json.JSONDecodeError, OSError):
            logger.debug("Skipping malformed cancel signal: %s", path)
    return signals


def mark_signal_done(signal_path: str) -> None:
    """Rename a processed signal file to ``.done``."""
    done_path = signal_path.replace(".json", ".done")
    try:
        os.replace(signal_path, done_path)
    except OSError:
        logger.debug("Failed to rename signal to .done: %s", signal_path)
