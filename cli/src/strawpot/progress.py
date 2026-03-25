"""Progress event types and renderers for real-time session feedback."""

import json
import logging
import sys
import threading
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)


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


def _format_duration(ms: int) -> str:
    """Format milliseconds as a human-readable duration string.

    Returns e.g. ``"12s"`` for < 60 s, ``"2m 47s"`` for >= 60 s.
    """
    seconds = ms // 1000
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    remaining = seconds % 60
    return f"{minutes}m {remaining}s"


class _BaseRenderer:
    """Thread-safe, BrokenPipeError-safe base for progress renderers.

    Subclasses implement ``_render(event)`` to produce output.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._disabled = False

    def handle_event(self, event: ProgressEvent) -> None:
        """Callback for ``Session.on_event``."""
        if self._disabled:
            return
        with self._lock:
            try:
                self._render(event)
            except Exception:
                logger.debug("Renderer failed, disabling", exc_info=True)
                self._disabled = True

    def _render(self, event: ProgressEvent) -> None:
        raise NotImplementedError


class TerminalProgressRenderer(_BaseRenderer):
    """Renders ProgressEvents as checkmark lines to stderr."""

    def __init__(self) -> None:
        super().__init__()
        self._is_tty = sys.stderr.isatty()

    def _render(self, event: ProgressEvent) -> None:
        ok = "\u2713" if self._is_tty else "[ok]"
        fail = "\u2717" if self._is_tty else "[FAIL]"
        indent = "  " + "  " * event.depth

        kind = event.kind
        if kind == "session_start":
            line = f"\n{indent}Session started (orchestrator: {event.role})\n"
        elif kind == "delegate_start":
            line = f"\n{indent}> Delegating to {event.role}..."
            self._set_terminal_title(f"StrawPot: {event.role}")
        elif kind == "delegate_end":
            dur = _format_duration(event.duration_ms)
            if event.status == "ok":
                line = f"{indent}{ok} {event.role} completed ({dur})"
            else:
                line = f"{indent}{fail} {event.role} failed ({dur})"
        elif kind == "delegate_denied":
            line = f"{indent}{fail} {event.role} denied: {event.detail}"
        elif kind == "delegate_cached":
            line = f"{indent}{ok} {event.role} (cached)"
        elif kind == "ask_user_start":
            line = f"{indent}? Waiting for user input ({event.role})..."
        elif kind == "ask_user_end":
            dur = _format_duration(event.duration_ms)
            line = f"{indent}{ok} User responded ({dur})"
        elif kind == "session_end":
            dur = _format_duration(event.duration_ms)
            detail_suffix = f" - {event.detail}" if event.detail else ""
            line = f"\n{indent}{ok} Session complete ({dur}){detail_suffix}\n"
            self._clear_terminal_title()
        else:
            return  # unknown event kind — skip silently

        sys.stderr.write(line + "\n")
        sys.stderr.flush()

    def _set_terminal_title(self, title: str) -> None:
        if self._is_tty:
            sys.stderr.write(f"\033]0;{title}\007")

    def _clear_terminal_title(self) -> None:
        self._set_terminal_title("")


class JsonProgressRenderer(_BaseRenderer):
    """Renders ProgressEvents as JSONL to stderr.

    Each event is one JSON object per line.
    """

    def _render(self, event: ProgressEvent) -> None:
        line = json.dumps(asdict(event), separators=(",", ":"))
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
