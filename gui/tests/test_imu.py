"""Tests for Bot Imu endpoints and virtual project initialization."""

from pathlib import Path
from unittest.mock import patch

from test_sessions_sync import _register_project

from strawpot_gui.db import ensure_imu_project, get_db


class TestEnsureImuProject:
    def test_imu_project_created_on_startup(self, client, app):
        """Virtual project id=0 is inserted by the app lifespan."""
        with get_db(app.state.db_path) as conn:
            row = conn.execute(
                "SELECT id, display_name FROM projects WHERE id = 0"
            ).fetchone()
        assert row is not None
        assert row["display_name"] == "Bot Imu"

    def test_imu_project_idempotent(self, client, app):
        """Calling ensure_imu_project twice does not error or create duplicates."""
        ensure_imu_project(app.state.db_path)
        ensure_imu_project(app.state.db_path)
        with get_db(app.state.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM projects WHERE id = 0"
            ).fetchone()[0]
        assert count == 1

    def test_imu_project_hidden_from_projects_list(self, client):
        """GET /api/projects must not include the virtual Bot Imu project."""
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()]
        assert 0 not in ids

    def test_regular_projects_still_listed(self, client, tmp_path):
        """Regular projects are unaffected by the id=0 filter."""
        d = tmp_path / "proj"
        d.mkdir()
        client.post("/api/projects", json={"display_name": "P", "working_dir": str(d)})
        resp = client.get("/api/projects")
        assert len(resp.json()) == 1
        assert resp.json()[0]["display_name"] == "P"


