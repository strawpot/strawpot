"""Tests for the conversation task queue and drain mechanism."""

import uuid
from unittest.mock import patch

from test_sessions_sync import _register_project

from strawpot_gui.db import get_db


def _create_conversation(client, project_id):
    resp = client.post("/api/conversations", json={"project_id": project_id})
    assert resp.status_code == 201
    return resp.json()


def _submit_task(client, conversation_id, task="Do something", **kwargs):
    body = {"task": task, **kwargs}
    with patch("strawpot_gui.routers.sessions.shutil.which", return_value="/usr/bin/strawpot"), \
         patch("strawpot_gui.routers.sessions.subprocess.Popen"), \
         patch("strawpot_gui.routers.sessions.load_config") as mock_config:
        from strawpot.config import StrawPotConfig
        mock_config.return_value = StrawPotConfig()
        return client.post(f"/api/conversations/{conversation_id}/tasks", json=body)


class TestTaskQueueInsert:
    """Tasks insert into conversation_task_queue as separate rows."""

    def test_queued_task_stored_individually(self, client, tmp_path, app):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        _submit_task(client, cid, task="First")
        _submit_task(client, cid, task="Second")
        _submit_task(client, cid, task="Third")

        with get_db(app.state.db_path) as conn:
            rows = conn.execute(
                "SELECT task FROM conversation_task_queue WHERE conversation_id = ? ORDER BY id",
                (cid,),
            ).fetchall()
        assert len(rows) == 2  # First launched, Second+Third queued
        assert rows[0]["task"] == "Second"
        assert rows[1]["task"] == "Third"

    def test_queued_tasks_in_detail_response(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        _submit_task(client, cid, task="Running")
        _submit_task(client, cid, task="Queued A")
        _submit_task(client, cid, task="Queued B")

        data = client.get(f"/api/conversations/{cid}").json()
        tasks = data.get("queued_tasks", [])
        assert len(tasks) == 2
        assert tasks[0]["task"] == "Queued A"
        assert tasks[1]["task"] == "Queued B"
        assert all("id" in t for t in tasks)
        assert all("created_at" in t for t in tasks)

    def test_pending_task_backward_compat(self, client, tmp_path):
        """pending_task field joins queued tasks for backward compatibility."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        _submit_task(client, cid, task="Running")
        _submit_task(client, cid, task="Task A")
        _submit_task(client, cid, task="Task B")

        data = client.get(f"/api/conversations/{cid}").json()
        assert "Task A" in data["pending_task"]
        assert "Task B" in data["pending_task"]

    def test_queue_preserves_source(self, client, tmp_path, app):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        _submit_task(client, cid, task="First")
        _submit_task(client, cid, task="Queued")

        with get_db(app.state.db_path) as conn:
            row = conn.execute(
                "SELECT source FROM conversation_task_queue WHERE conversation_id = ?",
                (cid,),
            ).fetchone()
        assert row["source"] == "user"


class TestDrainActiveSessionGuard:
    """Drain skips if a session is still active."""

    def test_drain_skips_when_session_active(self, client, tmp_path, app):
        """If a session is starting/running, drain does nothing."""
        from strawpot_gui.routers.sessions import _drain_pending_task

        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        # Launch first task (creates a session with status='starting')
        _submit_task(client, cid, task="Running task")
        # Queue a second
        _submit_task(client, cid, task="Queued task")

        # Try to drain — should skip because session is still active
        with get_db(app.state.db_path) as conn:
            _drain_pending_task(conn, cid)
            # Queue should still have the task
            remaining = conn.execute(
                "SELECT id FROM conversation_task_queue WHERE conversation_id = ?",
                (cid,),
            ).fetchall()
        assert len(remaining) == 1

    def test_drain_pops_after_session_completes(self, client, tmp_path, app):
        """After session completes, drain pops the next task."""
        from strawpot_gui.routers.sessions import _drain_pending_task

        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        resp = _submit_task(client, cid, task="First")
        run_id = resp.json()["run_id"]
        _submit_task(client, cid, task="Second")

        # Mark first session as completed
        with patch("strawpot_gui.routers.sessions.shutil.which", return_value="/usr/bin/strawpot"), \
             patch("strawpot_gui.routers.sessions.subprocess.Popen"), \
             patch("strawpot_gui.routers.sessions.load_config") as mock_config:
            from strawpot.config import StrawPotConfig
            mock_config.return_value = StrawPotConfig()
            with get_db(app.state.db_path) as conn:
                conn.execute(
                    "UPDATE sessions SET status = 'completed' WHERE run_id = ?",
                    (run_id,),
                )
                _drain_pending_task(conn, cid)

        # Queue should be empty and a new session should exist
        with get_db(app.state.db_path) as conn:
            remaining = conn.execute(
                "SELECT id FROM conversation_task_queue WHERE conversation_id = ?",
                (cid,),
            ).fetchall()
            sessions = conn.execute(
                "SELECT run_id FROM sessions WHERE conversation_id = ?",
                (cid,),
            ).fetchall()
        assert len(remaining) == 0
        assert len(sessions) == 2

    def test_drain_fifo_order(self, client, tmp_path, app):
        """Tasks drain in FIFO order (oldest first)."""
        from strawpot_gui.routers.sessions import _drain_pending_task

        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        resp = _submit_task(client, cid, task="First")
        run_id = resp.json()["run_id"]
        _submit_task(client, cid, task="Alpha")
        _submit_task(client, cid, task="Beta")

        # Complete first, drain once
        with patch("strawpot_gui.routers.sessions.shutil.which", return_value="/usr/bin/strawpot"), \
             patch("strawpot_gui.routers.sessions.subprocess.Popen") as mock_popen, \
             patch("strawpot_gui.routers.sessions.load_config") as mock_config:
            from strawpot.config import StrawPotConfig
            mock_config.return_value = StrawPotConfig()
            with get_db(app.state.db_path) as conn:
                conn.execute(
                    "UPDATE sessions SET status = 'completed' WHERE run_id = ?",
                    (run_id,),
                )
                _drain_pending_task(conn, cid)

        # Only Alpha should have drained, Beta still queued
        with get_db(app.state.db_path) as conn:
            remaining = conn.execute(
                "SELECT task FROM conversation_task_queue WHERE conversation_id = ? ORDER BY id",
                (cid,),
            ).fetchall()
        assert len(remaining) == 1
        assert remaining[0]["task"] == "Beta"


class TestCancelQueuedTask:
    """Individual and bulk queue cancellation."""

    def test_cancel_individual_task(self, client, tmp_path, app):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        _submit_task(client, cid, task="Running")
        _submit_task(client, cid, task="Cancel me")
        _submit_task(client, cid, task="Keep me")

        # Get task IDs
        data = client.get(f"/api/conversations/{cid}").json()
        tasks = data["queued_tasks"]
        cancel_id = tasks[0]["id"]

        resp = client.delete(f"/api/conversations/{cid}/queued_tasks/{cancel_id}")
        assert resp.status_code == 204

        # Only "Keep me" remains
        data = client.get(f"/api/conversations/{cid}").json()
        assert len(data["queued_tasks"]) == 1
        assert data["queued_tasks"][0]["task"] == "Keep me"

    def test_cancel_all_clears_queue(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        _submit_task(client, cid, task="Running")
        _submit_task(client, cid, task="A")
        _submit_task(client, cid, task="B")

        resp = client.delete(f"/api/conversations/{cid}/pending_task")
        assert resp.status_code == 204

        data = client.get(f"/api/conversations/{cid}").json()
        assert data["pending_task"] is None
        assert data.get("queued_tasks", []) == []

    def test_cancel_nonexistent_task_returns_404(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        cid = conv["id"]

        resp = client.delete(f"/api/conversations/{cid}/queued_tasks/99999")
        assert resp.status_code == 404
