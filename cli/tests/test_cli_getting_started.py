"""Tests for getting-started features: first-run banner, quickstart, grouped help."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from strawpot.cli import (
    GroupedGroup,
    _COMMAND_GROUPS,
    _first_run_marker_path,
    cli,
)


# ---------------------------------------------------------------------------
# First-run banner
# ---------------------------------------------------------------------------


def test_first_run_banner_shown_when_no_marker(tmp_path):
    """Banner is printed when the first-run marker file does not exist."""
    with patch("strawpot.cli.get_strawpot_home", return_value=tmp_path):
        marker = tmp_path / ".first_run_done"
        assert not marker.exists()

        runner = CliRunner()
        result = runner.invoke(cli, ["quickstart"])

        assert "Welcome to StrawPot!" in result.output
        assert "strawpot start" in result.output
        assert marker.exists()


def test_first_run_banner_not_shown_when_marker_exists(tmp_path):
    """Banner is suppressed when the marker file already exists."""
    marker = tmp_path / ".first_run_done"
    marker.touch()

    with patch("strawpot.cli.get_strawpot_home", return_value=tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["quickstart"])

        # Quickstart content should appear, but not the welcome banner
        assert "Welcome to StrawPot!" not in result.output
        assert "Quick Start Guide" in result.output


def test_first_run_marker_created_in_strawpot_home(tmp_path):
    """The marker file is created under the strawpot home directory."""
    with patch("strawpot.cli.get_strawpot_home", return_value=tmp_path):
        marker = _first_run_marker_path()
        assert marker == tmp_path / ".first_run_done"


def test_first_run_banner_creates_parent_dirs(tmp_path):
    """Banner creates the ~/.strawpot dir if it doesn't exist yet."""
    nested = tmp_path / "does" / "not" / "exist"
    with patch("strawpot.cli.get_strawpot_home", return_value=nested):
        runner = CliRunner()
        result = runner.invoke(cli, ["quickstart"])

        assert "Welcome to StrawPot!" in result.output
        assert (nested / ".first_run_done").exists()


# ---------------------------------------------------------------------------
# Quickstart command
# ---------------------------------------------------------------------------


def test_quickstart_command_exists():
    """The quickstart command is registered on the CLI group."""
    assert "quickstart" in cli.commands


def test_quickstart_prints_guide(tmp_path):
    """quickstart prints the step-by-step guide."""
    # Pre-create marker so we only see the quickstart output, not the banner
    marker = tmp_path / ".first_run_done"
    marker.touch()

    with patch("strawpot.cli.get_strawpot_home", return_value=tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["quickstart"])

    assert result.exit_code == 0
    assert "Quick Start Guide" in result.output
    assert "strawpot doctor" in result.output
    assert "strawpot start" in result.output
    assert "strawpot gui" in result.output
    assert "docs.strawpot.com" in result.output


# ---------------------------------------------------------------------------
# Grouped --help output
# ---------------------------------------------------------------------------


def test_help_shows_getting_started_group(tmp_path):
    """--help output contains the 'Getting Started' section header."""
    marker = tmp_path / ".first_run_done"
    marker.touch()

    with patch("strawpot.cli.get_strawpot_home", return_value=tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Getting Started" in result.output


def test_help_start_appears_before_install(tmp_path):
    """In --help, 'start' appears before 'install' (Getting Started before Package Management)."""
    marker = tmp_path / ".first_run_done"
    marker.touch()

    with patch("strawpot.cli.get_strawpot_home", return_value=tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

    start_pos = result.output.index("Getting Started")
    install_pos = result.output.index("Package Management")
    assert start_pos < install_pos


def test_help_contains_quickstart(tmp_path):
    """--help lists the quickstart command."""
    marker = tmp_path / ".first_run_done"
    marker.touch()

    with patch("strawpot.cli.get_strawpot_home", return_value=tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

    assert "quickstart" in result.output


def test_grouped_group_is_used():
    """The CLI group uses the GroupedGroup class."""
    assert isinstance(cli, GroupedGroup)


def test_command_groups_cover_core_commands():
    """All core StrawPot commands appear in a command group."""
    all_grouped = set()
    for _, cmds in _COMMAND_GROUPS:
        all_grouped.update(cmds)

    core = {"start", "quickstart", "doctor", "gui", "config", "sessions", "agents", "upgrade"}
    assert core.issubset(all_grouped)
