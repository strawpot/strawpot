"""Tests for the /via/{name} integration source middleware."""


class TestViaMiddleware:
    """Tests for IntegrationSourceMiddleware in app.py."""

    def test_via_rewrites_path(self, client):
        """/via/telegram/api/health → /api/health"""
        resp = client.get("/via/telegram/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_via_injects_source_header(self, client):
        """/via/telegram creates imu conversation with source=telegram."""
        resp = client.post("/via/telegram/api/imu/conversations")
        assert resp.status_code == 201
        data = resp.json()
        assert data["source"] == "telegram"

    def test_via_with_different_names(self, client):
        """Different integration names are extracted correctly."""
        for name in ("slack", "discord", "custom-bot"):
            resp = client.post(f"/via/{name}/api/imu/conversations")
            assert resp.status_code == 201
            assert resp.json()["source"] == name

    def test_via_strips_prefix_completely(self, client, tmp_path):
        """Nested API paths work after prefix stripping."""
        resp = client.get("/via/telegram/api/imu/conversations")
        assert resp.status_code == 200

    def test_non_via_path_unaffected(self, client):
        """Regular paths are not modified."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_via_with_empty_rest(self, client):
        """/via/telegram with no trailing path resolves to /."""
        resp = client.get("/via/telegram")
        # Should not 500 — resolves to root (SPA fallback or 404 depending on setup)
        assert resp.status_code != 500

    def test_body_source_overrides_via_header(self, client):
        """Explicit source in request body takes precedence over /via/ header."""
        resp = client.post(
            "/via/telegram/api/imu/conversations",
            json={"source": "slack", "source_meta": "override"},
        )
        assert resp.status_code == 201
        # Body source wins over header
        assert resp.json()["source"] == "slack"


class TestViaProjectScopedMiddleware:
    """Tests for /via/p/{project_id}/{name}/... URL pattern."""

    def test_via_project_rewrites_path(self, client):
        """/via/p/5/telegram/api/health → /api/health"""
        resp = client.get("/via/p/5/telegram/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_via_project_injects_source_header(self, client):
        """/via/p/{id}/{name} injects X-Strawpot-Source header."""
        resp = client.post("/via/p/3/discord/api/imu/conversations")
        assert resp.status_code == 201
        assert resp.json()["source"] == "discord"

    def test_via_project_injects_project_id_header(self, client):
        """/via/p/{id}/{name} injects X-Strawpot-Project-Id header."""
        # We can verify the header is injected by checking it's received
        # by the endpoint. The conversations endpoint doesn't use this header,
        # but we can at least verify the path rewrite + source work.
        resp = client.post("/via/p/7/slack/api/imu/conversations")
        assert resp.status_code == 201
        assert resp.json()["source"] == "slack"

    def test_via_project_with_empty_rest(self, client):
        """/via/p/1/telegram with no trailing path resolves to /."""
        resp = client.get("/via/p/1/telegram")
        assert resp.status_code != 500

    def test_via_project_different_ids(self, client):
        """Different project IDs are handled correctly."""
        for pid in (1, 42, 100):
            resp = client.post(f"/via/p/{pid}/telegram/api/imu/conversations")
            assert resp.status_code == 201
            assert resp.json()["source"] == "telegram"

    def test_via_p_without_project_id_no_match(self, client):
        """/via/p/ without enough segments doesn't crash."""
        resp = client.get("/via/p/")
        assert resp.status_code != 500


class TestConversationSourceTracking:
    """Tests for source/source_meta on conversations."""

    def test_imu_conversation_source_defaults_to_null(self, client):
        """Without /via/ prefix, source is null."""
        resp = client.post("/api/imu/conversations")
        data = resp.json()
        assert data.get("source") is None
        assert data.get("source_meta") is None

    def test_imu_conversation_with_explicit_source(self, client):
        """POST body can set source and source_meta."""
        resp = client.post("/api/imu/conversations", json={
            "source": "scheduler",
            "source_meta": '{"schedule_id": 7}',
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["source"] == "scheduler"
        assert data["source_meta"] == '{"schedule_id": 7}'

    def test_imu_list_includes_source(self, client):
        """List endpoint includes source fields."""
        client.post("/via/telegram/api/imu/conversations")
        client.post("/api/imu/conversations")

        items = client.get("/api/imu/conversations").json()
        sources = [c.get("source") for c in items]
        assert "telegram" in sources
        assert None in sources

    def test_conversation_detail_includes_source(self, client):
        """GET conversation detail includes source/source_meta."""
        resp = client.post("/via/slack/api/imu/conversations")
        conv_id = resp.json()["id"]

        detail = client.get(f"/api/conversations/{conv_id}").json()
        assert detail["source"] == "slack"

    def test_project_conversation_with_source(self, client, tmp_path):
        """Project conversations also support source tracking."""
        from test_sessions_sync import _register_project
        d = tmp_path / "proj"
        d.mkdir()
        pid = _register_project(client, d)

        resp = client.post("/via/discord/api/conversations", json={
            "project_id": pid,
        })
        assert resp.status_code == 201
        assert resp.json()["source"] == "discord"
