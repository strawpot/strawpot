"""Tests for session delete endpoint."""

import os

from strawpot_gui.db import sync_sessions

from test_sessions_sync import _register_project, _write_session, _write_trace


def _create_completed_session(client, tmp_path, run_id="run_test123"):
    """Register a project, create an archived session, sync, and return (project_id, run_id)."""
    pid = _register_project(client, tmp_path)
    session_dir = _write_session(tmp_path, run_id, archived=True)
    _write_trace(session_dir, [
        {"event": "session_end", "ts": "2026-01-01T12:05:00+00:00", "data": {"duration_ms": 300000, "exit_code": 0}},
    ])
    sync_sessions(client.app.state.db_path)
    return pid, run_id


class TestDeleteSession:
    def test_not_found(self, client):
        resp = client.delete("/api/sessions/run_nonexistent")
        assert resp.status_code == 404

    def test_cannot_delete_running(self, client, tmp_path):
        """Sessions with starting/running status cannot be deleted."""
        pid = _register_project(client, tmp_path)
        _write_session(tmp_path, "run_active1", archived=False)
        sync_sessions(client.app.state.db_path)

        # Force status back to running (sync marks dead PIDs as failed)
        from strawpot_gui.db import get_db
        with get_db(client.app.state.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET status = 'running' WHERE run_id = 'run_active1'"
            )

        resp = client.delete("/api/sessions/run_active1")
        assert resp.status_code == 409

    def test_delete_removes_db_row(self, client, tmp_path):
        pid, run_id = _create_completed_session(client, tmp_path)

        # Verify session exists
        resp = client.get(f"/api/projects/{pid}/sessions")
        assert resp.json()["total"] == 1

        # Delete
        resp = client.delete(f"/api/sessions/{run_id}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Verify gone
        resp = client.get(f"/api/projects/{pid}/sessions")
        assert resp.json()["total"] == 0

    def test_delete_removes_disk_files(self, client, tmp_path):
        pid, run_id = _create_completed_session(client, tmp_path)
        session_dir = os.path.join(str(tmp_path), ".strawpot", "sessions", run_id)
        assert os.path.isdir(session_dir)

        client.delete(f"/api/sessions/{run_id}")
        assert not os.path.isdir(session_dir)

    def test_delete_removes_symlinks(self, client, tmp_path):
        pid, run_id = _create_completed_session(client, tmp_path)
        archive_link = os.path.join(str(tmp_path), ".strawpot", "archive", run_id)
        assert os.path.exists(archive_link)

        client.delete(f"/api/sessions/{run_id}")
        assert not os.path.exists(archive_link)

    def test_delete_with_missing_directory(self, client, tmp_path):
        """Deleting a session whose directory is already gone should still succeed."""
        pid, run_id = _create_completed_session(client, tmp_path)

        # Remove directory before API call
        session_dir = os.path.join(str(tmp_path), ".strawpot", "sessions", run_id)
        import shutil
        shutil.rmtree(session_dir)

        resp = client.delete(f"/api/sessions/{run_id}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # DB row should still be gone
        resp = client.get(f"/api/projects/{pid}/sessions")
        assert resp.json()["total"] == 0
