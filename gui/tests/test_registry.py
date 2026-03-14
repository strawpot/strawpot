"""Tests for resource registry endpoints."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Patch get_strawpot_home to use a temp directory."""
    monkeypatch.setattr(
        "strawpot_gui.routers.registry.get_strawpot_home", lambda: tmp_path
    )
    return tmp_path


def _create_role(home, name, content=None):
    """Create a minimal role manifest."""
    role_dir = home / "roles" / name
    role_dir.mkdir(parents=True)
    if content is None:
        content = (
            f"---\nname: {name}\ndescription: A test role\n"
            f"metadata:\n  version: '1.0'\n---\nRole body"
        )
    (role_dir / "ROLE.md").write_text(content)
    return role_dir


def _create_skill(home, name):
    """Create a minimal skill manifest."""
    skill_dir = home / "skills" / name
    skill_dir.mkdir(parents=True)
    content = (
        f"---\nname: {name}\ndescription: A test skill\n"
        f"metadata:\n  version: '1.0'\n---\nSkill body"
    )
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


class TestListResources:
    def test_list_empty(self, client, home):
        resp = client.get("/api/registry/roles")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_roles(self, client, home):
        _create_role(home, "leader")
        _create_role(home, "coder")
        resp = client.get("/api/registry/roles")
        assert resp.status_code == 200
        names = [r["name"] for r in resp.json()]
        assert "leader" in names
        assert "coder" in names

    def test_list_skills(self, client, home):
        _create_skill(home, "my-skill")
        resp = client.get("/api/registry/skills")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "my-skill"

    def test_invalid_type_returns_400(self, client, home):
        resp = client.get("/api/registry/foobar")
        assert resp.status_code == 400

    def test_excludes_hidden_dirs(self, client, home):
        _create_role(home, "visible")
        hidden = home / "roles" / ".hidden"
        hidden.mkdir(parents=True)
        (hidden / "ROLE.md").write_text("---\nname: hidden\n---\n")

        resp = client.get("/api/registry/roles")
        names = [r["name"] for r in resp.json()]
        assert "visible" in names
        assert ".hidden" not in names
        assert "hidden" not in names


class TestGetResource:
    def test_get_role(self, client, home):
        _create_role(home, "test-role")
        resp = client.get("/api/registry/roles/test-role")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-role"
        assert "Role body" in data["body"]
        assert "frontmatter" in data

    def test_not_found(self, client, home):
        resp = client.get("/api/registry/roles/nonexistent")
        assert resp.status_code == 404

    def test_version_from_file(self, client, home):
        role_dir = _create_role(home, "versioned")
        (role_dir / ".version").write_text("2.5.0")
        resp = client.get("/api/registry/roles/versioned")
        assert resp.json()["version"] == "2.5.0"


class TestValidateType:
    def test_valid_types(self, client, home):
        for t in ["roles", "skills", "agents", "memories"]:
            resp = client.get(f"/api/registry/{t}")
            assert resp.status_code == 200

    def test_invalid_type(self, client, home):
        resp = client.get("/api/registry/widgets")
        assert resp.status_code == 400


class TestInstallResource:
    def test_missing_fields_returns_400(self, client, home):
        resp = client.post("/api/registry/install", json={})
        assert resp.status_code == 400

    def test_missing_name_returns_400(self, client, home):
        resp = client.post("/api/registry/install", json={"type": "roles"})
        assert resp.status_code == 400

    def test_missing_type_returns_400(self, client, home):
        resp = client.post("/api/registry/install", json={"name": "foo"})
        assert resp.status_code == 400


class TestUpdateResource:
    def test_missing_fields_returns_400(self, client, home):
        resp = client.post("/api/registry/update", json={})
        assert resp.status_code == 400


class TestReinstallResource:
    def test_missing_fields_returns_400(self, client, home):
        resp = client.post("/api/registry/reinstall", json={})
        assert resp.status_code == 400

    def test_not_found_returns_404(self, client, home):
        resp = client.post(
            "/api/registry/reinstall",
            json={"type": "roles", "name": "nonexistent"},
        )
        assert resp.status_code == 404


class TestUninstallProtectedResources:
    """Built-in resources cannot be uninstalled."""

    @pytest.mark.parametrize("resource_type,name", [
        ("roles", "imu"),
        ("roles", "ai-ceo"),
        ("roles", "ai-employee"),
        ("skills", "denden"),
        ("skills", "strawpot-session-recap"),
        ("agents", "strawpot-claude-code"),
        ("memories", "dial"),
    ])
    def test_protected_resource_returns_403(self, client, home, resource_type, name):
        resp = client.delete(f"/api/registry/{resource_type}/{name}")
        assert resp.status_code == 403
        assert "built-in" in resp.json()["detail"]

    def test_non_protected_resource_proceeds(self, client, home):
        """Non-protected resources are not blocked by the guard."""
        _create_role(home, "custom-role")
        # This will fail with strawhub not on PATH, but it should NOT be 403
        resp = client.delete("/api/registry/roles/custom-role")
        assert resp.status_code != 403
