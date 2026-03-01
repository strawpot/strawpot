"""Tests for strawpot.cli — start command wiring."""

import os
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from strawpot.agents.registry import AgentSpec, ValidationResult
from strawpot.cli import cli


def _make_spec(**overrides):
    defaults = {
        "name": "claude_code",
        "version": "1.0.0",
        "wrapper_cmd": ["/usr/bin/test-wrapper"],
        "config": {},
        "env_schema": {},
        "tools": {},
    }
    defaults.update(overrides)
    return AgentSpec(**defaults)


# ---------------------------------------------------------------------------
# Agent resolution
# ---------------------------------------------------------------------------


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_resolves_agent(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator, mock_session
):
    """start() calls resolve_agent with config.runtime."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    result = runner.invoke(cli, ["start"])

    mock_resolve.assert_called_once()
    call_args = mock_resolve.call_args
    assert call_args[0][0] == "claude_code"  # runtime name
    assert call_args[0][2] is None  # no agent-specific config


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_resolves_agent_with_runtime_override(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator, mock_session
):
    """start --runtime overrides the agent name passed to resolve_agent."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    runner.invoke(cli, ["start", "--runtime", "custom_agent"])

    # resolve_agent should be called with the overridden runtime name
    call_args = mock_resolve.call_args
    assert call_args[0][0] == "custom_agent"


@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_agent_not_found(mock_load, mock_resolve):
    """FileNotFoundError from resolve_agent prints error and exits 1."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.side_effect = FileNotFoundError("Agent not found: 'bad_agent'")

    runner = CliRunner()
    result = runner.invoke(cli, ["start"])

    assert result.exit_code != 0
    assert "Agent not found" in result.output


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.load_config")
def test_start_missing_tools_exits(mock_load, mock_validate, mock_resolve):
    """Missing tools prints error with hints and exits 1."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()
    mock_validate.return_value = ValidationResult(
        missing_tools=[("node", "brew install node"), ("git", None)]
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["start"])

    assert result.exit_code != 0
    assert "Missing required tools" in result.output
    assert "node" in result.output
    assert "brew install node" in result.output
    assert "git" in result.output


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.load_config")
def test_start_missing_env_prompts(
    mock_load, mock_validate, mock_resolve, mock_wrapper, mock_isolator, mock_session
):
    """Missing env vars are prompted and set in os.environ."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()
    mock_validate.return_value = ValidationResult(missing_env=["ANTHROPIC_API_KEY"])

    runner = CliRunner()
    result = runner.invoke(cli, ["start"], input="sk-test-key-123\n")

    assert result.exit_code == 0
    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-test-key-123"

    # Clean up
    os.environ.pop("ANTHROPIC_API_KEY", None)


# ---------------------------------------------------------------------------
# Runtime selection
# ---------------------------------------------------------------------------


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
@patch("strawpot.cli.shutil.which")
def test_start_uses_tmux_when_available(
    mock_which, mock_load, mock_resolve, mock_validate,
    mock_wrapper, mock_isolator, mock_session
):
    """InteractiveWrapperRuntime is used when tmux is on PATH."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()
    # shutil.which("tmux") returns a path
    mock_which.return_value = "/usr/bin/tmux"

    with patch("strawpot.cli.InteractiveWrapperRuntime") as mock_interactive:
        runner = CliRunner()
        runner.invoke(cli, ["start"])

        mock_interactive.assert_called_once()


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
@patch("strawpot.cli.shutil.which")
def test_start_falls_back_to_direct(
    mock_which, mock_load, mock_resolve, mock_validate,
    mock_wrapper, mock_isolator, mock_session
):
    """DirectWrapperRuntime is used when tmux is not on PATH."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()
    mock_which.return_value = None

    with patch("strawpot.cli.DirectWrapperRuntime") as mock_direct:
        runner = CliRunner()
        runner.invoke(cli, ["start"])

        mock_direct.assert_called_once()


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_creates_session(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator, mock_session
):
    """Session is constructed with correct args and start() is called."""
    from strawpot.config import StrawPotConfig

    config = StrawPotConfig()
    mock_load.return_value = config
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    result = runner.invoke(cli, ["start"])

    assert result.exit_code == 0
    mock_session.assert_called_once()
    call_kwargs = mock_session.call_args.kwargs
    assert call_kwargs["config"] is config
    assert "resolve_role" in call_kwargs
    assert "resolve_role_dirs" in call_kwargs

    # session.start() was called
    mock_session.return_value.start.assert_called_once()


# ---------------------------------------------------------------------------
# CLI overrides
# ---------------------------------------------------------------------------


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_role_override(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator, mock_session
):
    """--role overrides config.orchestrator_role."""
    from strawpot.config import StrawPotConfig

    config = StrawPotConfig()
    mock_load.return_value = config
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    runner.invoke(cli, ["start", "--role", "custom-orchestrator"])

    assert config.orchestrator_role == "custom-orchestrator"


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_isolation_override(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator, mock_session
):
    """--isolation overrides config.isolation."""
    from strawpot.config import StrawPotConfig

    config = StrawPotConfig()
    mock_load.return_value = config
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    runner.invoke(cli, ["start", "--isolation", "worktree"])

    assert config.isolation == "worktree"


@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_host_port_override(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator, mock_session
):
    """--host and --port override config.denden_addr."""
    from strawpot.config import StrawPotConfig

    config = StrawPotConfig()
    mock_load.return_value = config
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    runner.invoke(cli, ["start", "--host", "0.0.0.0", "--port", "8080"])

    assert config.denden_addr == "0.0.0.0:8080"
