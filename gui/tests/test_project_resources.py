"""Tests for project-scoped resource endpoints."""

import pytest
import tomli_w


@pytest.fixture
def global_home(tmp_path, monkeypatch):
    """Patch get_strawpot_home to use a temp directory for global resources."""
    home = tmp_path / "global_home"
    home.mkdir()
    monkeypatch.setattr(
        "strawpot_gui.routers.project_resources.get_strawpot_home", lambda: home
    )
    return home


def _setup_project(client, tmp_path):
    """Create a project and return (project_id, project_dir)."""
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / ".strawpot").mkdir()
    resp = client.post("/api/projects", json={
        "display_name": "Test",
        "working_dir": str(project_dir),
    })
    return resp.json()["id"], project_dir


def _install_skill(base_dir, name, env_schema=None):
    """Create a minimal skill manifest under base_dir/skills/."""
    skill_dir = base_dir / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    env_block = ""
    if env_schema:
        env_lines = "\n".join(
            f"      {k}:\n        description: '{v}'" for k, v in env_schema.items()
        )
        env_block = f"\n  strawpot:\n    env:\n{env_lines}"
    content = (
        f"---\nname: {name}\ndescription: A test skill\n"
        f"metadata:\n  version: '1.0'{env_block}\n---\nSkill body"
    )
    (skill_dir / "SKILL.md").write_text(content)


def _install_role(base_dir, name):
    """Create a minimal role manifest under base_dir/roles/."""
    role_dir = base_dir / "roles" / name
    role_dir.mkdir(parents=True, exist_ok=True)
    content = (
        f"---\nname: {name}\ndescription: A test role\n"
        f"metadata:\n  version: '1.0'\n  strawpot:\n    default_agent: default\n"
        f"---\nRole body"
    )
    (role_dir / "ROLE.md").write_text(content)


def _write_toml(project_dir, data):
    """Write strawpot.toml in the project directory."""
    (project_dir / "strawpot.toml").write_bytes(tomli_w.dumps(data).encode())


class TestListProjectResources:
    def test_empty(self, client, tmp_path, global_home):
        pid, _ = _setup_project(client, tmp_path)
        resp = client.get(f"/api/projects/{pid}/resources")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_project_resources(self, client, tmp_path, global_home):
        pid, project_dir = _setup_project(client, tmp_path)
        _install_skill(project_dir / ".strawpot", "my-skill")
        resp = client.get(f"/api/projects/{pid}/resources")
        assert resp.status_code == 200
        resources = resp.json()
        assert len(resources) == 1
        assert resources[0]["name"] == "my-skill"
        assert resources[0]["type"] == "skills"
        assert resources[0]["source"] == "project"

    def test_includes_global_resources(self, client, tmp_path, global_home):
        pid, _ = _setup_project(client, tmp_path)
        _install_skill(global_home, "global-skill")
        resp = client.get(f"/api/projects/{pid}/resources")
        resources = resp.json()
        assert len(resources) == 1
        assert resources[0]["name"] == "global-skill"
        assert resources[0]["source"] == "global"

    def test_project_shadows_global(self, client, tmp_path, global_home):
        """When same name exists in both, project-local wins."""
        pid, project_dir = _setup_project(client, tmp_path)
        _install_skill(global_home, "shared-skill")
        _install_skill(project_dir / ".strawpot", "shared-skill")
        resp = client.get(f"/api/projects/{pid}/resources")
        resources = resp.json()
        skills = [r for r in resources if r["name"] == "shared-skill"]
        assert len(skills) == 1
        assert skills[0]["source"] == "project"

    def test_config_count_zero_without_toml(self, client, tmp_path, global_home):
        pid, project_dir = _setup_project(client, tmp_path)
        _install_skill(project_dir / ".strawpot", "bare-skill")
        resp = client.get(f"/api/projects/{pid}/resources")
        resources = resp.json()
        assert resources[0]["config_count"] == 0

    def test_config_count_skill_env(self, client, tmp_path, global_home):
        pid, project_dir = _setup_project(client, tmp_path)
        _install_skill(project_dir / ".strawpot", "api-skill")
        _write_toml(project_dir, {
            "skills": {
                "api-skill": {
                    "env": {"API_KEY": "secret", "API_URL": "https://example.com"}
                }
            }
        })
        resp = client.get(f"/api/projects/{pid}/resources")
        resources = resp.json()
        assert resources[0]["config_count"] == 2

    def test_config_count_role_params(self, client, tmp_path, global_home):
        pid, project_dir = _setup_project(client, tmp_path)
        _install_role(project_dir / ".strawpot", "leader")
        _write_toml(project_dir, {
            "roles": {"leader": {"default_agent": "claude"}}
        })
        resp = client.get(f"/api/projects/{pid}/resources")
        role = [r for r in resp.json() if r["type"] == "roles"][0]
        assert role["config_count"] == 1

    def test_config_count_on_global_resource(self, client, tmp_path, global_home):
        """Global resources show project-level config overrides."""
        pid, project_dir = _setup_project(client, tmp_path)
        _install_skill(global_home, "twitter-api")
        _write_toml(project_dir, {
            "skills": {
                "twitter-api": {"env": {"TWITTER_TOKEN": "tok123"}}
            }
        })
        resp = client.get(f"/api/projects/{pid}/resources")
        resources = resp.json()
        skill = [r for r in resources if r["name"] == "twitter-api"][0]
        assert skill["source"] == "global"
        assert skill["config_count"] == 1

    def test_config_count_mixed(self, client, tmp_path, global_home):
        """Resources without overrides show 0, those with overrides show count."""
        pid, project_dir = _setup_project(client, tmp_path)
        _install_skill(project_dir / ".strawpot", "configured")
        _install_skill(project_dir / ".strawpot", "unconfigured")
        _write_toml(project_dir, {
            "skills": {
                "configured": {"env": {"TOKEN": "abc"}}
            }
        })
        resp = client.get(f"/api/projects/{pid}/resources")
        resources = {r["name"]: r for r in resp.json()}
        assert resources["configured"]["config_count"] == 1
        assert resources["unconfigured"]["config_count"] == 0


