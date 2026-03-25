"""Progress event types for real-time session feedback."""

from dataclasses import dataclass


@dataclass
class ProgressEvent:
    """A single progress event emitted during a session.

    Consumed by renderers (terminal, JSON) or adapters (GUI EventBus).

    Valid ``kind`` values::

        session_start, delegate_start, delegate_end,
        delegate_denied, delegate_cached,
        ask_user_start, ask_user_end, session_end

    Valid ``status`` values::

        ok, error, denied, cached, "" (empty for start events)
    """

    kind: str
    role: str  # e.g. "implementer", "code-reviewer"
    detail: str  # human-readable (truncated task text or reason)
    timestamp: str  # ISO 8601 UTC
    duration_ms: int  # 0 for start events, elapsed for end events
    status: str
    depth: int  # delegation depth (0 = orchestrator)
