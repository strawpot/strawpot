"""Tests for the global SSE event bus integration.

The /api/events endpoint is a long-lived SSE stream that blocks waiting
for events, so it cannot be tested with the synchronous TestClient.
Instead we test the SSE formatting and event bus independently.
"""

from strawpot_gui.event_bus import SessionEvent
from strawpot_gui.sse import format_sse_typed


class TestFormatSSETyped:
    def test_format_includes_event_type(self):
        result = format_sse_typed(1, "session_started", {"run_id": "r1"})
        assert "event: session_started" in result
        assert "id: 1" in result
        assert '"run_id":"r1"' in result

    def test_different_event_types(self):
        for kind in ("session_started", "session_completed", "session_failed", "session_stopped"):
            result = format_sse_typed(1, kind, {"run_id": "r1"})
            assert f"event: {kind}" in result


class TestSessionEventModel:
    def test_defaults(self):
        event = SessionEvent(kind="session_started", run_id="r1")
        assert event.project_id is None
        assert event.data == {}

    def test_with_project_id(self):
        event = SessionEvent(kind="session_started", run_id="r1", project_id=42)
        assert event.project_id == 42
