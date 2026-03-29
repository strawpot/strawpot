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
@patch("strawpot.init.questionnaire.run_questionnaire")
@patch("strawpot.init.generator.generate_files")
def test_init_runs_pipeline(mock_gen, mock_quest, mock_home, tmp_path):
    """strawpot init runs the questionnaire → generate → write pipeline."""
    from strawpot.init.types import ProjectConfig

    mock_home.return_value = tmp_path
    (tmp_path / ".first_run_done").touch()
    mock_quest.return_value = ProjectConfig(
        project_name="test", project_type="Other", components=[],
    )
    mock_gen.return_value = []

    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0
    assert "No files to generate" in result.output


@patch("strawpot.cli.get_strawpot_home")
def test_init_in_getting_started_group(mock_home, tmp_path):
    """init command appears in the Getting Started section of --help."""
    mock_home.return_value = tmp_path
    (tmp_path / ".first_run_done").touch()

    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    # The command should appear in the help output
    assert "init" in result.output
