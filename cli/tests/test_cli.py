"""Tests for strawpot.cli — start command wiring."""

import os
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from strawpot.agents.registry import AgentSpec, ValidationResult
from strawpot.cli import cli


def _make_spec(**overrides):
    defaults = {
        "name": "strawpot-claude-code",
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


@patch("strawpot.cli.needs_onboarding", return_value=False)
@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_resolves_agent(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator,
    mock_session, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory,
    _mock_onboarding,
):
    """start() calls resolve_agent with config.runtime."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    result = runner.invoke(cli, ["start"])

    mock_resolve.assert_called_once()
    call_args = mock_resolve.call_args
    assert call_args[0][0] == "strawpot-claude-code"  # runtime name
    assert call_args[0][2] is None  # no agent-specific config


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_resolves_agent_with_runtime_override(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator,
    mock_session, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
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


@patch("strawpot.cli.needs_onboarding", return_value=False)
@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_agent_not_found(mock_load, mock_resolve, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory, _mock_onboarding):
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


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.load_config")
def test_start_missing_tools_exits(
    mock_load, mock_validate, mock_resolve, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
):
    """Missing tools prints error with hints and exits 1."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()
    mock_validate.return_value = ValidationResult(
        missing_tools=[("node", "brew install node"), ("git", None)]
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["start"], input="n\n")

    assert result.exit_code != 0
    assert "Missing required tools" in result.output
    assert "node" in result.output
    assert "brew install node" in result.output
    assert "git" in result.output


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.load_config")
def test_start_missing_env_prompts(
    mock_load, mock_validate, mock_resolve, mock_wrapper, mock_isolator,
    mock_session, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
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
    assert "console.anthropic.com" in result.output
    assert "Enter your ANTHROPIC_API_KEY" in result.output

    # Clean up
    os.environ.pop("ANTHROPIC_API_KEY", None)


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.load_config")
@patch("strawpot.config.save_resource_config")
def test_start_missing_env_persists_to_config(
    mock_save, mock_load, mock_validate, mock_resolve, mock_wrapper, mock_isolator,
    mock_session, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
):
    """Prompted agent env vars are persisted to global config."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()
    mock_validate.return_value = ValidationResult(missing_env=["ANTHROPIC_API_KEY"])

    runner = CliRunner()
    result = runner.invoke(cli, ["start"], input="sk-test-key-123\n")

    assert result.exit_code == 0
    mock_save.assert_called_once_with(
        None, "agents", "strawpot-claude-code",
        env_values={"ANTHROPIC_API_KEY": "sk-test-key-123"},
    )
    assert "Saved env vars" in result.output

    # Clean up
    os.environ.pop("ANTHROPIC_API_KEY", None)


# ---------------------------------------------------------------------------
# Runtime selection
# ---------------------------------------------------------------------------


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
@patch("strawpot.cli.shutil.which")
def test_start_uses_tmux_when_available(
    mock_which, mock_load, mock_resolve, mock_validate,
    mock_wrapper, mock_isolator, mock_session, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
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


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
@patch("strawpot.cli.shutil.which")
def test_start_falls_back_to_direct(
    mock_which, mock_load, mock_resolve, mock_validate,
    mock_wrapper, mock_isolator, mock_session, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
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


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_creates_session(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator,
    mock_session, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
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


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_role_override(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator,
    mock_session, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
):
    """--role overrides config.orchestrator_role."""
    from strawpot.config import StrawPotConfig

    config = StrawPotConfig()
    mock_load.return_value = config
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    runner.invoke(cli, ["start", "--role", "custom-orchestrator"])

    assert config.orchestrator_role == "custom-orchestrator"


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_isolation_override(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator,
    mock_session, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
):
    """--isolation overrides config.isolation."""
    from strawpot.config import StrawPotConfig

    config = StrawPotConfig()
    mock_load.return_value = config
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    runner.invoke(cli, ["start", "--isolation", "worktree"])

    assert config.isolation == "worktree"


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_host_port_override(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator,
    mock_session, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
):
    """--host and --port override config.denden_addr."""
    from strawpot.config import StrawPotConfig

    config = StrawPotConfig()
    mock_load.return_value = config
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    runner.invoke(cli, ["start", "--host", "0.0.0.0", "--port", "8080"])

    assert config.denden_addr == "0.0.0.0:8080"


# ---------------------------------------------------------------------------
# Run ID
# ---------------------------------------------------------------------------


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.Session")
@patch("strawpot.cli.resolve_isolator")
@patch("strawpot.cli.WrapperRuntime")
@patch("strawpot.cli.validate_agent", return_value=ValidationResult())
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_run_id_override(
    mock_load, mock_resolve, mock_validate, mock_wrapper, mock_isolator,
    mock_session, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
):
    """--run-id passes the pre-assigned run ID to Session constructor."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    runner.invoke(cli, [
        "start", "--headless", "--task", "do stuff", "--run-id", "run_gui123"
    ])

    call_kwargs = mock_session.call_args.kwargs
    assert call_kwargs["run_id"] == "run_gui123"


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.load_config")
def test_start_invalid_run_id_rejected(
    mock_load, mock_resolve, mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
):
    """--run-id without 'run_' prefix fails with error."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()

    runner = CliRunner()
    result = runner.invoke(cli, [
        "start", "--headless", "--task", "do stuff", "--run-id", "bad_id"
    ])

    assert result.exit_code != 0
    assert "run_" in result.output


# ---------------------------------------------------------------------------
# Headless fail-fast
# ---------------------------------------------------------------------------


@patch("strawpot.cli.needs_onboarding", return_value=True)
@patch("strawpot.cli.load_config")
def test_start_headless_fails_when_not_configured(mock_load, _mock_onboarding):
    """--headless exits 1 with clear error when onboarding is needed."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--headless", "--task", "do stuff"])

    assert result.exit_code != 0
    assert "StrawPot is not configured" in result.output


@patch("strawpot.cli._ensure_memory_installed")
@patch("strawpot.cli._ensure_role_installed")
@patch("strawpot.cli._ensure_skill_installed")
@patch("strawpot.cli._ensure_agent_installed")
@patch("strawpot.cli.resolve_agent")
@patch("strawpot.cli.validate_agent")
@patch("strawpot.cli.load_config")
def test_start_headless_missing_env_shows_guidance(
    mock_load, mock_validate, mock_resolve,
    mock_ensure_agent, mock_ensure_skill, mock_ensure_role, mock_ensure_memory
):
    """--headless exits 1 with actionable guidance when API key is missing."""
    from strawpot.config import StrawPotConfig

    mock_load.return_value = StrawPotConfig()
    mock_resolve.return_value = _make_spec()
    mock_validate.return_value = ValidationResult(missing_env=["ANTHROPIC_API_KEY"])

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--headless", "--task", "do stuff"])

    assert result.exit_code != 0
    assert "StrawPot needs an LLM API key" in result.output
    assert "ANTHROPIC_API_KEY" in result.output
    assert "console.anthropic.com" in result.output
    assert "docs.strawpot.com/quickstart" in result.output
