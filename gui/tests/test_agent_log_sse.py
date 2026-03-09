"""Integration tests for the agent log SSE and REST endpoints."""

import json
import os

from test_sessions_sync import _register_project, _write_session

from strawpot_gui.db import sync_sessions


def _write_agent_log(session_dir, agent_id, content):
    """Write a .log file for an agent."""
    agent_dir = os.path.join(session_dir, "agents", agent_id)
    os.makedirs(agent_dir, exist_ok=True)
    with open(os.path.join(agent_dir, ".log"), "w") as f:
        f.write(content)


def _parse_sse_named_events(body):
    """Parse SSE events with event types."""
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
            current_type = "message"
    return events


class TestAgentLogSSETerminal:
    """Tests for completed sessions — snapshot then done."""

    def test_completed_session_returns_snapshot_and_done(self, client, tmp_path):
        """Completed session sends log snapshot then done event."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_log1", archived=True)
        _write_agent_log(session_dir, "agent_abc", "line 1\nline 2\nline 3\n")

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_log1/logs/agent_abc")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        events = _parse_sse_named_events(resp.text)
        assert len(events) >= 2

        etype, data = events[0]
        assert etype == "snapshot"
        assert data["lines"] == ["line 1", "line 2", "line 3"]
        assert data["offset"] > 0

        etype2, _ = events[1]
        assert etype2 == "done"

    def test_empty_log_returns_empty_snapshot(self, client, tmp_path):
        """Session with no log file returns empty snapshot then done."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_log2", archived=True)
        # Create agent dir but no .log file
        os.makedirs(os.path.join(session_dir, "agents", "agent_abc"))

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_log2/logs/agent_abc")
        assert resp.status_code == 200

        events = _parse_sse_named_events(resp.text)
        assert len(events) >= 2

        etype, data = events[0]
        assert etype == "snapshot"
        assert data["lines"] == []
        assert data["offset"] == 0

        etype2, _ = events[1]
        assert etype2 == "done"

    def test_large_log_returns_last_500_lines(self, client, tmp_path):
        """Large log files are truncated to the last 500 lines."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_log3", archived=True)
        lines = [f"line {i}" for i in range(1000)]
        _write_agent_log(session_dir, "agent_abc", "\n".join(lines) + "\n")

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_log3/logs/agent_abc")
        events = _parse_sse_named_events(resp.text)

        etype, data = events[0]
        assert etype == "snapshot"
        assert len(data["lines"]) == 500
        assert data["lines"][0] == "line 500"
        assert data["lines"][-1] == "line 999"


class TestAgentLogSSENotFound:
    def test_unknown_session_returns_404(self, client):
        """Non-existent session returns 404."""
        resp = client.get("/api/sessions/run_nonexistent/logs/agent_abc")
        assert resp.status_code == 404

    def test_unknown_agent_returns_404(self, client, tmp_path):
        """Non-existent agent returns 404."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        _write_session(project_dir, "run_log4", archived=True)
        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_log4/logs/agent_nonexistent")
        assert resp.status_code == 404


class TestAgentLogREST:
    """Tests for the full log download REST endpoint."""

    def test_full_log_returns_plaintext(self, client, tmp_path):
        """Full log endpoint returns complete content as text/plain."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_log5", archived=True)
        _write_agent_log(session_dir, "agent_abc", "hello world\n")

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_log5/logs/agent_abc/full")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert resp.text == "hello world\n"

    def test_missing_log_returns_empty(self, client, tmp_path):
        """Missing log file returns empty 200 response."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_log6", archived=True)
        os.makedirs(os.path.join(session_dir, "agents", "agent_abc"))

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_log6/logs/agent_abc/full")
        assert resp.status_code == 200
        assert resp.text == ""

    def test_unknown_session_returns_404(self, client):
        """Non-existent session returns 404."""
        resp = client.get("/api/sessions/run_nonexistent/logs/agent_abc/full")
        assert resp.status_code == 404

    def test_unknown_agent_returns_404(self, client, tmp_path):
        """Non-existent agent returns 404."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        _write_session(project_dir, "run_log7", archived=True)
        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/sessions/run_log7/logs/agent_nonexistent/full")
        assert resp.status_code == 404
