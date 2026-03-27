"""Tests for config read/write endpoints."""

import tomllib
from pathlib import Path


class TestGlobalConfig:
    def test_get_empty_global_config(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "home"))
        resp = client.get("/api/config/global")
        assert resp.status_code == 200
        body = resp.json()
        assert body["values"] == {}
        assert "defaults" in body
        assert body["defaults"]["runtime"] == "strawpot-claude-code"

    def test_put_and_get_global_config(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "home"))
        data = {"runtime": "codex"}

        resp = client.put("/api/config/global", json=data)
        assert resp.status_code == 200
        assert resp.json() == data

        # Verify file was written
        path = tmp_path / "home" / "strawpot.toml"
        assert path.is_file()
        with open(path, "rb") as f:
            written = tomllib.load(f)
        assert written == data

        # Verify round-trip via GET
        resp = client.get("/api/config/global")
        body = resp.json()
        assert body["values"] == data
        assert "defaults" in body


class TestProjectConfig:
    def _create_project(self, client, working_dir):
        resp = client.post("/api/projects", json={
            "display_name": "Test",
            "working_dir": str(working_dir),
        })
        return resp.json()["id"]

    def test_get_project_config_empty(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "home"))
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = self._create_project(client, project_dir)

        resp = client.get(f"/api/projects/{pid}/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "merged" in data
        assert "project" in data
        assert "global" in data
        # No config files → project and global are empty dicts
        assert data["project"] == {}
        assert data["global"] == {}
        # Merged should have defaults
        assert data["merged"]["runtime"] == "strawpot-claude-code"

    def test_put_and_get_project_config(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "home"))
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = self._create_project(client, project_dir)

        config_data = {"runtime": "codex"}
        resp = client.put(f"/api/projects/{pid}/config", json=config_data)
        assert resp.status_code == 200

        # Verify file written
        path = project_dir / "strawpot.toml"
        assert path.is_file()

        # Verify merged config picks up the override
        resp = client.get(f"/api/projects/{pid}/config")
        data = resp.json()
        assert data["project"] == {"runtime": "codex"}
        assert data["merged"]["runtime"] == "codex"

    def test_merged_shows_both_sources(self, client, tmp_path, monkeypatch):
        home = tmp_path / "home"
        monkeypatch.setenv("STRAWPOT_HOME", str(home))

        # Write global config
        client.put("/api/config/global", json={"runtime": "global_rt"})

        # Create project with its own config
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = self._create_project(client, project_dir)
        client.put(f"/api/projects/{pid}/config", json={"memory": "local"})

        resp = client.get(f"/api/projects/{pid}/config")
        data = resp.json()
        assert data["global"] == {"runtime": "global_rt"}
        assert data["project"] == {"memory": "local"}
        # Merged has global runtime + project memory
        assert data["merged"]["runtime"] == "global_rt"
        assert data["merged"]["memory"] == "local"

    def test_project_not_found(self, client):
        resp = client.get("/api/projects/999/config")
        assert resp.status_code == 404

    def test_put_project_not_found(self, client):
        resp = client.put("/api/projects/999/config", json={"runtime": "x"})
        assert resp.status_code == 404

    def test_put_preserves_skills_and_roles(self, client, tmp_path, monkeypatch):
        """Saving config form should not wipe skills/roles env values."""
        monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "home"))
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = self._create_project(client, project_dir)

        # Pre-populate toml with skills env values
        import tomli_w
        existing = {
            "runtime": "old-rt",
            "skills": {
                "notify-telegram": {"env": {"TOKEN": "secret"}},
                "browse": "*",
            },
            "roles": {"my-role": "*"},
        }
        with open(project_dir / "strawpot.toml", "wb") as f:
            tomli_w.dump(existing, f)

        # Save config form (only has runtime, no skills/roles)
        resp = client.put(f"/api/projects/{pid}/config", json={"runtime": "new-rt"})
        assert resp.status_code == 200

        # Verify skills and roles survived
        import tomllib
        with open(project_dir / "strawpot.toml", "rb") as f:
            written = tomllib.load(f)
        assert written["runtime"] == "new-rt"
        assert written["skills"]["notify-telegram"]["env"]["TOKEN"] == "secret"
        assert written["skills"]["browse"] == "*"
        assert written["roles"]["my-role"] == "*"

    def test_put_global_preserves_skills(self, client, tmp_path, monkeypatch):
        """Saving global config form should not wipe skills env values."""
        home = tmp_path / "home"
        monkeypatch.setenv("STRAWPOT_HOME", str(home))

        # Pre-populate global toml
        import tomli_w
        home.mkdir(parents=True, exist_ok=True)
        existing = {
            "runtime": "old",
            "agents": {"my-agent": {"env": {"KEY": "val"}}},
        }
        with open(home / "strawpot.toml", "wb") as f:
            tomli_w.dump(existing, f)

        # Save form data without agents section
        resp = client.put("/api/config/global", json={"runtime": "new"})
        assert resp.status_code == 200

        import tomllib
        with open(home / "strawpot.toml", "rb") as f:
            written = tomllib.load(f)
        assert written["runtime"] == "new"
        assert written["agents"]["my-agent"]["env"]["KEY"] == "val"