class TestListImuConversations:
    def test_empty_list(self, client):
        resp = client.get("/api/imu/conversations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_created_conversations(self, client):
        client.post("/api/imu/conversations")
        client.post("/api/imu/conversations")
        resp = client.get("/api/imu/conversations")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_ordered_newest_first(self, client):
        r1 = client.post("/api/imu/conversations").json()
        r2 = client.post("/api/imu/conversations").json()
        items = client.get("/api/imu/conversations").json()
        # Most recent conversation first
        assert items[0]["id"] == r2["id"]
        assert items[1]["id"] == r1["id"]

    def test_includes_session_count(self, client):
        client.post("/api/imu/conversations")
        items = client.get("/api/imu/conversations").json()
        assert "session_count" in items[0]
        assert items[0]["session_count"] == 0

    def test_limit_param(self, client):
        for _ in range(5):
            client.post("/api/imu/conversations")
        resp = client.get("/api/imu/conversations?limit=3")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_does_not_include_regular_project_conversations(self, client, tmp_path):
        """Conversations from regular projects must not appear in imu list."""
        d = tmp_path / "proj"
        d.mkdir()
        create = client.post("/api/projects", json={"display_name": "P", "working_dir": str(d)})
        pid = create.json()["id"]
        client.post("/api/conversations", json={"project_id": pid})

        items = client.get("/api/imu/conversations").json()
        assert items == []


class TestCreateImuConversation:
    def test_returns_201(self, client):
        resp = client.post("/api/imu/conversations")
        assert resp.status_code == 201

    def test_response_shape(self, client):
        resp = client.post("/api/imu/conversations")
        data = resp.json()
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert "title" in data

    def test_title_is_null_initially(self, client):
        resp = client.post("/api/imu/conversations")
        assert resp.json()["title"] is None

    def test_each_call_creates_new_conversation(self, client):
        r1 = client.post("/api/imu/conversations").json()
        r2 = client.post("/api/imu/conversations").json()
        assert r1["id"] != r2["id"]

    def test_created_conversation_is_project_zero(self, client, app):
        resp = client.post("/api/imu/conversations")
        conv_id = resp.json()["id"]
        with get_db(app.state.db_path) as conn:
            row = conn.execute(
                "SELECT project_id FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
        assert row["project_id"] == 0


def _submit_task(client, conversation_id, task="Do something", **kwargs):
    """Submit a task using a mocked subprocess."""
    body = {"task": task, **kwargs}
    with patch("strawpot_gui.routers.sessions.shutil.which", return_value="/usr/bin/strawpot"), \
         patch("strawpot_gui.routers.sessions.subprocess.Popen"), \
         patch("strawpot_gui.routers.sessions.load_config") as mock_config:
        from strawpot.config import StrawPotConfig
        mock_config.return_value = StrawPotConfig()
        return client.post(f"/api/conversations/{conversation_id}/tasks", json=body)


class TestCrossProjectDelegation:
    """Test the imu → project conversation delegation flow.

    Simulates the real flow: imu receives a user request, creates a
    conversation on the target project, and submits a task to it.
    """

    def test_imu_creates_project_conversation_and_submits_task(self, client, tmp_path):
        """Full delegation: imu creates a project conversation and submits work."""
        # 1. Register a real project
        d = tmp_path / "myproject"
        d.mkdir()
        pid = _register_project(client, d)

        # 2. imu creates a conversation on the project (not on project 0)
        conv = client.post("/api/conversations", json={
            "project_id": pid,
            "title": "Fix login bug",
        })
        assert conv.status_code == 201
        conv_id = conv.json()["id"]

        # 3. imu submits a task to that project conversation
        resp = _submit_task(client, conv_id, task="Fix the login validation in auth.py")
        assert resp.status_code == 201
        assert "run_id" in resp.json()

        # 4. The conversation belongs to the project, not to imu
        proj_convs = client.get(f"/api/projects/{pid}/conversations")
        assert proj_convs.status_code == 200
        conv_ids = [c["id"] for c in proj_convs.json()["items"]]
        assert conv_id in conv_ids

        # 5. imu's own conversations don't include the project conversation
        imu_convs = client.get("/api/imu/conversations").json()
        imu_conv_ids = [c["id"] for c in imu_convs]
        assert conv_id not in imu_conv_ids

    def test_imu_continues_existing_project_conversation(self, client, tmp_path):
        """imu submits multiple tasks to the same project conversation."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)

        conv = client.post("/api/conversations", json={"project_id": pid}).json()
        conv_id = conv["id"]

        # First task starts a session
        resp1 = _submit_task(client, conv_id, task="Implement feature X")
        assert resp1.status_code == 201

        # Second task is queued (session already running)
        resp2 = _submit_task(client, conv_id, task="Add tests for feature X")
        assert resp2.status_code == 202
        assert resp2.json()["queued"] is True

    def test_imu_delegates_to_multiple_projects(self, client, tmp_path):
        """imu can delegate to conversations on different projects."""
        d1 = tmp_path / "proj1"
        d1.mkdir()
        d2 = tmp_path / "proj2"
        d2.mkdir()
        pid1 = _register_project(client, d1)
        pid2 = _register_project(client, d2)

        conv1 = client.post("/api/conversations", json={"project_id": pid1}).json()
        conv2 = client.post("/api/conversations", json={"project_id": pid2}).json()

        resp1 = _submit_task(client, conv1["id"], task="Fix bug in project 1")
        resp2 = _submit_task(client, conv2["id"], task="Add feature to project 2")

        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["run_id"] != resp2.json()["run_id"]

    def test_imu_conversation_isolated_from_project_delegation(self, client, tmp_path):
        """imu's own conversation and project conversations are fully separate."""
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)

        # imu creates its own conversation
        imu_conv = client.post("/api/imu/conversations").json()

        # imu also creates a project conversation for delegation
        proj_conv = client.post("/api/conversations", json={"project_id": pid}).json()

        # They are different conversations
        assert imu_conv["id"] != proj_conv["id"]

        # Each appears in the right listing
        imu_list = [c["id"] for c in client.get("/api/imu/conversations").json()]
        proj_list = [c["id"] for c in client.get(f"/api/projects/{pid}/conversations").json()["items"]]

        assert imu_conv["id"] in imu_list
        assert imu_conv["id"] not in proj_list
        assert proj_conv["id"] in proj_list
        assert proj_conv["id"] not in imu_list
