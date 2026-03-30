"""Tests for strawpot.config."""

import tomllib
from pathlib import Path

from strawpot.config import (
    StrawPotConfig,
    get_strawpot_home,
    has_explicit_runtime,
    load_config,
    save_skill_env,
)


def test_defaults():
    config = StrawPotConfig()
    assert config.runtime == "strawpot-claude-code"
    assert config.denden_addr == "127.0.0.1:9700"
    assert config.orchestrator_role == "ai-ceo"
    assert config.max_depth == 3
    assert config.permission_mode == "default"
    assert config.agent_timeout is None
    assert config.max_delegate_retries == 0
    assert config.agents == {}
    assert config.skills == {}
    assert config.roles == {}
    assert config.memory == "dial"
    assert config.memory_config == {}
    assert config.pull_before_session == "prompt"
    assert config.trace is True


def test_strawpot_home_default(monkeypatch):
    monkeypatch.delenv("STRAWPOT_HOME", raising=False)
    assert get_strawpot_home() == Path.home() / ".strawpot"


def test_strawpot_home_env(monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", "/tmp/custom-home")
    assert get_strawpot_home() == Path("/tmp/custom-home")


def test_load_config_no_files(tmp_path):
    config = load_config(tmp_path)
    assert config.runtime == "strawpot-claude-code"
    assert config.denden_addr == "127.0.0.1:9700"


def test_load_config_global(tmp_path, monkeypatch):
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text(
        '[agents."strawpot-claude-code"]\nmodel = "claude-opus-4-6"\n'
    )
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    config = load_config(tmp_path / "project")
    assert config.agents == {"strawpot-claude-code": {"model": "claude-opus-4-6"}}
    assert config.runtime == "strawpot-claude-code"  # default preserved


def test_load_config_project_overrides_global(tmp_path, monkeypatch):
    # Global config
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text('runtime = "codex"\n')
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    # Project config
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text('runtime = "openhands"\n')

    config = load_config(project_dir)
    assert config.runtime == "openhands"


def test_load_config_full(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "nonexistent"))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text(
        'runtime = "codex"\n'
        'memory = "test-provider"\n'
        "\n"
        "[denden]\n"
        'addr = "0.0.0.0:8080"\n'
        "\n"
        "[orchestrator]\n"
        'role = "team-lead"\n'
        'permission_mode = "plan"\n'
        "\n"
        "[policy]\n"
        "max_depth = 5\n"
        "agent_timeout = 300\n"
        "max_delegate_retries = 2\n"
        "\n"
        "[session]\n"
        'pull_before_session = "auto"\n'
        "\n"
        "[memory_config]\n"
        'storage_dir = "/custom/mem"\n'
        "\n"
        '[agents."strawpot-claude-code"]\n'
        'model = "claude-sonnet-4-6"\n'
    )

    config = load_config(project_dir)
    assert config.runtime == "codex"
    assert config.denden_addr == "0.0.0.0:8080"
    assert config.orchestrator_role == "team-lead"
    assert config.max_depth == 5
    assert config.permission_mode == "plan"
    assert config.agent_timeout == 300
    assert config.max_delegate_retries == 2
    assert config.agents == {"strawpot-claude-code": {"model": "claude-sonnet-4-6"}}
    assert config.memory == "test-provider"
    assert config.memory_config == {"storage_dir": "/custom/mem"}
    assert config.pull_before_session == "auto"


def test_load_config_session_override(tmp_path, monkeypatch):
    """Project [session] overrides global [session] per-key."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text(
        "[session]\n"
        'pull_before_session = "never"\n'
    )
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text(
        "[session]\n"
        'pull_before_session = "always"\n'
    )

    config = load_config(project_dir)
    assert config.pull_before_session == "always"


def test_load_config_agents_merge(tmp_path, monkeypatch):
    """Agent config from project overrides global per-key, not wholesale."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text(
        '[agents."strawpot-claude-code"]\nmodel = "claude-opus-4-6"\ntimeout = 300\n'
    )
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text(
        '[agents."strawpot-claude-code"]\nmodel = "claude-sonnet-4-6"\n'
    )

    config = load_config(project_dir)
    assert config.agents == {
        "strawpot-claude-code": {"model": "claude-sonnet-4-6", "timeout": 300}
    }


def test_load_config_memory_merge(tmp_path, monkeypatch):
    """Memory config from project merges with global per-key."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text(
        'memory = "my-provider"\n'
        "\n"
        "[memory_config]\n"
        'storage_dir = "/global/mem"\n'
        "em_max_events = 5000\n"
    )
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text(
        "[memory_config]\n"
        'storage_dir = "/project/mem"\n'
    )

    config = load_config(project_dir)
    assert config.memory == "my-provider"
    assert config.memory_config["storage_dir"] == "/project/mem"
    assert config.memory_config["em_max_events"] == 5000


def test_load_config_memory_settings(tmp_path, monkeypatch):
    """[memory_settings] section sets semantic_search and graph flags."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "nonexistent"))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text(
        "[memory_settings]\n"
        "semantic_search = true\n"
        "graph = false\n"
    )

    config = load_config(project_dir)
    assert config.semantic_search is True
    assert config.memory_graph is False


