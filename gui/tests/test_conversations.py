"""Tests for conversation endpoints."""

from unittest.mock import patch

from test_sessions_sync import _register_project

from strawpot_gui.db import get_db


def _create_conversation(client, project_id, title=None):
    body = {"project_id": project_id}
    if title:
        body["title"] = title
    resp = client.post("/api/conversations", json=body)
    assert resp.status_code == 201
    return resp.json()


def _submit_task(client, conversation_id, task="Do something", **kwargs):
    """Submit a task using a mocked subprocess."""
    body = {"task": task, **kwargs}
    with patch("strawpot_gui.routers.sessions.shutil.which", return_value="/usr/bin/strawpot"), \
         patch("strawpot_gui.routers.sessions.subprocess.Popen"), \
         patch("strawpot_gui.routers.sessions.load_config") as mock_config:
        from strawpot.config import StrawPotConfig
        mock_config.return_value = StrawPotConfig()
        return client.post(f"/api/conversations/{conversation_id}/tasks", json=body)


class TestCreateConversation:
    def test_returns_201(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        resp = client.post("/api/conversations", json={"project_id": pid})
        assert resp.status_code == 201

    def test_response_shape(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        data = _create_conversation(client, pid, title="My Chat")
        assert data["project_id"] == pid
        assert data["title"] == "My Chat"
        assert "id" in data
        assert "created_at" in data

    def test_title_defaults_to_null(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        data = _create_conversation(client, pid)
        assert data["title"] is None

    def test_unknown_project_returns_404(self, client):
        resp = client.post("/api/conversations", json={"project_id": 9999})
        assert resp.status_code == 404


class TestGetConversation:
    def test_get_existing(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = client.get(f"/api/conversations/{conv['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == conv["id"]
        assert data["project_id"] == pid
        assert "sessions" in data
        assert "has_more" in data

    def test_get_missing_returns_404(self, client):
        resp = client.get("/api/conversations/9999")
        assert resp.status_code == 404

    def test_empty_sessions_list(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        data = client.get(f"/api/conversations/{conv['id']}").json()
        assert data["sessions"] == []
        assert data["has_more"] is False

    def test_sessions_after_task_submission(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        _submit_task(client, conv["id"], task="Build it")
        data = client.get(f"/api/conversations/{conv['id']}").json()
        assert len(data["sessions"]) == 1

    def test_pagination_limit(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        for _ in range(3):
            _submit_task(client, conv["id"])
        data = client.get(f"/api/conversations/{conv['id']}?limit=2").json()
        assert len(data["sessions"]) == 2
        assert data["has_more"] is True

    def test_pagination_no_more(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        _submit_task(client, conv["id"])
        data = client.get(f"/api/conversations/{conv['id']}?limit=20").json()
        assert len(data["sessions"]) == 1
        assert data["has_more"] is False


class TestListProjectConversations:
    def test_empty_list(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        resp = client.get(f"/api/projects/{pid}/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_lists_conversations(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        _create_conversation(client, pid, title="First")
        _create_conversation(client, pid, title="Second")
        data = client.get(f"/api/projects/{pid}/conversations").json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_unknown_project_returns_404(self, client):
        resp = client.get("/api/projects/9999/conversations")
        assert resp.status_code == 404

    def test_scoped_to_project(self, client, tmp_path):
        d1 = tmp_path / "p1"
        d1.mkdir()
        d2 = tmp_path / "p2"
        d2.mkdir()
        pid1 = _register_project(client, d1)
        pid2 = _register_project(client, d2)
        _create_conversation(client, pid1)
        _create_conversation(client, pid2)
        _create_conversation(client, pid2)
        assert client.get(f"/api/projects/{pid1}/conversations").json()["total"] == 1
        assert client.get(f"/api/projects/{pid2}/conversations").json()["total"] == 2

    def test_pagination(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        for _ in range(5):
            _create_conversation(client, pid)
        data = client.get(f"/api/projects/{pid}/conversations?per_page=3&page=1").json()
        assert len(data["items"]) == 3
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["per_page"] == 3


class TestListRecentConversations:
    def test_empty(self, client):
        resp = client.get("/api/conversations/recent")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_across_projects(self, client, tmp_path):
        d1 = tmp_path / "p1"
        d1.mkdir()
        d2 = tmp_path / "p2"
        d2.mkdir()
        pid1 = _register_project(client, d1)
        pid2 = _register_project(client, d2)
        _create_conversation(client, pid1)
        _create_conversation(client, pid2)
        items = client.get("/api/conversations/recent").json()
        assert len(items) == 2

    def test_limit_param(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        for _ in range(5):
            _create_conversation(client, pid)
        items = client.get("/api/conversations/recent?limit=3").json()
        assert len(items) == 3

    def test_includes_project_name(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        _create_conversation(client, pid)
        items = client.get("/api/conversations/recent").json()
        assert "project_name" in items[0]


class TestSubmitTask:
    def test_returns_201_with_run_id(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = _submit_task(client, conv["id"], task="Write tests")
        assert resp.status_code == 201
        data = resp.json()
        assert data["run_id"].startswith("run_")
        assert data["conversation_id"] == conv["id"]

    def test_auto_sets_title_from_first_message(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        assert conv["title"] is None
        _submit_task(client, conv["id"], task="Implement the login page")
        updated = client.get(f"/api/conversations/{conv['id']}").json()
        assert updated["title"] == "Implement the login page"

    def test_does_not_overwrite_existing_title(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid, title="Fixed Title")
        _submit_task(client, conv["id"], task="Some task")
        updated = client.get(f"/api/conversations/{conv['id']}").json()
        assert updated["title"] == "Fixed Title"

    def test_unknown_conversation_returns_404(self, client):
        resp = _submit_task(client, 9999)
        assert resp.status_code == 404

    def test_session_linked_to_conversation(self, client, tmp_path, app):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = _submit_task(client, conv["id"], task="Do work")
        run_id = resp.json()["run_id"]
        with get_db(app.state.db_path) as conn:
            row = conn.execute(
                "SELECT conversation_id FROM sessions WHERE run_id = ?", (run_id,)
            ).fetchone()
        assert row["conversation_id"] == conv["id"]

    def test_context_prepended_on_second_turn(self, client, tmp_path, app):
        """Second task should have prior conversation context in the full task."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        _submit_task(client, conv["id"], task="First task")
        resp2 = _submit_task(client, conv["id"], task="Second task")
        run_id2 = resp2.json()["run_id"]
        with get_db(app.state.db_path) as conn:
            row = conn.execute(
                "SELECT task, user_task FROM sessions WHERE run_id = ?", (run_id2,)
            ).fetchone()
        # user_task is the raw message; task has context prepended
        assert row["user_task"] == "Second task"
        assert "Prior Conversation" in row["task"]
        assert "Second task" in row["task"]


class TestUpdateConversation:
    def test_update_title(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = client.patch(f"/api/conversations/{conv['id']}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    def test_update_missing_returns_404(self, client):
        resp = client.patch("/api/conversations/9999", json={"title": "X"})
        assert resp.status_code == 404


class TestDeleteConversation:
    def test_delete_removes_conversation(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = client.delete(f"/api/conversations/{conv['id']}")
        assert resp.status_code == 204
        resp = client.get(f"/api/conversations/{conv['id']}")
        assert resp.status_code == 404

    def test_delete_missing_returns_404(self, client):
        resp = client.delete("/api/conversations/9999")
        assert resp.status_code == 404

    def test_delete_unlinks_sessions(self, client, tmp_path, app):
        """Sessions belonging to the conversation lose their conversation_id FK."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)
        conv = _create_conversation(client, pid)
        resp = _submit_task(client, conv["id"])
        run_id = resp.json()["run_id"]

        client.delete(f"/api/conversations/{conv['id']}")

        with get_db(app.state.db_path) as conn:
            row = conn.execute(
                "SELECT conversation_id FROM sessions WHERE run_id = ?", (run_id,)
            ).fetchone()
        assert row["conversation_id"] is None
