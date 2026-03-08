"""Integration tests for the SSE agent tree endpoint."""

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


class TestTreeSSETerminalSession:
    """Tests for completed/failed sessions — single event then close."""

    def test_completed_session_returns_tree(self, client, tmp_path):
        """Completed session sends one event with final tree and closes."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_tree1", archived=True)
        _write_trace(session_dir, [
            {"ts": "T1", "event": "session_start", "trace_id": "run_tree1",
             "span_id": "s0", "data": {"run_id": "run_tree1",
                                        "role": "orchestrator",
                                        "runtime": "claude_code",
                                        "isolation": "none"}},
            {"ts": "T2", "event": "delegate_end", "trace_id": "run_tree1",
             "span_id": "s0", "parent_span": None,
             "data": {"exit_code": 0, "summary": "Done",
                       "duration_ms": 5000}},
            {"ts": "T3", "event": "session_end", "trace_id": "run_tree1",
             "span_id": "s0", "data": {"duration_ms": 5100}},
        ])

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_tree1/tree")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        events = _parse_sse_events(resp.text)
        assert len(events) >= 1
        data = events[0]
        assert "nodes" in data
        assert "pending_delegations" in data
        assert "denied_delegations" in data
        # Root agent from session.json
        assert len(data["nodes"]) >= 1

    def test_tree_with_sub_agents(self, client, tmp_path):
        """Tree includes sub-agents from trace events."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_tree2", archived=True)
        _write_trace(session_dir, [
            {"ts": "T1", "event": "session_start", "trace_id": "run_tree2",
             "span_id": "s0", "data": {}},
            {"ts": "T2", "event": "delegate_start", "trace_id": "run_tree2",
             "span_id": "s1", "parent_span": "s0",
             "data": {"role": "implementer"}},
            {"ts": "T3", "event": "agent_spawn", "trace_id": "run_tree2",
             "span_id": "s1", "parent_span": "s0",
             "data": {"agent_id": "agent_impl", "runtime": "cc",
                       "pid": 999}},
            {"ts": "T4", "event": "agent_end", "trace_id": "run_tree2",
             "span_id": "s1",
             "data": {"exit_code": 0, "duration_ms": 10000}},
            {"ts": "T5", "event": "delegate_end", "trace_id": "run_tree2",
             "span_id": "s1", "parent_span": None,
             "data": {"exit_code": 0, "summary": "Done",
                       "duration_ms": 10000}},
            {"ts": "T6", "event": "session_end", "trace_id": "run_tree2",
             "span_id": "s0", "data": {"duration_ms": 11000}},
        ])

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_tree2/tree")
        events = _parse_sse_events(resp.text)
        data = events[0]

        agent_ids = [n["agent_id"] for n in data["nodes"]]
        assert "agent_abc" in agent_ids  # root from session.json
        assert "agent_impl" in agent_ids  # sub-agent from trace

        impl = next(n for n in data["nodes"] if n["agent_id"] == "agent_impl")
        assert impl["status"] == "completed"
        assert impl["parent"] == "agent_abc"

    def test_tree_with_denied_delegation(self, client, tmp_path):
        """Denied delegations appear in the response."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_tree3", archived=True)
        _write_trace(session_dir, [
            {"ts": "T1", "event": "session_start", "trace_id": "run_tree3",
             "span_id": "s0", "data": {}},
            {"ts": "T2", "event": "delegate_denied", "trace_id": "run_tree3",
             "span_id": "s1", "parent_span": "s0",
             "data": {"role": "admin", "reason": "DENY_DEPTH_LIMIT"}},
            {"ts": "T3", "event": "session_end", "trace_id": "run_tree3",
             "span_id": "s0", "data": {"duration_ms": 1000}},
        ])

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_tree3/tree")
        events = _parse_sse_events(resp.text)
        data = events[0]

        assert len(data["denied_delegations"]) == 1
        assert data["denied_delegations"][0]["role"] == "admin"
        assert data["denied_delegations"][0]["reason"] == "DENY_DEPTH_LIMIT"


class TestTreeSSENotFound:
    def test_unknown_session_returns_404(self, client):
        """Non-existent session returns 404."""
        resp = client.get("/api/sessions/run_nonexistent/tree")
        assert resp.status_code == 404


class TestTreeSSEActiveSession:
    def test_active_session_with_session_end_terminates(self, client, tmp_path):
        """Active session that ends via trace terminates the SSE stream."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        # Write session as active (not archived) but include session_end
        # so the SSE loop terminates after reading all events
        session_dir = _write_session(project_dir, "run_active")
        _write_trace(session_dir, [
            {"ts": "T1", "event": "session_start", "trace_id": "run_active",
             "span_id": "s0", "data": {}},
            {"ts": "T2", "event": "session_end", "trace_id": "run_active",
             "span_id": "s0", "data": {"duration_ms": 1000}},
        ])

        sync_sessions(client.app.state.db_path)

        # Even though DB status is "running", the trace has session_end
        # so the SSE stream should send the state and terminate
        resp = client.get("/api/sessions/run_active/tree")
        assert resp.status_code == 200

        events = _parse_sse_events(resp.text)
        assert len(events) >= 1
        data = events[0]
        assert "nodes" in data
        # Root agent from session.json
        assert len(data["nodes"]) >= 1
