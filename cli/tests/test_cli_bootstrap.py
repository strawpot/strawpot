"""Tests for strawpot.cli bootstrap helpers (_ensure_agent_installed, _ensure_skill_installed)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from strawpot.cli import (
    _ensure_agent_installed,
    _ensure_memory_installed,
    _ensure_role_installed,
    _ensure_skill_installed,
    needs_onboarding,
)
from strawpot.config import StrawPotConfig

# Prevent tests from finding real AGENT.md files in ~/.strawpot/
_EMPTY_HOME = Path("/nonexistent/strawpot_test_home")


# ---------------------------------------------------------------------------
# _ensure_agent_installed
# ---------------------------------------------------------------------------


@patch("strawpot.cli.resolve_agent")
def test_ensure_agent_already_installed(mock_resolve):
    """No prompt when the agent is already installed."""
    mock_resolve.return_value = MagicMock()  # resolve succeeds

    _ensure_agent_installed("strawpot-claude-code", "/tmp/project")

    mock_resolve.assert_called_once_with("strawpot-claude-code", "/tmp/project")


@patch("strawpot.cli.get_strawpot_home", return_value=_EMPTY_HOME)
@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=True)
@patch("strawpot.cli.resolve_agent", side_effect=FileNotFoundError("not found"))
def test_ensure_agent_installs_on_confirm(mock_resolve, mock_confirm, mock_which, mock_run, _):
    """Installs agent via strawhub when user confirms."""
    mock_run.return_value = MagicMock(returncode=0)

    _ensure_agent_installed("strawpot-claude-code", "/tmp/project")

    mock_confirm.assert_called_once()
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == ["/usr/bin/strawhub", "install", "agent", "strawpot-claude-code", "--global"]


@patch("strawpot.cli.get_strawpot_home", return_value=_EMPTY_HOME)
@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=False)
@patch("strawpot.cli.resolve_agent", side_effect=FileNotFoundError("not found"))
def test_ensure_agent_skips_on_decline(mock_resolve, mock_confirm, mock_which, mock_run, _):
    """Does nothing when user declines install."""
    _ensure_agent_installed("strawpot-claude-code", "/tmp/project")

    mock_confirm.assert_called_once()
    mock_run.assert_not_called()


@patch("strawpot.cli.get_strawpot_home", return_value=_EMPTY_HOME)
@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.shutil.which", return_value=None)
@patch("strawpot.cli.click.confirm", return_value=True)
@patch("strawpot.cli.resolve_agent", side_effect=FileNotFoundError("not found"))
def test_ensure_agent_strawhub_not_found(mock_resolve, mock_confirm, mock_which, mock_echo, _):
    """Shows error when strawhub CLI is not on PATH."""
    _ensure_agent_installed("strawpot-claude-code", "/tmp/project")

    # Should print error about missing strawhub
    calls = [str(c) for c in mock_echo.call_args_list]
    assert any("strawhub CLI not found" in c for c in calls)


@patch("strawpot.cli.get_strawpot_home", return_value=_EMPTY_HOME)
@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=True)
@patch("strawpot.cli.resolve_agent", side_effect=FileNotFoundError("not found"))
def test_ensure_agent_install_fails(mock_resolve, mock_confirm, mock_which, mock_run, mock_echo, _):
    """Shows error when install command fails."""
    mock_run.return_value = MagicMock(returncode=1)

    _ensure_agent_installed("strawpot-claude-code", "/tmp/project")

    calls = [str(c) for c in mock_echo.call_args_list]
    assert any("Failed to install agent" in c for c in calls)


def test_ensure_agent_runs_strawpot_install_from_frontmatter(tmp_path):
    """Runs metadata.strawpot.install.<os> from AGENT.md when binary is missing."""
    agent_dir = tmp_path / ".strawpot" / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text(
        "---\n"
        "name: test-agent\n"
        "metadata:\n"
        "  strawpot:\n"
        "    bin:\n"
        "      macos: test_agent\n"
        "      linux: test_agent\n"
        "    install:\n"
        "      macos: curl -fsSL https://example.com/install.sh | sh\n"
        "      linux: curl -fsSL https://example.com/install.sh | sh\n"
        "---\n"
    )
    # resolve_agent raises ValueError because binary doesn't exist
    with patch("strawpot.cli.resolve_agent", side_effect=ValueError("binary not found")), \
         patch("strawpot.cli.subprocess.run") as mock_run, \
         patch("strawpot.cli.click.echo"):
        mock_run.return_value = MagicMock(returncode=0)
        _ensure_agent_installed("test-agent", str(tmp_path))

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["sh", "-c", mock_run.call_args[0][0][2]]
        # Verify the install command from frontmatter was used
        assert "curl" in mock_run.call_args[0][0][2]


def test_ensure_agent_falls_back_to_install_sh(tmp_path):
    """Falls back to install.sh when no strawpot.install in AGENT.md."""
    agent_dir = tmp_path / ".strawpot" / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text(
        "---\n"
        "name: test-agent\n"
        "metadata:\n"
        "  strawpot:\n"
        "    bin:\n"
        "      macos: test_agent\n"
        "      linux: test_agent\n"
        "---\n"
    )
    (agent_dir / "install.sh").write_text("#!/bin/sh\necho installed\n")
    with patch("strawpot.cli.resolve_agent", side_effect=ValueError("binary not found")), \
         patch("strawpot.cli.subprocess.run") as mock_run, \
         patch("strawpot.cli.click.echo"):
        mock_run.return_value = MagicMock(returncode=0)
        _ensure_agent_installed("test-agent", str(tmp_path))

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["sh", str(agent_dir / "install.sh")]


# ---------------------------------------------------------------------------
# _ensure_skill_installed
# ---------------------------------------------------------------------------


def test_ensure_skill_already_installed_project_local(tmp_path):
    """No prompt when the skill exists in project-local .strawpot/skills/."""
    skill_dir = tmp_path / ".strawpot" / "skills" / "denden"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: denden\n---")

    with patch("strawpot.cli.click.confirm") as mock_confirm:
        _ensure_skill_installed("denden", str(tmp_path))
        mock_confirm.assert_not_called()


def test_ensure_skill_already_installed_global(tmp_path, monkeypatch):
    """No prompt when the skill exists in global ~/.strawpot/skills/."""
    global_home = tmp_path / "global_home"
    skill_dir = global_home / "skills" / "denden"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: denden\n---")
    monkeypatch.setenv("STRAWPOT_HOME", str(global_home))

    with patch("strawpot.cli.click.confirm") as mock_confirm:
        _ensure_skill_installed("denden", str(tmp_path / "project"))
        mock_confirm.assert_not_called()


@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=True)
def test_ensure_skill_installs_on_confirm(mock_confirm, mock_which, mock_run, tmp_path, monkeypatch):
    """Installs skill via strawhub when user confirms."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global_home"))
    mock_run.return_value = MagicMock(returncode=0)

    _ensure_skill_installed("denden", str(tmp_path / "project"))

    mock_confirm.assert_called_once()
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == ["/usr/bin/strawhub", "install", "skill", "denden", "--global"]


