"""Tests for Bot Imu endpoints and virtual project initialization."""

from pathlib import Path

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
