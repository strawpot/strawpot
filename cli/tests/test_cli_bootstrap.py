"""Tests for strawpot.cli bootstrap helpers (_ensure_agent_installed, _ensure_skill_installed)."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from strawpot.cli import (
    _ensure_agent_installed,
    _ensure_memory_installed,
    _ensure_role_installed,
    _ensure_skill_installed,
)


# ---------------------------------------------------------------------------
# _ensure_agent_installed
# ---------------------------------------------------------------------------


@patch("strawpot.cli.resolve_agent")
def test_ensure_agent_already_installed(mock_resolve):
    """No prompt when the agent is already installed."""
    mock_resolve.return_value = MagicMock()  # resolve succeeds

    _ensure_agent_installed("claude_code", "/tmp/project")

    mock_resolve.assert_called_once_with("claude_code", "/tmp/project")


@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=True)
@patch("strawpot.cli.resolve_agent", side_effect=FileNotFoundError("not found"))
def test_ensure_agent_installs_on_confirm(mock_resolve, mock_confirm, mock_which, mock_run):
    """Installs agent via strawhub when user confirms."""
    mock_run.return_value = MagicMock(returncode=0)

    _ensure_agent_installed("claude_code", "/tmp/project")

    mock_confirm.assert_called_once()
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == ["/usr/bin/strawhub", "install", "agent", "claude_code", "--global"]


@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=False)
@patch("strawpot.cli.resolve_agent", side_effect=FileNotFoundError("not found"))
def test_ensure_agent_skips_on_decline(mock_resolve, mock_confirm, mock_which, mock_run):
    """Does nothing when user declines install."""
    _ensure_agent_installed("claude_code", "/tmp/project")

    mock_confirm.assert_called_once()
    mock_run.assert_not_called()


@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.shutil.which", return_value=None)
@patch("strawpot.cli.click.confirm", return_value=True)
@patch("strawpot.cli.resolve_agent", side_effect=FileNotFoundError("not found"))
def test_ensure_agent_strawhub_not_found(mock_resolve, mock_confirm, mock_which, mock_echo):
    """Shows error when strawhub CLI is not on PATH."""
    _ensure_agent_installed("claude_code", "/tmp/project")

    # Should print error about missing strawhub
    calls = [str(c) for c in mock_echo.call_args_list]
    assert any("strawhub CLI not found" in c for c in calls)


@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm", return_value=True)
@patch("strawpot.cli.resolve_agent", side_effect=FileNotFoundError("not found"))
def test_ensure_agent_install_fails(mock_resolve, mock_confirm, mock_which, mock_run, mock_echo):
    """Shows error when install command fails."""
    mock_run.return_value = MagicMock(returncode=1)

    _ensure_agent_installed("claude_code", "/tmp/project")

    calls = [str(c) for c in mock_echo.call_args_list]
    assert any("Failed to install agent" in c for c in calls)


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


@patch("strawpot.cli.subprocess.run")
@patch("strawpot.cli.shutil.which", return_value="/usr/bin/strawhub")
@patch("strawpot.cli.click.confirm")
@patch("strawpot.cli.resolve_agent", side_effect=FileNotFoundError("not found"))
def test_ensure_agent_auto_setup_skips_confirm(mock_resolve, mock_confirm, mock_which, mock_run):
    """auto_setup=True installs without prompting."""
    mock_run.return_value = MagicMock(returncode=0)

    _ensure_agent_installed("claude_code", "/tmp/project", auto_setup=True)

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
