"""Integration tests for the SSE trace events endpoint."""

import json

from test_sessions_sync import _register_project, _write_session, _write_trace

from strawpot_gui.db import sync_sessions


def _parse_sse_events(body: str) -> list[dict]:
    """Parse SSE data events from a response body string."""
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


class TestTraceSSETerminalSession:
    """Tests for completed/failed sessions — batch events then close."""

    def test_completed_session_returns_all_events(self, client, tmp_path):
        """Completed session sends all trace events and closes."""
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

        sse_messages = _parse_sse_events(resp.text)
        assert len(sse_messages) >= 1
        data = sse_messages[0]
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

        sse_messages = _parse_sse_events(resp.text)
        assert len(sse_messages) >= 1
        assert len(sse_messages[0]["events"]) == 2
