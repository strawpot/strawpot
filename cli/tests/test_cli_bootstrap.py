"""Tests for strawpot.cli bootstrap helpers (_ensure_agent_installed, _ensure_skill_installed)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from strawpot.cli import (
    _CURL_PIPE_SH_RE,
    _SEEDED_AGENTS,
    _authenticate_agent,
    _download_script,
    _ensure_agent_installed,
    _ensure_memory_installed,
    _ensure_role_installed,
    _ensure_skill_installed,
    _onboarding_wizard,
    _pick_agent,
    _run_install_for_agent,
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


def test_ensure_agent_downloads_and_runs_curl_install_via_urllib(tmp_path):
    """curl-pipe-sh install commands are downloaded via urllib and piped to sh."""
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
    fake_script = b"#!/bin/sh\necho installed\n"
    # resolve_agent raises ValueError because binary doesn't exist
    with patch("strawpot.cli.resolve_agent", side_effect=ValueError("binary not found")), \
         patch("strawpot.cli._download_script", return_value=fake_script) as mock_dl, \
         patch("strawpot.cli.subprocess.run") as mock_run, \
         patch("strawpot.cli.click.echo"):
        mock_run.return_value = MagicMock(returncode=0)
        _ensure_agent_installed("test-agent", str(tmp_path))

        # Should have downloaded from the URL in the install command
        mock_dl.assert_called_once_with("https://example.com/install.sh")
        # Should pipe script to sh (not call curl)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["sh"]
        assert mock_run.call_args[1]["input"] == fake_script


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
# _CURL_PIPE_SH_RE pattern matching
# ---------------------------------------------------------------------------


def test_curl_regex_matches_standard_curl_pipe_sh():
    """Matches standard curl -fsSL <url> | sh."""
    m = _CURL_PIPE_SH_RE.match("curl -fsSL https://example.com/install.sh | sh")
    assert m is not None
    assert m.group(1) == "https://example.com/install.sh"


def test_curl_regex_matches_various_flags():
    """Matches curl with different flags."""
    m = _CURL_PIPE_SH_RE.match("curl -sL https://example.com/install.sh | sh")
    assert m is not None
    assert m.group(1) == "https://example.com/install.sh"


def test_curl_regex_no_match_for_non_curl():
    """Does not match non-curl commands."""
    m = _CURL_PIPE_SH_RE.match("wget -q https://example.com/install.sh | sh")
    assert m is None


def test_curl_regex_no_match_without_pipe_sh():
    """Does not match curl without piping to sh."""
    m = _CURL_PIPE_SH_RE.match("curl -fsSL https://example.com/install.sh > script.sh")
    assert m is None


# ---------------------------------------------------------------------------
# _download_script
# ---------------------------------------------------------------------------


def test_download_script_success():
    """Downloads script content via urllib."""
    import urllib.request
    fake_content = b"#!/bin/sh\necho hello\n"
    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_content
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch.object(urllib.request, "urlopen", return_value=mock_resp):
        result = _download_script("https://example.com/install.sh")
        assert result == fake_content


def test_download_script_failure_raises():
    """Raises RuntimeError on download failure."""
    import urllib.error
    import urllib.request
    with patch.object(urllib.request, "urlopen", side_effect=urllib.error.URLError("timeout")):
        with pytest.raises(RuntimeError, match="Failed to download"):
            _download_script("https://example.com/install.sh")


# ---------------------------------------------------------------------------
# _run_install_for_agent — non-curl install commands
# ---------------------------------------------------------------------------


def test_run_install_non_curl_cmd_uses_sh_c(tmp_path):
    """Non-curl install commands are run via sh -c as before."""
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text(
        "---\n"
        "name: test-agent\n"
        "metadata:\n"
        "  strawpot:\n"
        "    install:\n"
        "      macos: npm install -g my-agent\n"
        "      linux: npm install -g my-agent\n"
        "---\n"
    )
    with patch("strawpot.cli.subprocess.run") as mock_run, \
         patch("strawpot.cli.click.echo"):
        mock_run.return_value = MagicMock(returncode=0)
        result = _run_install_for_agent(agent_dir, "test-agent")

    assert result is True
    cmd = mock_run.call_args[0][0]
    assert cmd[0:2] == ["sh", "-c"]


def test_run_install_download_failure_returns_false(tmp_path):
    """Returns False when script download fails."""
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text(
        "---\n"
        "name: test-agent\n"
        "metadata:\n"
        "  strawpot:\n"
        "    install:\n"
        "      macos: curl -fsSL https://example.com/install.sh | sh\n"
        "      linux: curl -fsSL https://example.com/install.sh | sh\n"
        "---\n"
    )
    with patch("strawpot.cli._download_script", side_effect=RuntimeError("network error")), \
         patch("strawpot.cli.click.echo"):
        result = _run_install_for_agent(agent_dir, "test-agent")

    assert result is False


def test_run_install_no_install_method_returns_false(tmp_path):
    """Returns False when no install command or install.sh exists."""
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text(
        "---\n"
        "name: test-agent\n"
        "metadata:\n"
        "  strawpot:\n"
        "    bin:\n"
        "      macos: my_binary\n"
        "---\n"
    )
    with patch("strawpot.cli.click.echo"):
        result = _run_install_for_agent(agent_dir, "test-agent")

    assert result is False


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


# ---------------------------------------------------------------------------
# _pick_agent
# ---------------------------------------------------------------------------


@patch("strawpot.cli.click.prompt", return_value="1")
def test_pick_agent_selects_first(mock_prompt):
    """Selecting 1 returns the first seeded agent."""
    result = _pick_agent()
    assert result == _SEEDED_AGENTS[0][0]


@patch("strawpot.cli.click.prompt", return_value="3")
def test_pick_agent_selects_third(mock_prompt):
    """Selecting 3 returns the third seeded agent."""
    result = _pick_agent()
    assert result == _SEEDED_AGENTS[2][0]


@patch("strawpot.cli.click.prompt", return_value="5")
def test_pick_agent_selects_fifth(mock_prompt):
    """Selecting 5 is out of range (only 3 agents), returns None."""
    assert _pick_agent() is None


@patch("strawpot.cli.click.prompt", return_value="0")
def test_pick_agent_invalid_zero(mock_prompt):
    """Out-of-range selection returns None."""
    assert _pick_agent() is None


@patch("strawpot.cli.click.prompt", return_value="abc")
def test_pick_agent_invalid_text(mock_prompt):
    """Non-numeric input returns None."""
    assert _pick_agent() is None


# ---------------------------------------------------------------------------
# _onboarding_wizard
# ---------------------------------------------------------------------------


def test_onboarding_wizard_saves_runtime(tmp_path, monkeypatch):
    """Wizard saves runtime to global strawpot.toml and returns agent name."""
    import tomllib

    global_dir = tmp_path / "global"
    global_dir.mkdir()
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    with patch("strawpot.cli._pick_agent", return_value="strawpot-gemini"), \
         patch("strawpot.cli._ensure_agent_installed"), \
         patch("strawpot.cli._authenticate_agent"), \
         patch("strawpot.cli.click.echo"):
        result = _onboarding_wizard(str(tmp_path / "project"))

    assert result == "strawpot-gemini"
    with open(global_dir / "strawpot.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["runtime"] == "strawpot-gemini"


def test_onboarding_wizard_returns_none_on_cancel(tmp_path, monkeypatch):
    """Wizard returns None when user cancels agent selection."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    with patch("strawpot.cli._pick_agent", return_value=None), \
         patch("strawpot.cli.click.echo"):
        result = _onboarding_wizard(str(tmp_path / "project"))

    assert result is None


