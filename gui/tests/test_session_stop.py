"""Tests for POST /api/sessions/:run_id/stop endpoint."""

import json
import os
from unittest.mock import patch

from test_conversations import _create_conversation, _submit_task
from test_sessions_sync import _register_project, _write_session

from strawpot_gui.db import get_db, sync_sessions


def _insert_session(client, project_dir, run_id, *, status="running"):
    """Register project, write session.json, sync, then force status."""
    pid = _register_project(client, project_dir)
    session_dir = _write_session(project_dir, run_id, pid=os.getpid())
    sync_sessions(client.app.state.db_path)
    # Override status to desired value
    with get_db(client.app.state.db_path) as conn:
        conn.execute(
            "UPDATE sessions SET status = ? WHERE run_id = ?",
            (status, run_id),
        )
    return pid, session_dir


class TestStopSession:
    def test_stop_sends_sigterm(self, client, tmp_path):
        """Stopping a running session sends SIGTERM and returns 'stopping'."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _, session_dir = _insert_session(client, project_dir, "run_stop")

        with patch("strawpot_gui.routers.sessions.os.kill") as mock_kill:
            resp = client.post("/api/sessions/run_stop/stop")

        assert resp.status_code == 200
        assert resp.json() == {"run_id": "run_stop", "status": "stopped"}
        # First call: liveness check (signal 0), second call: SIGTERM
        assert mock_kill.call_count == 2
        mock_kill.assert_any_call(os.getpid(), 0)
        import signal
        mock_kill.assert_any_call(os.getpid(), signal.SIGTERM)

        # Verify summary defaults to "Interrupted" when not already set
        with get_db(client.app.state.db_path) as conn:
            row = conn.execute(
                "SELECT summary FROM sessions WHERE run_id = ?",
                ("run_stop",),
            ).fetchone()
        assert row["summary"] == "Interrupted"

    def test_stop_preserves_existing_summary(self, client, tmp_path):
        """Stopping a session with an existing summary doesn't overwrite it."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _, session_dir = _insert_session(client, project_dir, "run_summary")

        # Pre-set a summary before stopping
        with get_db(client.app.state.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET summary = 'Task completed' WHERE run_id = ?",
                ("run_summary",),
            )

        with patch("strawpot_gui.routers.sessions.os.kill"):
            resp = client.post("/api/sessions/run_summary/stop")

        assert resp.status_code == 200
        with get_db(client.app.state.db_path) as conn:
            row = conn.execute(
                "SELECT summary FROM sessions WHERE run_id = ?",
                ("run_summary",),
            ).fetchone()
        assert row["summary"] == "Task completed"  # Not overwritten

    def test_stop_nonexistent_returns_404(self, client):
        """Unknown run_id returns 404."""
        resp = client.post("/api/sessions/run_nope/stop")
        assert resp.status_code == 404

    def test_stop_completed_returns_409(self, client, tmp_path):
        """Cannot stop a completed session."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _insert_session(
            client, project_dir, "run_done", status="completed"
        )

        resp = client.post("/api/sessions/run_done/stop")
        assert resp.status_code == 409

    def test_stop_failed_returns_409(self, client, tmp_path):
        """Cannot stop a failed session."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _insert_session(
            client, project_dir, "run_fail", status="failed"
        )

        resp = client.post("/api/sessions/run_fail/stop")
        assert resp.status_code == 409

    def test_stop_starting_session_allowed(self, client, tmp_path):
        """Can stop a session still in 'starting' status."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _insert_session(
            client, project_dir, "run_start", status="starting"
        )

        with patch("strawpot_gui.routers.sessions.os.kill"):
            resp = client.post("/api/sessions/run_start/stop")

        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_stop_already_dead_marks_failed(self, client, tmp_path):
        """If process is already gone, marks session as failed."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _insert_session(client, project_dir, "run_dead")

        with patch(
            "strawpot_gui.routers.sessions.os.kill",
            side_effect=ProcessLookupError,
        ):
            resp = client.post("/api/sessions/run_dead/stop")

        assert resp.status_code == 200
        assert resp.json() == {"run_id": "run_dead", "status": "stopped"}

        # Verify DB was updated
        with get_db(client.app.state.db_path) as conn:
            row = conn.execute(
                "SELECT status FROM sessions WHERE run_id = ?",
                ("run_dead",),
            ).fetchone()
        assert row["status"] == "stopped"

    def test_stop_missing_session_json_marks_failed(self, client, tmp_path):
        """If session.json is missing, marks session as failed."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _, session_dir = _insert_session(
            client, project_dir, "run_nofile"
        )

        # Delete session.json
        os.remove(os.path.join(session_dir, "session.json"))

        resp = client.post("/api/sessions/run_nofile/stop")
        assert resp.status_code == 200
        assert resp.json() == {"run_id": "run_nofile", "status": "stopped"}

    def test_stop_no_pid_in_session_json_marks_failed(self, client, tmp_path):
        """If session.json has no pid field, marks session as failed."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _, session_dir = _insert_session(
            client, project_dir, "run_nopid"
        )

        # Rewrite session.json without pid
        session_file = os.path.join(session_dir, "session.json")
        with open(session_file) as f:
            data = json.load(f)
        del data["pid"]
        with open(session_file, "w") as f:
            json.dump(data, f)

        resp = client.post("/api/sessions/run_nopid/stop")
        assert resp.status_code == 200
        assert resp.json() == {"run_id": "run_nopid", "status": "stopped"}

    def test_stop_drains_queued_task(self, client, tmp_path, app):
        """Stopping a session drains the next queued task."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        # Launch first task — creates a session
        resp1 = _submit_task(client, cid, task="First task")
        run_id1 = resp1.json()["run_id"]

        # Queue a second task (session already active → 202)
        _submit_task(client, cid, task="Queued task")

        # Verify task is queued
        with get_db(app.state.db_path) as conn:
            queued = conn.execute(
                "SELECT task FROM conversation_task_queue WHERE conversation_id = ?",
                (cid,),
            ).fetchall()
        assert len(queued) == 1
        assert queued[0]["task"] == "Queued task"

        # Stop the first session — should drain the queued task
        with patch("strawpot_gui.routers.sessions.os.kill"), \
             patch("strawpot_gui.routers.sessions.shutil.which", return_value="/usr/bin/strawpot"), \
             patch("strawpot_gui.routers.sessions.subprocess.Popen"), \
             patch("strawpot_gui.routers.sessions.load_config") as mock_config:
            from strawpot.config import StrawPotConfig
            mock_config.return_value = StrawPotConfig()
            resp = client.post(f"/api/sessions/{run_id1}/stop")

        assert resp.status_code == 200

        # Queue should be empty — task was drained
        with get_db(app.state.db_path) as conn:
            remaining = conn.execute(
                "SELECT id FROM conversation_task_queue WHERE conversation_id = ?",
                (cid,),
            ).fetchall()
        assert len(remaining) == 0

        # A new session should have been created for the queued task
        with get_db(app.state.db_path) as conn:
            sessions = conn.execute(
                "SELECT run_id FROM sessions WHERE conversation_id = ?",
                (cid,),
            ).fetchall()
        assert len(sessions) == 2
