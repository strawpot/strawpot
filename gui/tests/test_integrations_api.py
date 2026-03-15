"""Tests for integration management API endpoints."""

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Patch get_strawpot_home to use a temp directory."""
    monkeypatch.setattr(
        "strawpot_gui.routers.integrations.get_strawpot_home", lambda: tmp_path
    )
    return tmp_path


def _create_integration(home, name, extra_meta=""):
    """Create a minimal INTEGRATION.md manifest."""
    integration_dir = home / "integrations" / name
    integration_dir.mkdir(parents=True)
    content = (
        f"---\nname: {name}\ndescription: A test {name} adapter\n"
        f"metadata:\n  strawpot:\n    entry_point: python adapter.py\n"
        f"    auto_start: false\n"
        f"    config:\n"
        f"      bot_token:\n"
        f"        type: secret\n"
        f"        required: true\n"
        f"        description: Bot API token\n"
        f"{extra_meta}"
        f"---\n# {name.title()} Adapter\n\nBody text."
    )
    (integration_dir / "INTEGRATION.md").write_text(content)
    return integration_dir


class TestListIntegrations:
    def test_list_empty(self, client, home):
        resp = client.get("/api/integrations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_one(self, client, home):
        _create_integration(home, "telegram")
        resp = client.get("/api/integrations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]
        assert item["name"] == "telegram"
        assert item["description"] == "A test telegram adapter"
        assert item["entry_point"] == "python adapter.py"
        assert item["status"] == "stopped"
        assert item["pid"] is None

    def test_list_multiple(self, client, home):
        _create_integration(home, "telegram")
        _create_integration(home, "slack")
        resp = client.get("/api/integrations")
        names = [i["name"] for i in resp.json()]
        assert "slack" in names
        assert "telegram" in names

    def test_excludes_hidden_dirs(self, client, home):
        _create_integration(home, "telegram")
        hidden = home / "integrations" / ".hidden"
        hidden.mkdir(parents=True)
        (hidden / "INTEGRATION.md").write_text("---\nname: hidden\n---\n")
        resp = client.get("/api/integrations")
        names = [i["name"] for i in resp.json()]
        assert "telegram" in names
        assert "hidden" not in names


class TestGetIntegration:
    def test_get_detail(self, client, home):
        _create_integration(home, "telegram")
        resp = client.get("/api/integrations/telegram")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "telegram"
        assert data["body"].strip().startswith("# Telegram Adapter")
        assert "frontmatter" in data
        assert data["status"] == "stopped"

    def test_get_not_found(self, client, home):
        resp = client.get("/api/integrations/nonexistent")
        assert resp.status_code == 404


class TestIntegrationConfig:
    def test_get_config_schema(self, client, home):
        _create_integration(home, "telegram")
        resp = client.get("/api/integrations/telegram/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "bot_token" in data["config_schema"]
        assert data["config_schema"]["bot_token"]["type"] == "secret"
        assert data["config_values"] == {}

    def test_put_config(self, client, home):
        _create_integration(home, "telegram")
        resp = client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"bot_token": "123:ABC"}},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Verify saved
        resp = client.get("/api/integrations/telegram/config")
        assert resp.json()["config_values"]["bot_token"] == "123:ABC"

    def test_put_config_updates_existing(self, client, home):
        _create_integration(home, "telegram")
        client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"bot_token": "old"}},
        )
        client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"bot_token": "new"}},
        )
        resp = client.get("/api/integrations/telegram/config")
        assert resp.json()["config_values"]["bot_token"] == "new"

    def test_put_config_not_found(self, client, home):
        resp = client.put(
            "/api/integrations/nonexistent/config",
            json={"config_values": {"key": "val"}},
        )
        assert resp.status_code == 404

    def test_delete_config(self, client, home):
        _create_integration(home, "telegram")
        client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"bot_token": "123:ABC"}},
        )
        resp = client.delete("/api/integrations/telegram/config")
        assert resp.status_code == 200

        # Config should be cleared
        resp = client.get("/api/integrations/telegram/config")
        assert resp.json()["config_values"] == {}

    def test_config_visible_in_list(self, client, home):
        """Saved config values appear when listing integrations."""
        _create_integration(home, "telegram")
        client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"bot_token": "123:ABC"}},
        )
        resp = client.get("/api/integrations")
        item = resp.json()[0]
        assert item["config_values"]["bot_token"] == "123:ABC"
