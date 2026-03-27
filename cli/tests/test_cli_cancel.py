"""Tests for strawpot cancel agent and strawpot cancel run CLI commands."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from strawpot.cli import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(tmp_path, run_id, *, pid=99999, agents=None):
    """Create a mock session directory."""
    session_dir = tmp_path / ".strawpot" / "sessions" / run_id
    session_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "working_dir": str(tmp_path),
        "pid": pid,
        "runtime": "cc",
        "agents": agents or {},
    }
    with open(session_dir / "session.json", "w") as f:
        json.dump(data, f)
    return session_dir


def _sample_agents():
    return {
        "orch": {"role": "orchestrator", "parent": None, "state": "running", "pid": 100},
        "impl": {"role": "implementer", "parent": "orch", "state": "running", "pid": 200},
        "rev": {"role": "reviewer", "parent": "orch", "state": "running", "pid": 300},
    }


# ---------------------------------------------------------------------------
# cancel agent
# ---------------------------------------------------------------------------


class TestCancelAgent:
    @patch("strawpot.cli.is_pid_alive", return_value=True)
    @patch("strawpot.cli.os.kill")
    def test_cancel_agent_writes_signal_file(self, mock_kill, mock_alive, tmp_path):
        _make_session(tmp_path, "run_abc", agents=_sample_agents())
        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            with patch("strawpot.cli._wait_for_cancel", return_value=True):
                result = runner.invoke(cli, [
                    "cancel", "agent", "impl", "--run", "run_abc", "--yes"
                ])
        assert result.exit_code == 0
        assert "Cancel signal sent" in result.output
        # Signal file should exist
        signal_file = tmp_path / ".strawpot" / "sessions" / "run_abc" / "cancel" / "impl.json"
        assert signal_file.is_file()
        data = json.loads(signal_file.read_text())
        assert data["agent_id"] == "impl"
        assert data["force"] is False

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    @patch("strawpot.cli.os.kill")
    def test_cancel_agent_force_flag(self, mock_kill, mock_alive, tmp_path):
        _make_session(tmp_path, "run_abc", agents=_sample_agents())
        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            with patch("strawpot.cli._wait_for_cancel", return_value=True):
                result = runner.invoke(cli, [
                    "cancel", "agent", "impl", "--run", "run_abc", "--force", "--yes"
                ])
        assert result.exit_code == 0
        signal_file = tmp_path / ".strawpot" / "sessions" / "run_abc" / "cancel" / "impl.json"
        data = json.loads(signal_file.read_text())
        assert data["force"] is True

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_cancel_agent_not_found(self, mock_alive, tmp_path):
        _make_session(tmp_path, "run_abc", agents=_sample_agents())
        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, [
                "cancel", "agent", "nonexistent", "--run", "run_abc", "--yes"
            ])
        assert result.exit_code != 0
        assert "Agent not found" in result.output

    @patch("strawpot.cli.is_pid_alive", return_value=False)
    def test_cancel_agent_stale_session(self, mock_alive, tmp_path):
        _make_session(tmp_path, "run_abc", agents=_sample_agents())
        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, [
                "cancel", "agent", "impl", "--run", "run_abc", "--yes"
            ])
        assert result.exit_code != 0
        assert "not running" in result.output

    def test_cancel_agent_session_not_found(self, tmp_path):
        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, [
                "cancel", "agent", "impl", "--run", "run_nonexistent", "--yes"
            ])
        assert result.exit_code != 0
        assert "Session not found" in result.output

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_cancel_agent_confirmation_declined(self, mock_alive, tmp_path):
        _make_session(tmp_path, "run_abc", agents=_sample_agents())
        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, [
                "cancel", "agent", "impl", "--run", "run_abc"
            ], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled." in result.output

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_cancel_agent_run_required(self, mock_alive, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["cancel", "agent", "impl"])
        assert result.exit_code != 0
        assert "--run" in result.output


# ---------------------------------------------------------------------------
# cancel run
# ---------------------------------------------------------------------------


class TestCancelRun:
    @patch("strawpot.cli.is_pid_alive", return_value=True)
    @patch("strawpot.cli.os.kill")
    def test_cancel_run_writes_signal(self, mock_kill, mock_alive, tmp_path):
        _make_session(tmp_path, "run_abc", agents=_sample_agents())
        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            with patch("strawpot.cli._wait_for_cancel", return_value=True):
                result = runner.invoke(cli, ["cancel", "run", "run_abc", "--yes"])
        assert result.exit_code == 0
        signal_file = tmp_path / ".strawpot" / "sessions" / "run_abc" / "cancel" / "_run.json"
        assert signal_file.is_file()
        data = json.loads(signal_file.read_text())
        assert data["agent_id"] is None

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    @patch("strawpot.cli.os.kill")
    def test_cancel_run_timeout(self, mock_kill, mock_alive, tmp_path):
        _make_session(tmp_path, "run_abc", agents=_sample_agents())
        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            with patch("strawpot.cli._wait_for_cancel", return_value=False):
                result = runner.invoke(cli, ["cancel", "run", "run_abc", "--yes"])
        assert result.exit_code != 0
        assert "timed out" in result.output

    @patch("strawpot.cli.is_pid_alive", return_value=False)
    def test_cancel_run_stale_session(self, mock_alive, tmp_path):
        _make_session(tmp_path, "run_abc", agents=_sample_agents())
        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["cancel", "run", "run_abc", "--yes"])
        assert result.exit_code != 0
        assert "not running" in result.output


# ---------------------------------------------------------------------------
# Help output
# ---------------------------------------------------------------------------


class TestCancelHelp:
    def test_cancel_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["cancel", "--help"])
        assert result.exit_code == 0
        assert "agent" in result.output
        assert "run" in result.output

    def test_cancel_agent_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["cancel", "agent", "--help"])
        assert result.exit_code == 0
        assert "--run" in result.output
        assert "--force" in result.output
        assert "--yes" in result.output