@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=False)
def test_ensure_skill_skips_on_decline(mock_confirm, mock_which, mock_run, tmp_path, monkeypatch):
    """Does nothing when user declines install."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global_home"))

    _ensure_skill_installed("denden", str(tmp_path / "project"))

    mock_confirm.assert_called_once()
    mock_run.assert_not_called()


@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.shutil.which", return_value=None)
@patch("strawpot.cli.click.confirm", return_value=True)
def test_ensure_skill_strawhub_not_found(mock_confirm, mock_which, mock_echo, tmp_path, monkeypatch):
    """Shows error when strawhub CLI is not on PATH."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global_home"))

    _ensure_skill_installed("denden", str(tmp_path / "project"))

    calls = [str(c) for c in mock_echo.call_args_list]
    assert any("strawhub CLI not found" in c for c in calls)


@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=True)
def test_ensure_skill_install_fails(mock_confirm, mock_which, mock_run, mock_echo, tmp_path, monkeypatch):
    """Shows error when install command fails."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global_home"))
    mock_run.return_value = MagicMock(returncode=1)

    _ensure_skill_installed("denden", str(tmp_path / "project"))

    calls = [str(c) for c in mock_echo.call_args_list]
    assert any("Failed to install skill" in c for c in calls)


# ---------------------------------------------------------------------------
# _ensure_role_installed
# ---------------------------------------------------------------------------


def test_ensure_role_already_installed_project_local(tmp_path):
    """No prompt when the role exists in project-local .strawpot/roles/."""
    role_dir = tmp_path / ".strawpot" / "roles" / "ai-ceo"
    role_dir.mkdir(parents=True)
    (role_dir / "ROLE.md").write_text("---\nname: ai-ceo\n---")

    with patch("strawpot.cli.click.confirm") as mock_confirm:
        _ensure_role_installed("ai-ceo", str(tmp_path))
        mock_confirm.assert_not_called()


def test_ensure_role_already_installed_global(tmp_path, monkeypatch):
    """No prompt when the role exists in global ~/.strawpot/roles/."""
    global_home = tmp_path / "global_home"
    role_dir = global_home / "roles" / "ai-ceo"
    role_dir.mkdir(parents=True)
    (role_dir / "ROLE.md").write_text("---\nname: ai-ceo\n---")
    monkeypatch.setenv("STRAWPOT_HOME", str(global_home))

    with patch("strawpot.cli.click.confirm") as mock_confirm:
        _ensure_role_installed("ai-ceo", str(tmp_path / "project"))
        mock_confirm.assert_not_called()


@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=True)
def test_ensure_role_installs_on_confirm(mock_confirm, mock_which, mock_run, tmp_path, monkeypatch):
    """Installs role via strawhub when user confirms."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global_home"))
    mock_run.return_value = MagicMock(returncode=0)

    _ensure_role_installed("ai-ceo", str(tmp_path / "project"))

    mock_confirm.assert_called_once()
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == ["/usr/bin/strawhub", "install", "role", "ai-ceo", "--global"]


