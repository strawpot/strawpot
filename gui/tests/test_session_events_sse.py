"""Integration tests for the SSE trace events endpoint."""

import json

from test_sessions_sync import _register_project, _write_session, _write_trace

from strawpot_gui.db import sync_sessions


def _parse_sse_named_events(body: str) -> list[tuple[str, dict]]:
    """Parse SSE events with event types.

    Returns a list of (event_type, data) tuples.
    Handles both named events (``event: snapshot``) and unnamed events
    (default type ``message``).
    """
    events = []
    current_type = "message"
    for line in body.splitlines():
        if line.startswith("event: "):
            current_type = line[7:].strip()
        elif line.startswith("data: "):
            try:
                events.append((current_type, json.loads(line[6:])))
            except json.JSONDecodeError:
                pass
            current_type = "message"  # reset for next event
    return events


def _parse_sse_events(body: str) -> list[dict]:
    """Parse SSE data events (ignoring event types)."""
    return [data for _, data in _parse_sse_named_events(body)]


class TestTraceSSETerminalSession:
    """Tests for completed/failed sessions — batch events then close."""

    def test_completed_session_returns_all_events(self, client, tmp_path):
        """Completed session sends all trace events as a snapshot and closes."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        trace_events = [
            {"ts": "T1", "event": "session_start", "trace_id": "run_ev1",
             "span_id": "s0", "data": {"run_id": "run_ev1"}},
            {"ts": "T2", "event": "delegate_start", "trace_id": "run_ev1",
             "span_id": "s1", "parent_span": "s0",
             "data": {"role": "implementer"}},
            {"ts": "T3", "event": "session_end", "trace_id": "run_ev1",
             "span_id": "s0", "data": {"duration_ms": 5000}},
        ]

        session_dir = _write_session(project_dir, "run_ev1", archived=True)
        _write_trace(session_dir, trace_events)

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_ev1/events")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        named_events = _parse_sse_named_events(resp.text)
        assert len(named_events) >= 1

        event_type, data = named_events[0]
        assert event_type == "snapshot"
        assert "events" in data
        assert len(data["events"]) == 3
        assert data["events"][0]["event"] == "session_start"
        assert data["events"][2]["event"] == "session_end"

    def test_empty_trace_sends_no_events(self, client, tmp_path):
        """Session with no trace events sends nothing and closes."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        _write_session(project_dir, "run_ev2", archived=True)
        # No _write_trace — trace.jsonl doesn't exist

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_ev2/events")
        assert resp.status_code == 200

        sse_messages = _parse_sse_events(resp.text)
        # No data events (only retry directive)
        assert len(sse_messages) == 0


class TestTraceSSENotFound:
    def test_unknown_session_returns_404(self, client):
        """Non-existent session returns 404."""
        resp = client.get("/api/sessions/run_nonexistent/events")
        assert resp.status_code == 404


class TestTraceSSEActiveSession:
    def test_active_session_with_session_end_terminates(self, client, tmp_path):
        """Active session whose trace has session_end terminates SSE stream."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_ev3")
        _write_trace(session_dir, [
            {"ts": "T1", "event": "session_start", "trace_id": "run_ev3",
             "span_id": "s0", "data": {}},
            {"ts": "T2", "event": "session_end", "trace_id": "run_ev3",
             "span_id": "s0", "data": {"duration_ms": 1000}},
        ])

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_ev3/events")
        assert resp.status_code == 200

        named_events = _parse_sse_named_events(resp.text)
        assert len(named_events) >= 1
        event_type, data = named_events[0]
        assert event_type == "snapshot"
        assert len(data["events"]) == 2
