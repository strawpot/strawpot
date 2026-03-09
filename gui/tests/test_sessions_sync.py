"""Tests for session index sync on startup."""

import json
import os

from strawpot_gui.db import _parse_trace, sync_sessions


def _register_project(client, working_dir):
    """Helper to register a project and return its ID."""
    resp = client.post("/api/projects", json={
        "display_name": "Test",
        "working_dir": str(working_dir),
    })
    return resp.json()["id"]


def _write_session(base_dir, run_id, *, archived=False, **overrides):
    """Write a minimal session.json and return the session directory path.

    Session dirs always live at ``sessions/<run_id>/``.  A symlink is
    created in ``sessions/running/`` or ``sessions/archive/`` depending
    on the ``archived`` flag.
    """
    strawpot_dir = os.path.join(str(base_dir), ".strawpot")
    session_dir = os.path.join(strawpot_dir, "sessions", run_id)
    os.makedirs(session_dir, exist_ok=True)

    data = {
        "run_id": run_id,
        "working_dir": str(base_dir),
        "isolation": "none",
        "runtime": "strawpot-claude-code",
        "denden_addr": "127.0.0.1:9700",
        "started_at": "2026-01-01T12:00:00+00:00",
        "pid": 999999,
        "agents": {
            "agent_abc": {
                "role": "orchestrator",
                "runtime": "strawpot-claude-code",
                "parent": None,
                "started_at": "2026-01-01T12:00:01+00:00",
                "pid": 999998,
            }
        },
    }
    data.update(overrides)

    with open(os.path.join(session_dir, "session.json"), "w") as f:
        json.dump(data, f)

    # Create symlink in .strawpot/running/ or .strawpot/archive/
    view_dir = os.path.join(strawpot_dir, "archive" if archived else "running")
    os.makedirs(view_dir, exist_ok=True)
    link_path = os.path.join(view_dir, run_id)
    if not os.path.exists(link_path):
        os.symlink(os.path.join("..", "sessions", run_id), link_path)

    return session_dir


