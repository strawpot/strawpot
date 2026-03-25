"""Tests for the ``strawpot run`` command (alias for ``start --task``)."""

from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from strawpot.cli import _COMMAND_GROUPS, cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def _suppress_first_run(tmp_path):
    """Suppress the first-run banner so it doesn't pollute test output."""
    marker_dir = tmp_path / "home"
    marker_dir.mkdir()
    (marker_dir / ".first_run_done").touch()
    with patch("strawpot.cli.get_strawpot_home", return_value=marker_dir):
        yield


@pytest.fixture()
def start_spy():
    """Intercept ``ctx.invoke(start, ...)`` and record the kwargs."""
    invocations: list[dict] = []
    original_invoke = click.Context.invoke

    def spy_invoke(self, callback, **kwargs):
        from strawpot.cli import start as start_cmd

        if callback is start_cmd:
            invocations.append(kwargs)
            return  # don't actually run start
        return original_invoke(self, callback, **kwargs)

    with patch.object(click.Context, "invoke", spy_invoke):
        yield invocations


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


def test_run_command_exists():
    """The ``run`` command is registered on the CLI group."""
    assert "run" in cli.commands


def test_run_option_parity_with_start():
    """``run`` exposes the same options as ``start`` minus --task and --yes."""
    from strawpot.cli import run as run_cmd, start as start_cmd

    start_names = {p.name for p in start_cmd.params}
    run_names = {p.name for p in run_cmd.params}
    # Both have "task" (start as --task option, run as positional argument).
    # start additionally has --yes/yes_flag which run always implies.
    assert start_names - run_names == {"yes_flag"}
    assert run_names - start_names == set()


def test_run_in_getting_started_group():
    """``run`` appears in the Getting Started command group."""
    getting_started = dict(_COMMAND_GROUPS)["Getting Started"]
    assert "run" in getting_started


def test_run_appears_in_help(runner):
    """``strawpot --help`` lists the run command."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output


def test_run_help_shows_task_argument(runner):
    """``strawpot run --help`` shows the positional TASK argument."""
    result = runner.invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    assert "TASK" in result.output


def test_run_help_shows_options(runner):
    """``strawpot run --help`` lists pass-through options."""
    result = runner.invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    for opt in ("--role", "--runtime", "--progress", "--headless"):
        assert opt in result.output


def test_run_help_omits_task_and_yes_options(runner):
    """``strawpot run --help`` does NOT show --task or --yes (they are implicit)."""
    result = runner.invoke(cli, ["run", "--help"])
    option_lines = [l for l in result.output.splitlines() if l.strip().startswith("--")]
    # --memory-task is expected; only a bare --task option should be absent.
    assert not any("--task " in l and "--memory-task" not in l for l in option_lines)
    assert not any("--yes" in l for l in option_lines)


def test_run_without_task_shows_usage_error(runner):
    """``strawpot run`` without a task argument shows a usage error."""
    result = runner.invoke(cli, ["run"])
    assert result.exit_code != 0
    assert "Missing argument" in result.output or "Usage" in result.output


# ---------------------------------------------------------------------------
# Delegation to start
# ---------------------------------------------------------------------------


def test_run_invokes_start_with_task_and_yes(runner, start_spy):
    """``run`` delegates to ``start`` with task= and yes_flag=True."""
    runner.invoke(cli, ["run", "Add dark mode toggle"])

    assert len(start_spy) == 1
    assert start_spy[0]["task"] == "Add dark mode toggle"
    assert start_spy[0]["yes_flag"] is True


def test_run_passes_options_through(runner, start_spy):
    """``run`` passes --role, --runtime, and other options to start."""
    runner.invoke(cli, [
        "run", "--role", "my-ceo", "--runtime", "claude",
        "--progress", "json", "Build a feature",
    ])

    assert len(start_spy) == 1
    assert start_spy[0]["task"] == "Build a feature"
    assert start_spy[0]["role"] == "my-ceo"
    assert start_spy[0]["runtime"] == "claude"
    assert start_spy[0]["progress_mode"] == "json"
    assert start_spy[0]["yes_flag"] is True


# ---------------------------------------------------------------------------
# Quickstart text
# ---------------------------------------------------------------------------


def test_quickstart_mentions_run(runner):
    """The quickstart guide mentions ``strawpot run``."""
    result = runner.invoke(cli, ["quickstart"])
    assert result.exit_code == 0
    assert "strawpot run" in result.output
