"""Tests for getting-started features: first-run banner, quickstart, grouped help."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from strawpot.cli import (
    GroupedGroup,
    _COMMAND_GROUPS,
    _first_run_marker_path,
    cli,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_home(tmp_path):
    """Patch get_strawpot_home to use a fresh temp dir (no marker file)."""
    with patch("strawpot.cli.get_strawpot_home", return_value=tmp_path):
        yield tmp_path


@pytest.fixture()
def fake_home_with_marker(fake_home):
    """Same as fake_home but with the first-run marker already created."""
    (fake_home / ".first_run_done").touch()
    yield fake_home


def _invoke(*args):
    """Shorthand for invoking the CLI via CliRunner."""
    return CliRunner().invoke(cli, list(args))


# ---------------------------------------------------------------------------
# First-run banner
# ---------------------------------------------------------------------------


def test_first_run_banner_shown_when_no_marker(fake_home):
    """Banner is printed when the first-run marker file does not exist."""
    marker = fake_home / ".first_run_done"
    assert not marker.exists()

    result = _invoke("quickstart")

    assert "Welcome to StrawPot!" in result.output
    assert "strawpot start" in result.output
    assert marker.exists()


def test_first_run_banner_not_shown_when_marker_exists(fake_home_with_marker):
    """Banner is suppressed when the marker file already exists."""
    result = _invoke("quickstart")

    assert "Welcome to StrawPot!" not in result.output
    assert "Quick Start Guide" in result.output


def test_first_run_marker_created_in_strawpot_home(fake_home):
    """The marker file is created under the strawpot home directory."""
    marker = _first_run_marker_path()
    assert marker == fake_home / ".first_run_done"


def test_first_run_banner_creates_parent_dirs(tmp_path):
    """Banner creates the ~/.strawpot dir if it doesn't exist yet."""
    nested = tmp_path / "does" / "not" / "exist"
    with patch("strawpot.cli.get_strawpot_home", return_value=nested):
        result = _invoke("quickstart")

    assert "Welcome to StrawPot!" in result.output
    assert (nested / ".first_run_done").exists()


# ---------------------------------------------------------------------------
# Quickstart command
# ---------------------------------------------------------------------------


def test_quickstart_command_exists():
    """The quickstart command is registered on the CLI group."""
    assert "quickstart" in cli.commands


def test_quickstart_prints_guide(fake_home_with_marker):
    """quickstart prints the step-by-step guide."""
    result = _invoke("quickstart")

    assert result.exit_code == 0
    for expected in ("Quick Start Guide", "strawpot doctor", "strawpot start",
                     "strawpot gui", "docs.strawpot.com"):
        assert expected in result.output


# ---------------------------------------------------------------------------
# Grouped --help output
# ---------------------------------------------------------------------------


def test_help_shows_getting_started_group(fake_home_with_marker):
    """--help output contains the 'Getting Started' section header."""
    result = _invoke("--help")

    assert result.exit_code == 0
    assert "Getting Started" in result.output


def test_help_start_appears_before_install(fake_home_with_marker):
    """In --help, 'start' appears before 'install' (Getting Started before Package Management)."""
    result = _invoke("--help")

    start_pos = result.output.index("Getting Started")
    install_pos = result.output.index("Package Management")
    assert start_pos < install_pos


def test_help_contains_quickstart(fake_home_with_marker):
    """--help lists the quickstart command."""
    result = _invoke("--help")
    assert "quickstart" in result.output


def test_grouped_group_is_used():
    """The CLI group uses the GroupedGroup class."""
    assert isinstance(cli, GroupedGroup)


def test_command_groups_cover_core_commands():
    """All core StrawPot commands appear in a command group."""
    all_grouped = {name for _, cmds in _COMMAND_GROUPS for name in cmds}
    core = {"start", "quickstart", "doctor", "gui", "config", "sessions", "agents", "upgrade"}
    assert core.issubset(all_grouped)