def _write_trace(session_dir, events):
    """Write trace events to trace.jsonl in the given session dir."""
    trace_path = os.path.join(session_dir, "trace.jsonl")
    with open(trace_path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


class TestParseTrace:
    def test_empty_file(self, tmp_path):
        path = str(tmp_path / "trace.jsonl")
        with open(path, "w") as f:
            f.write("")
        assert _parse_trace(path) == {}

    def test_missing_file(self, tmp_path):
        assert _parse_trace(str(tmp_path / "nonexistent.jsonl")) == {}

    def test_session_end_event(self, tmp_path):
        path = str(tmp_path / "trace.jsonl")
        _write_trace(str(tmp_path), [
            {
                "ts": "2026-01-01T12:05:00+00:00",
                "event": "session_end",
                "trace_id": "run_x",
                "span_id": "span1",
                "data": {"merge_strategy": "auto", "duration_ms": 300000},
            }
        ])
        result = _parse_trace(os.path.join(str(tmp_path), "trace.jsonl"))
        assert result["ended_at"] == "2026-01-01T12:05:00+00:00"
        assert result["duration_ms"] == 300000

    def test_delegate_end_root(self, tmp_path):
        path = str(tmp_path / "trace.jsonl")
        _write_trace(str(tmp_path), [
            {
                "ts": "2026-01-01T12:04:00+00:00",
                "event": "delegate_end",
                "trace_id": "run_x",
                "span_id": "span2",
                "parent_span": None,
                "data": {"exit_code": 0, "summary": "Done", "duration_ms": 250000},
            }
        ])
        result = _parse_trace(os.path.join(str(tmp_path), "trace.jsonl"))
        assert result["exit_code"] == 0
        assert result["summary"] == "Done"

    def test_non_root_delegate_end_ignored(self, tmp_path):
        _write_trace(str(tmp_path), [
            {
                "ts": "2026-01-01T12:04:00+00:00",
                "event": "delegate_end",
                "trace_id": "run_x",
                "span_id": "span2",
                "parent_span": "span1",
                "data": {"exit_code": 1, "summary": "Sub failed", "duration_ms": 5000},
            }
        ])
        result = _parse_trace(os.path.join(str(tmp_path), "trace.jsonl"))
        assert "exit_code" not in result


class TestSyncSessions:
    def test_no_projects(self, client):
        """Sync with no registered projects is a no-op."""
        sync_sessions(client.app.state.db_path)

    def test_project_no_sessions_dir(self, client, tmp_path):
        """Project with no .strawpot/sessions/ directory."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        sync_sessions(client.app.state.db_path)
        # No crash, no sessions created

    def test_archived_session_minimal(self, client, tmp_path):
        """Archived session with session.json only → row with minimal fields."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        _write_session(project_dir, "run_abc123", archived=True)

        sync_sessions(client.app.state.db_path)

        resp = client.get("/api/projects")
        # Check db directly
        from strawpot_gui.db import get_db
        with get_db(client.app.state.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE run_id = ?", ("run_abc123",)
            ).fetchone()
        assert row is not None
        assert row["project_id"] == pid
        assert row["role"] == "orchestrator"
        assert row["runtime"] == "strawpot-claude-code"
        assert row["isolation"] == "none"
        assert row["status"] == "failed"  # no trace → failed

    def test_archived_session_with_trace(self, client, tmp_path):
        """Archived session with trace.jsonl → has completion fields."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_traced", archived=True)
        _write_trace(session_dir, [
            {
                "ts": "2026-01-01T12:00:01+00:00",
                "event": "session_start",
                "trace_id": "run_traced",
                "span_id": "s1",
                "data": {"run_id": "run_traced", "role": "orchestrator",
                         "runtime": "strawpot-claude-code", "isolation": "none"},
            },
            {
                "ts": "2026-01-01T12:05:00+00:00",
                "event": "delegate_end",
                "trace_id": "run_traced",
                "span_id": "s2",
                "parent_span": None,
                "data": {"exit_code": 0, "summary": "All done", "duration_ms": 300000},
            },
            {
                "ts": "2026-01-01T12:05:01+00:00",
                "event": "session_end",
                "trace_id": "run_traced",
                "span_id": "s1",
                "data": {"merge_strategy": "auto", "duration_ms": 300100},
            },
        ])

        sync_sessions(client.app.state.db_path)

        from strawpot_gui.db import get_db
        with get_db(client.app.state.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE run_id = ?", ("run_traced",)
            ).fetchone()
        assert row["status"] == "completed"
        assert row["exit_code"] == 0
        assert row["summary"] == "All done"
        assert row["duration_ms"] == 300100
        assert row["ended_at"] == "2026-01-01T12:05:01+00:00"

    def test_active_session_live_pid(self, client, tmp_path):
        """Active session with live PID → status 'running'."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        # Use current process PID so it's alive
        _write_session(project_dir, "run_live", pid=os.getpid())

        sync_sessions(client.app.state.db_path)

        from strawpot_gui.db import get_db
        with get_db(client.app.state.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE run_id = ?", ("run_live",)
            ).fetchone()
        assert row["status"] == "running"

    def test_corrupt_session_json_skipped(self, client, tmp_path):
        """Corrupt session.json is skipped without crashing."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        strawpot_dir = os.path.join(str(project_dir), ".strawpot")
        session_dir = os.path.join(strawpot_dir, "sessions", "run_corrupt")
        os.makedirs(session_dir)
        with open(os.path.join(session_dir, "session.json"), "w") as f:
            f.write("NOT JSON")
        # Create archive symlink so it's discovered
        archive_dir = os.path.join(strawpot_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        os.symlink(os.path.join("..", "sessions", "run_corrupt"), os.path.join(archive_dir, "run_corrupt"))

        sync_sessions(client.app.state.db_path)

        from strawpot_gui.db import get_db
        with get_db(client.app.state.db_path) as conn:
            count = conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
        assert count == 0

    def test_multiple_projects(self, client, tmp_path):
        """Sessions from multiple projects are all synced."""
        p1 = tmp_path / "proj1"
        p1.mkdir()
        p2 = tmp_path / "proj2"
        p2.mkdir()
        _register_project(client, p1)
        _register_project(client, p2)

        _write_session(p1, "run_p1", archived=True)
        _write_session(p2, "run_p2", archived=True)

        sync_sessions(client.app.state.db_path)

        from strawpot_gui.db import get_db
        with get_db(client.app.state.db_path) as conn:
            count = conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
        assert count == 2

    def test_idempotent(self, client, tmp_path):
        """Running sync twice doesn't duplicate rows."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)

        _write_session(project_dir, "run_idem", archived=True)

        sync_sessions(client.app.state.db_path)
        sync_sessions(client.app.state.db_path)

        from strawpot_gui.db import get_db
        with get_db(client.app.state.db_path) as conn:
            count = conn.execute(
                "SELECT count(*) FROM sessions WHERE run_id = ?", ("run_idem",)
            ).fetchone()[0]
        assert count == 1