class TestGetProjectResource:
    def test_get_project_resource(self, client, tmp_path, global_home):
        pid, project_dir = _setup_project(client, tmp_path)
        _install_skill(project_dir / ".strawpot", "local-skill")
        resp = client.get(f"/api/projects/{pid}/resources/skills/local-skill")
        assert resp.status_code == 200
        assert resp.json()["source"] == "project"

    def test_get_global_resource(self, client, tmp_path, global_home):
        pid, _ = _setup_project(client, tmp_path)
        _install_skill(global_home, "global-skill")
        resp = client.get(f"/api/projects/{pid}/resources/skills/global-skill")
        assert resp.status_code == 200
        assert resp.json()["source"] == "global"

    def test_not_found(self, client, tmp_path, global_home):
        pid, _ = _setup_project(client, tmp_path)
        resp = client.get(f"/api/projects/{pid}/resources/skills/nonexistent")
        assert resp.status_code == 404


class TestUpdateAllProjectResources:
    def test_endpoint_exists(self, client, tmp_path, global_home):
        pid, _ = _setup_project(client, tmp_path)
        resp = client.post(f"/api/projects/{pid}/resources/update-all")
        # Will be 503 if strawhub not on PATH, or 200 if it is.
        assert resp.status_code != 404
        assert resp.status_code != 405

    def test_nonexistent_project_returns_404(self, client, tmp_path, global_home):
        resp = client.post("/api/projects/9999/resources/update-all")
        assert resp.status_code == 404

    def test_calls_strawhub_with_correct_args(self, client, tmp_path, global_home, monkeypatch):
        """Verify the correct strawhub arguments including --root and project dir."""
        pid, project_dir = _setup_project(client, tmp_path)
        captured_args = {}

        def fake_run(*args, **kwargs):
            captured_args["args"] = args
            captured_args["kwargs"] = kwargs
            return {"exit_code": 0, "stdout": "", "stderr": ""}

        monkeypatch.setattr(
            "strawpot_gui.routers.project_resources.run_strawhub", fake_run
        )
        resp = client.post(f"/api/projects/{pid}/resources/update-all")
        assert resp.status_code == 200
        assert captured_args["args"] == (
            "--root", str(project_dir), "update", "--all", "-y"
        )
        assert captured_args["kwargs"] == {"timeout": 300}


class TestProjectResourceConfig:
    def test_get_config_for_global_resource(self, client, tmp_path, global_home):
        """Can read config schema from global resource + saved values from project toml."""
        pid, project_dir = _setup_project(client, tmp_path)
        _install_skill(global_home, "api-skill", env_schema={"API_KEY": "Your API key"})
        _write_toml(project_dir, {
            "skills": {"api-skill": {"env": {"API_KEY": "secret"}}}
        })
        resp = client.get(f"/api/projects/{pid}/resources/skills/api-skill/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "API_KEY" in data["env_schema"]
        assert data["env_values"]["API_KEY"] == "secret"

    def test_config_not_found(self, client, tmp_path, global_home):
        pid, _ = _setup_project(client, tmp_path)
        resp = client.get(f"/api/projects/{pid}/resources/skills/missing/config")
        assert resp.status_code == 404