def test_load_config_memory_settings_defaults(tmp_path, monkeypatch):
    """Memory settings default to semantic_search=false, graph=true."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "nonexistent"))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text("")

    config = load_config(project_dir)
    assert config.semantic_search is False
    assert config.memory_graph is True


def test_load_config_skills_env(tmp_path, monkeypatch):
    """[skills.<slug>.env] values are loaded into config.skills."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "nonexistent"))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text(
        "[skills.github_pr.env]\n"
        'GITHUB_TOKEN = "ghp_abc"\n'
    )

    config = load_config(project_dir)
    assert config.skills == {"github_pr": {"GITHUB_TOKEN": "ghp_abc"}}


def test_load_config_roles(tmp_path, monkeypatch):
    """[roles.<slug>] values are loaded into config.roles."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "nonexistent"))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text(
        "[roles.implementer]\n"
        'default_agent = "strawpot-claude-code"\n'
    )

    config = load_config(project_dir)
    assert config.roles == {"implementer": {"default_agent": "strawpot-claude-code"}}


def test_skills_env_merge_global_project(tmp_path, monkeypatch):
    """Skill env from project overrides global per-key, not wholesale."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text(
        "[skills.my_skill.env]\n"
        'TOKEN = "global_token"\n'
        'EXTRA = "global_extra"\n'
    )
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text(
        "[skills.my_skill.env]\n"
        'TOKEN = "project_token"\n'
    )

    config = load_config(project_dir)
    assert config.skills == {
        "my_skill": {"TOKEN": "project_token", "EXTRA": "global_extra"}
    }


def test_roles_merge_global_project(tmp_path, monkeypatch):
    """Role overrides from project merge with global per-key."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text(
        "[roles.implementer]\n"
        'default_agent = "codex"\n'
    )
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text(
        "[roles.implementer]\n"
        'default_agent = "strawpot-claude-code"\n'
    )

    config = load_config(project_dir)
    assert config.roles == {"implementer": {"default_agent": "strawpot-claude-code"}}


def test_trace_disabled_via_toml(tmp_path, monkeypatch):
    """[trace] enabled = false disables tracing."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "nonexistent"))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text(
        "[trace]\n"
        "enabled = false\n"
    )

    config = load_config(project_dir)
    assert config.trace is False


def test_save_skill_env_creates_file(tmp_path):
    """save_skill_env creates strawpot.toml from scratch."""
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)

    save_skill_env(project_dir, "my_skill", {"TOKEN": "abc123"})

    toml_path = project_dir / "strawpot.toml"
    assert toml_path.exists()
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    assert data["skills"]["my_skill"]["env"]["TOKEN"] == "abc123"


def test_save_skill_env_merges_existing(tmp_path):
    """save_skill_env preserves existing content and merges."""
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "strawpot.toml").write_text(
        'runtime = "codex"\n'
        "\n"
        "[skills.my_skill.env]\n"
        'EXISTING = "keep"\n'
    )

    save_skill_env(project_dir, "my_skill", {"NEW_VAR": "new_val"})

    with open(project_dir / "strawpot.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["runtime"] == "codex"
    assert data["skills"]["my_skill"]["env"]["EXISTING"] == "keep"
    assert data["skills"]["my_skill"]["env"]["NEW_VAR"] == "new_val"


# ---------------------------------------------------------------------------
# has_explicit_runtime
# ---------------------------------------------------------------------------


def test_has_explicit_runtime_false_when_no_files(tmp_path, monkeypatch):
    """Returns False when no config files exist."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "empty"))
    assert has_explicit_runtime(tmp_path / "project") is False


def test_has_explicit_runtime_false_when_no_runtime_key(tmp_path, monkeypatch):
    """Returns False when config exists but has no runtime key."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text('memory = "dial"\n')
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))
    assert has_explicit_runtime(tmp_path / "project") is False


def test_has_explicit_runtime_true_in_global(tmp_path, monkeypatch):
    """Returns True when runtime is set in global config."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text('runtime = "strawpot-gemini"\n')
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))
    assert has_explicit_runtime(tmp_path / "project") is True


def test_has_explicit_runtime_true_in_project(tmp_path, monkeypatch):
    """Returns True when runtime is set in project config only."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text('memory = "dial"\n')
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "strawpot.toml").write_text('runtime = "strawpot-codex"\n')
    assert has_explicit_runtime(project_dir) is True


def test_has_explicit_runtime_no_project_dir(tmp_path, monkeypatch):
    """Returns False when no project_dir given and global has no runtime."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text('memory = "dial"\n')
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))
    assert has_explicit_runtime(None) is False