def test_onboarding_wizard_calls_ensure_agent_installed(tmp_path, monkeypatch):
    """Wizard calls _ensure_agent_installed with auto_setup=True."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    with patch("strawpot.cli._pick_agent", return_value="strawpot-codex"), \
         patch("strawpot.cli._ensure_agent_installed") as mock_install, \
         patch("strawpot.cli._authenticate_agent"), \
         patch("strawpot.cli.click.echo"):
        _onboarding_wizard(str(tmp_path / "project"))

    mock_install.assert_called_once_with(
        "strawpot-codex", str(tmp_path / "project"), auto_setup=True,
    )


def test_onboarding_wizard_calls_authenticate(tmp_path, monkeypatch):
    """Wizard calls _authenticate_agent after installing the agent."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))

    with patch("strawpot.cli._pick_agent", return_value="strawpot-pi"), \
         patch("strawpot.cli._ensure_agent_installed"), \
         patch("strawpot.cli._authenticate_agent") as mock_auth, \
         patch("strawpot.cli.click.echo"):
        _onboarding_wizard(str(tmp_path / "project"))

    mock_auth.assert_called_once_with("strawpot-pi", str(tmp_path / "project"))


# ---------------------------------------------------------------------------
# _authenticate_agent
# ---------------------------------------------------------------------------


