"""Tests for the strawpot init CLI command scaffold."""

from unittest.mock import patch

from click.testing import CliRunner

from strawpot.cli import cli


@patch("strawpot.cli.get_strawpot_home")
def test_init_help(mock_home, tmp_path):
    """strawpot init --help shows help text with all expected flags."""
    mock_home.return_value = tmp_path
    (tmp_path / ".first_run_done").touch()

    result = CliRunner().invoke(cli, ["init", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output
    assert "--check" in result.output
    assert "--verbose" in result.output
    assert "--non-interactive" in result.output


@patch("strawpot.cli.get_strawpot_home")
def test_init_placeholder(mock_home, tmp_path):
    """strawpot init prints a placeholder message and exits cleanly."""
    mock_home.return_value = tmp_path
    (tmp_path / ".first_run_done").touch()

    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


@patch("strawpot.cli.get_strawpot_home")
def test_init_in_getting_started_group(mock_home, tmp_path):
    """init command appears in the Getting Started section of --help."""
    mock_home.return_value = tmp_path
    (tmp_path / ".first_run_done").touch()

    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    # The command should appear in the help output
    assert "init" in result.output
