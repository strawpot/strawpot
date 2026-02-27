"""Tests for strawpot.config."""

from pathlib import Path

from strawpot.config import StrawpotConfig, get_strawpot_home, load_config


def test_defaults():
    config = StrawpotConfig()
    assert config.runtime == "claude_code"
    assert config.isolation == "none"
    assert config.denden_addr == "127.0.0.1:9700"
    assert config.orchestrator_role == "orchestrator"
    assert config.allowed_roles is None
    assert config.max_depth == 3
    assert config.agents == {}


def test_strawpot_home_default(monkeypatch):
    monkeypatch.delenv("STRAWPOT_HOME", raising=False)
    assert get_strawpot_home() == Path.home() / ".strawpot"


def test_strawpot_home_env(monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", "/tmp/custom-home")
    assert get_strawpot_home() == Path("/tmp/custom-home")


def test_load_config_no_files(tmp_path):
    config = load_config(tmp_path)
    assert config.runtime == "claude_code"
    assert config.denden_addr == "127.0.0.1:9700"


def test_load_config_global(tmp_path, monkeypatch):
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "config.toml").write_text(
        '[agents.claude_code]\nmodel = "claude-opus-4-6"\n'
    )
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    config = load_config(tmp_path / "project")
    assert config.agents == {"claude_code": {"model": "claude-opus-4-6"}}
    assert config.runtime == "claude_code"  # default preserved


def test_load_config_project_overrides_global(tmp_path, monkeypatch):
    # Global config
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "config.toml").write_text('runtime = "codex"\n')
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    # Project config
    project_dir = tmp_path / "project"
    strawpot_dir = project_dir / ".strawpot"
    strawpot_dir.mkdir(parents=True)
    (strawpot_dir / "config.toml").write_text('runtime = "openhands"\n')

    config = load_config(project_dir)
    assert config.runtime == "openhands"


def test_load_config_full(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "nonexistent"))

    project_dir = tmp_path / "project"
    strawpot_dir = project_dir / ".strawpot"
    strawpot_dir.mkdir(parents=True)
    (strawpot_dir / "config.toml").write_text(
        'runtime = "codex"\n'
        'isolation = "docker"\n'
        "\n"
        "[denden]\n"
        'addr = "0.0.0.0:8080"\n'
        "\n"
        "[orchestrator]\n"
        'role = "team-lead"\n'
        "\n"
        "[policy]\n"
        'allowed_roles = ["implementer", "reviewer"]\n'
        "max_depth = 5\n"
        "\n"
        "[agents.claude_code]\n"
        'model = "claude-sonnet-4-6"\n'
    )

    config = load_config(project_dir)
    assert config.runtime == "codex"
    assert config.isolation == "docker"
    assert config.denden_addr == "0.0.0.0:8080"
    assert config.orchestrator_role == "team-lead"
    assert config.allowed_roles == ["implementer", "reviewer"]
    assert config.max_depth == 5
    assert config.agents == {"claude_code": {"model": "claude-sonnet-4-6"}}


def test_load_config_agents_merge(tmp_path, monkeypatch):
    """Agent config from project overrides global per-key, not wholesale."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "config.toml").write_text(
        '[agents.claude_code]\nmodel = "claude-opus-4-6"\ntimeout = 300\n'
    )
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    project_dir = tmp_path / "project"
    strawpot_dir = project_dir / ".strawpot"
    strawpot_dir.mkdir(parents=True)
    (strawpot_dir / "config.toml").write_text(
        '[agents.claude_code]\nmodel = "claude-sonnet-4-6"\n'
    )

    config = load_config(project_dir)
    assert config.agents == {
        "claude_code": {"model": "claude-sonnet-4-6", "timeout": 300}
    }