@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=False)
def test_ensure_role_skips_on_decline(mock_confirm, mock_which, mock_run, tmp_path, monkeypatch):
    """Does nothing when user declines install."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global_home"))

    _ensure_role_installed("ai-ceo", str(tmp_path / "project"))

    mock_confirm.assert_called_once()
    mock_run.assert_not_called()


@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.shutil.which", return_value=None)
@patch("strawpot.cli.click.confirm", return_value=True)
def test_ensure_role_strawhub_not_found(mock_confirm, mock_which, mock_echo, tmp_path, monkeypatch):
    """Shows error when strawhub CLI is not on PATH."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global_home"))

    _ensure_role_installed("ai-ceo", str(tmp_path / "project"))

    calls = [str(c) for c in mock_echo.call_args_list]
    assert any("strawhub CLI not found" in c for c in calls)


@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=True)
def test_ensure_role_install_fails(mock_confirm, mock_which, mock_run, mock_echo, tmp_path, monkeypatch):
    """Shows error when install command fails."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global_home"))
    mock_run.return_value = MagicMock(returncode=1)

    _ensure_role_installed("ai-ceo", str(tmp_path / "project"))

    calls = [str(c) for c in mock_echo.call_args_list]
    assert any("Failed to install role" in c for c in calls)


# ---------------------------------------------------------------------------
# auto_setup=True (headless mode)
# ---------------------------------------------------------------------------


@patch("strawpot.cli.get_strawpot_home", return_value=_EMPTY_HOME)
@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm")
@patch("strawpot.cli.resolve_agent", side_effect=FileNotFoundError("not found"))
def test_ensure_agent_auto_setup_skips_confirm(mock_resolve, mock_confirm, mock_which, mock_run, _):
    """auto_setup=True installs without prompting."""
    mock_run.return_value = MagicMock(returncode=0)

    _ensure_agent_installed("strawpot-claude-code", "/tmp/project", auto_setup=True)

    mock_confirm.assert_not_called()
    mock_run.assert_called_once()


@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm")
def test_ensure_skill_auto_setup_skips_confirm(mock_confirm, mock_which, mock_run, tmp_path, monkeypatch):
    """auto_setup=True installs skill without prompting."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global_home"))
    mock_run.return_value = MagicMock(returncode=0)

    _ensure_skill_installed("denden", str(tmp_path / "project"), auto_setup=True)

    mock_confirm.assert_not_called()
    mock_run.assert_called_once()


@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm")
def test_ensure_role_auto_setup_skips_confirm(mock_confirm, mock_which, mock_run, tmp_path, monkeypatch):
    """auto_setup=True installs role without prompting."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global_home"))
    mock_run.return_value = MagicMock(returncode=0)

    _ensure_role_installed("ai-ceo", str(tmp_path / "project"), auto_setup=True)

    mock_confirm.assert_not_called()
    mock_run.assert_called_once()


@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm")
@patch("strawpot.cli.resolve_memory", side_effect=FileNotFoundError("not found"))
def test_ensure_memory_auto_setup_skips_confirm(mock_resolve, mock_confirm, mock_which, mock_run):
    """auto_setup=True installs memory provider without prompting."""
    mock_run.return_value = MagicMock(returncode=0)

    _ensure_memory_installed("semantic", "/tmp/project", auto_setup=True)

    mock_confirm.assert_not_called()
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# needs_onboarding
# ---------------------------------------------------------------------------


def test_needs_onboarding_true_no_config_no_agent(tmp_path, monkeypatch):
    """Returns True when no runtime in config and no agent installed."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text('memory = "dial"\n')
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    config = StrawPotConfig()  # default runtime = "strawpot-claude-code"
    assert needs_onboarding(config, str(tmp_path / "project")) is True


def test_needs_onboarding_false_explicit_runtime(tmp_path, monkeypatch):
    """Returns False when runtime is explicitly set in config."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text('runtime = "strawpot-gemini"\n')
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    config = StrawPotConfig(runtime="strawpot-gemini")
    assert needs_onboarding(config, str(tmp_path / "project")) is False


def test_needs_onboarding_false_agent_installed(tmp_path, monkeypatch):
    """Returns False when agent is installed even without explicit runtime."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "strawpot.toml").write_text('memory = "dial"\n')
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    config = StrawPotConfig()
    with patch("strawpot.cli.resolve_agent") as mock_resolve:
        mock_resolve.return_value = MagicMock()  # agent found
        assert needs_onboarding(config, str(tmp_path / "project")) is False
