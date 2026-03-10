"""Tests for the ask_user respond endpoint."""

import json
import os

from strawpot_gui.db import get_db, sync_sessions

from test_sessions_sync import _register_project, _write_session


def _make_active_session(client, tmp_path, run_id="run_interactive"):
    """Create a running interactive session and return (project_id, session_dir)."""
    pid = _register_project(client, tmp_path)
    session_dir = _write_session(tmp_path, run_id, archived=False)
    sync_sessions(client.app.state.db_path)

    # Force status to running (sync marks dead PIDs as failed)
    with get_db(client.app.state.db_path) as conn:
        conn.execute(
            "UPDATE sessions SET status = 'running' WHERE run_id = ?",
            (run_id,),
        )

    return pid, str(session_dir)


def _write_pending(session_dir, request_id="abc123"):
    """Write an ask_user_pending.json file."""
    path = os.path.join(session_dir, "ask_user_pending.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"request_id": request_id, "question": "Pick a color?"}, f)
    return path


class TestRespondToAskUser:
    def test_not_found(self, client):
        resp = client.post(
            "/api/sessions/run_nonexistent/respond",
            json={"request_id": "x", "text": "hi"},
        )
        assert resp.status_code == 404

    def test_inactive_session(self, client, tmp_path):
        """Cannot respond to a completed session."""
        pid = _register_project(client, tmp_path)
        _write_session(tmp_path, "run_done", archived=True)
        sync_sessions(client.app.state.db_path)

        resp = client.post(
            "/api/sessions/run_done/respond",
            json={"request_id": "x", "text": "hi"},
        )
        assert resp.status_code == 409

    def test_no_pending_request(self, client, tmp_path):
        """409/404 when no ask_user_pending.json exists."""
        _make_active_session(client, tmp_path, "run_no_pending")

        resp = client.post(
            "/api/sessions/run_no_pending/respond",
            json={"request_id": "x", "text": "hi"},
        )
        assert resp.status_code == 404

    def test_request_id_mismatch(self, client, tmp_path):
        """409 when request_id doesn't match pending."""
        _, session_dir = _make_active_session(client, tmp_path, "run_mismatch")
        _write_pending(session_dir, request_id="correct_id")

        resp = client.post(
            "/api/sessions/run_mismatch/respond",
            json={"request_id": "wrong_id", "text": "hi"},
        )
        assert resp.status_code == 409

    def test_successful_respond(self, client, tmp_path):
        """Successful response writes ask_user_response.json."""
        _, session_dir = _make_active_session(client, tmp_path, "run_ok")
        _write_pending(session_dir, request_id="req123")

        resp = client.post(
            "/api/sessions/run_ok/respond",
            json={"request_id": "req123", "text": "blue"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Verify response file was written
        response_path = os.path.join(session_dir, "ask_user_response.json")
        assert os.path.isfile(response_path)
        with open(response_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["request_id"] == "req123"
        assert data["text"] == "blue"
