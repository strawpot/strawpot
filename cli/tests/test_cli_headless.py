"""Tests for headless and non-interactive mode behavior."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from strawpot.cli import cli


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.recover_stale_sessions", return_value=[])
@patch("strawpot.cli.load_config")
def test_headless_missing_env_exits(
    mock_config,
    mock_recover,
    mock_agent_install,
    mock_skill_install,
    mock_role_install,
    mock_memory_install,
    mock_resolve,
    mock_validate,
    mock_wrapper,
    mock_isolator,
    mock_session,
):
    """Headless mode exits with error when agent has missing env vars."""
    mock_config.return_value = MagicMock(
        orchestrator_role="orchestrator",
        runtime="strawpot-claude-code",
        isolation="none",
        merge_strategy="auto",
        pull_before_session="never",
        denden_addr="127.0.0.1:9700",
        memory=None,
        agents={},
    )
    mock_resolve.return_value = MagicMock()
    mock_validate.return_value = MagicMock(
        missing_tools=[],
        missing_env=["ANTHROPIC_API_KEY", "OTHER_KEY"],
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--headless", "--task", "test task"])

    assert result.exit_code != 0
    assert "missing environment variables" in result.output
    assert "ANTHROPIC_API_KEY" in result.output


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.recover_stale_sessions", return_value=[])
@patch("strawpot.cli.load_config")
def test_headless_no_missing_env_proceeds(
    mock_config,
    mock_recover,
    mock_agent_install,
    mock_skill_install,
    mock_role_install,
    mock_memory_install,
    mock_resolve,
    mock_validate,
    mock_wrapper,
    mock_isolator,
    mock_session,
):
    """Headless mode proceeds when no env vars are missing."""
    mock_config.return_value = MagicMock(
        orchestrator_role="orchestrator",
        runtime="strawpot-claude-code",
        isolation="none",
        merge_strategy="auto",
        pull_before_session="never",
        denden_addr="127.0.0.1:9700",
        memory=None,
        agents={},
    )
    mock_resolve.return_value = MagicMock()
    mock_validate.return_value = MagicMock(
        missing_tools=[],
        missing_env=[],
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--headless", "--task", "test task"])

    # Should reach session creation (may fail later but not on env vars)
    assert "missing environment variables" not in (result.output or "")


@patch("strawpot.cli.needs_onboarding", return_value=False)
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.recover_stale_sessions", return_value=[])
@patch("strawpot.cli.load_config")
def test_headless_passes_auto_setup_to_bootstrap(
    mock_config,
    mock_recover,
    mock_agent_install,
    _mock_onboarding,
):
    """Headless mode passes auto_setup=True to bootstrap helpers."""
    mock_config.return_value = MagicMock(
        orchestrator_role="orchestrator",
        runtime="strawpot-claude-code",
        isolation="none",
        merge_strategy="auto",
        pull_before_session="never",
        denden_addr="127.0.0.1:9700",
        memory=None,
        agents={},
    )
    # Make it fail after agent install so we don't need to mock everything
    mock_agent_install.side_effect = SystemExit(1)

    runner = CliRunner()
    runner.invoke(cli, ["start", "--headless", "--task", "test task"])

    mock_agent_install.assert_called_once()
    _, kwargs = mock_agent_install.call_args
    assert kwargs.get("auto_setup") is True


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.recover_stale_sessions", return_value=[])
@patch("strawpot.cli.load_config")
def test_headless_unresolvable_tools_exits(
    mock_config,
    mock_recover,
    mock_agent_install,
    mock_skill_install,
    mock_role_install,
    mock_memory_install,
    mock_resolve,
    mock_validate,
    mock_wrapper,
    mock_isolator,
    mock_session,
):
    """Headless mode exits with error when tools cannot be installed."""
    mock_config.return_value = MagicMock(
        orchestrator_role="orchestrator",
        runtime="strawpot-claude-code",
        isolation="none",
        merge_strategy="auto",
        pull_before_session="never",
        denden_addr="127.0.0.1:9700",
        memory=None,
        agents={},
    )
    mock_resolve.return_value = MagicMock()
    mock_validate.return_value = MagicMock(
        missing_tools=[("git", None)],
        missing_env=[],
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--headless", "--task", "test task"])

    assert result.exit_code != 0
    assert "Missing required tools" in result.output
    assert "git" in result.output


# ---------------------------------------------------------------------------
# --yes / -y flag
# ---------------------------------------------------------------------------


@patch("strawpot.cli.needs_onboarding", return_value=False)
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.recover_stale_sessions", return_value=[])
@patch("strawpot.cli.load_config")
def test_yes_flag_passes_auto_setup_to_bootstrap(
    mock_config,
    mock_recover,
    mock_agent_install,
    _mock_onboarding,
):
    """--yes flag passes auto_setup=True to bootstrap helpers."""
    mock_config.return_value = MagicMock(
        orchestrator_role="orchestrator",
        runtime="strawpot-claude-code",
        isolation="none",
        merge_strategy="auto",
        pull_before_session="never",
        denden_addr="127.0.0.1:9700",
        memory=None,
        agents={},
    )
    mock_agent_install.side_effect = SystemExit(1)

    runner = CliRunner()
    runner.invoke(cli, ["start", "--yes", "--task", "test task"])

    mock_agent_install.assert_called_once()
    _, kwargs = mock_agent_install.call_args
    assert kwargs.get("auto_setup") is True


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.recover_stale_sessions", return_value=[])
@patch("strawpot.cli.load_config")
def test_yes_flag_auto_accepts_tool_install(
    mock_config,
    mock_recover,
    mock_agent_install,
    mock_skill_install,
    mock_role_install,
    mock_memory_install,
    mock_resolve,
    mock_validate,
    mock_wrapper,
    mock_isolator,
    mock_session,
):
    """--yes flag auto-accepts tool install prompts without click.confirm."""
    mock_config.return_value = MagicMock(
        orchestrator_role="orchestrator",
        runtime="strawpot-claude-code",
        isolation="none",
        merge_strategy="auto",
        pull_before_session="never",
        denden_addr="127.0.0.1:9700",
        memory=None,
        agents={},
    )
    mock_resolve.return_value = MagicMock()
    mock_validate.return_value = MagicMock(
        missing_tools=[("gh", "apt install gh")],
        missing_env=[],
    )

    with patch("strawpot.cli.subprocess.run") as mock_run, \
         patch("strawpot.cli.click.confirm") as mock_confirm:
        mock_run.return_value = MagicMock(returncode=0)
        runner = CliRunner()
        result = runner.invoke(cli, ["start", "--yes", "--task", "test task"])

        # click.confirm should NOT have been called — auto-accepted
        mock_confirm.assert_not_called()
        assert "Installing gh" in result.output


# ---------------------------------------------------------------------------
# --no-tools flag
# ---------------------------------------------------------------------------


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.recover_stale_sessions", return_value=[])
@patch("strawpot.cli.load_config")
def test_no_tools_skips_tool_install(
    mock_config,
    mock_recover,
    mock_agent_install,
    mock_skill_install,
    mock_role_install,
    mock_memory_install,
    mock_resolve,
    mock_validate,
    mock_wrapper,
    mock_isolator,
    mock_session,
):
    """--no-tools flag skips tool installation and exits with error."""
    mock_config.return_value = MagicMock(
        orchestrator_role="orchestrator",
        runtime="strawpot-claude-code",
        isolation="none",
        merge_strategy="auto",
        pull_before_session="never",
        denden_addr="127.0.0.1:9700",
        memory=None,
        agents={},
    )
    mock_resolve.return_value = MagicMock()
    mock_validate.return_value = MagicMock(
        missing_tools=[("gh", "apt install gh")],
        missing_env=[],
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--no-tools", "--task", "test task"])

    assert result.exit_code != 0
    assert "--no-tools" in result.output
    assert "gh" in result.output


# ---------------------------------------------------------------------------
# Non-interactive TTY detection
# ---------------------------------------------------------------------------


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.recover_stale_sessions", return_value=[])
@patch("strawpot.cli.load_config")
def test_non_tty_skips_tool_install(
    mock_config,
    mock_recover,
    mock_agent_install,
    mock_skill_install,
    mock_role_install,
    mock_memory_install,
    mock_resolve,
    mock_validate,
    mock_wrapper,
    mock_isolator,
    mock_session,
):
    """Non-interactive stdin (no TTY) skips tool prompts and exits with error."""
    mock_config.return_value = MagicMock(
        orchestrator_role="orchestrator",
        runtime="strawpot-claude-code",
        isolation="none",
        merge_strategy="auto",
        pull_before_session="never",
        denden_addr="127.0.0.1:9700",
        memory=None,
        agents={},
    )
    mock_resolve.return_value = MagicMock()
    mock_validate.return_value = MagicMock(
        missing_tools=[("gh", "apt install gh")],
        missing_env=[],
    )

    # Simulate a non-interactive terminal (piped stdin)
    with patch("strawpot.cli.sys") as mock_sys:
        mock_sys.stdin.isatty.return_value = False
        mock_sys.exit = SystemExit
        import sys as _sys
        mock_sys.stdout = _sys.stdout
        mock_sys.stderr = _sys.stderr

        runner = CliRunner()
        result = runner.invoke(cli, ["start", "--task", "test task"])

    assert result.exit_code != 0
    assert "non-interactive" in result.output
    assert "gh" in result.output