def _make_spec(**overrides):
    """Build a minimal AgentSpec for auth tests."""
    from strawpot.agents.registry import AgentSpec

    defaults = dict(
        name="test-agent",
        version="1.0.0",
        wrapper_cmd=["/usr/bin/test-wrapper"],
        env_schema={"TEST_API_KEY": {"required": False, "description": "Test key"}},
    )
    defaults.update(overrides)
    return AgentSpec(**defaults)


@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.click.prompt", return_value="1")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.resolve_agent")
def test_authenticate_agent_login_session(mock_resolve, mock_runtime_cls, mock_prompt, mock_echo):
    """Choice 1 runs WrapperRuntime.setup() for login session."""
    spec = _make_spec()
    mock_resolve.return_value = spec
    mock_runtime = MagicMock()
    mock_runtime.setup.return_value = True
    mock_runtime_cls.return_value = mock_runtime

    _authenticate_agent("test-agent", "/tmp/project")

    mock_runtime_cls.assert_called_once_with(spec)
    mock_runtime.setup.assert_called_once()


@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.click.prompt")
@patch("strawpot.cli.resolve_agent")
def test_authenticate_agent_api_key(mock_resolve, mock_prompt, mock_echo):
    """Choice 2 prompts for API key and saves via save_resource_config."""
    spec = _make_spec()
    mock_resolve.return_value = spec
    # First prompt: choice "2", second prompt: the API key value
    mock_prompt.side_effect = ["2", "sk-test-key-123"]

    with patch("strawpot.config.save_resource_config") as mock_save:
        _authenticate_agent("test-agent", "/tmp/project")

    mock_save.assert_called_once_with(
        None, "agents", "test-agent", env_values={"TEST_API_KEY": "sk-test-key-123"},
    )


@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.click.prompt", return_value="3")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.resolve_agent")
def test_authenticate_agent_skip(mock_resolve, mock_runtime_cls, mock_prompt, mock_echo):
    """Choice 3 skips authentication entirely."""
    spec = _make_spec()
    mock_resolve.return_value = spec

    with patch("strawpot.config.save_resource_config") as mock_save:
        _authenticate_agent("test-agent", "/tmp/project")

    mock_runtime_cls.assert_not_called()
    mock_save.assert_not_called()


@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.click.prompt", return_value="1")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.resolve_agent")
def test_authenticate_agent_login_failure(mock_resolve, mock_runtime_cls, mock_prompt, mock_echo):
    """Failed login prints error but does not raise."""
    spec = _make_spec()
    mock_resolve.return_value = spec
    mock_runtime = MagicMock()
    mock_runtime.setup.return_value = False
    mock_runtime_cls.return_value = mock_runtime

    _authenticate_agent("test-agent", "/tmp/project")

    calls = [str(c) for c in mock_echo.call_args_list]
    assert any("Login failed" in c for c in calls)


@patch("strawpot.cli.click.echo")
@patch("strawpot.cli.click.prompt", return_value="2")
@patch("strawpot.cli.resolve_agent")
def test_authenticate_agent_no_env_skip_maps_to_choice_2(mock_resolve, mock_prompt, mock_echo):
    """When agent has no env vars, choice 2 is 'skip' (not API key)."""
    spec = _make_spec(env_schema={})
    mock_resolve.return_value = spec

    with patch("strawpot.config.save_resource_config") as mock_save:
        _authenticate_agent("test-agent", "/tmp/project")

    # Should skip — no API key prompt, no save
    mock_save.assert_not_called()
    calls = [str(c) for c in mock_echo.call_args_list]
    assert any("Skipping" in c for c in calls)
