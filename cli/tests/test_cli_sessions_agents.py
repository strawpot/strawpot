"""Tests for enhanced strawpot sessions and agents CLI commands."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from strawpot.cli import cli, _latest_running_session, _collect_sessions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_dir(tmp_path, run_id, *, pid=99999, alive=True, agents=None):
    """Create a mock session directory with session.json."""
    sessions_dir = tmp_path / ".strawpot" / "sessions" / run_id
    sessions_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "working_dir": str(tmp_path),
        "pid": pid,
        "isolation": "worktree",
        "runtime": "claude-code",
        "denden_addr": "127.0.0.1:50051",
        "started_at": "2026-03-27T00:00:00Z",
        "agents": agents or {},
    }
    with open(sessions_dir / "session.json", "w") as f:
        json.dump(data, f)
    return sessions_dir


def _make_running_symlink(tmp_path, run_id):
    running_dir = tmp_path / ".strawpot" / "running"
    running_dir.mkdir(parents=True, exist_ok=True)
    link = running_dir / run_id
    if not link.exists():
        os.symlink(f"../sessions/{run_id}", str(link))


def _make_archive_symlink(tmp_path, run_id):
    archive_dir = tmp_path / ".strawpot" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    link = archive_dir / run_id
    if not link.exists():
        os.symlink(f"../sessions/{run_id}", str(link))


# ---------------------------------------------------------------------------
# _latest_running_session
# ---------------------------------------------------------------------------


class TestLatestRunningSession:
    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_returns_latest_by_started_at(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_old")
        _make_running_symlink(tmp_path, "run_old")
        # Newer session
        sessions_dir = tmp_path / ".strawpot" / "sessions" / "run_new"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        with open(sessions_dir / "session.json", "w") as f:
            json.dump({
                "run_id": "run_new",
                "working_dir": str(tmp_path),
                "pid": 99998,
                "started_at": "2026-03-28T00:00:00Z",
            }, f)
        _make_running_symlink(tmp_path, "run_new")

        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = _latest_running_session()
        assert result == "run_new"

    @patch("strawpot.cli.is_pid_alive", return_value=False)
    def test_returns_none_when_no_running(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_stale")
        _make_running_symlink(tmp_path, "run_stale")

        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = _latest_running_session()
        assert result is None


# ---------------------------------------------------------------------------
# sessions command
# ---------------------------------------------------------------------------


class TestSessionsCommand:
    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_sessions_default_shows_running(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_abc")
        _make_running_symlink(tmp_path, "run_abc")

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["sessions"])
        assert result.exit_code == 0
        assert "run_abc" in result.output
        assert "running" in result.output

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_sessions_json_output(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_abc")
        _make_running_symlink(tmp_path, "run_abc")

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["sessions", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["run_id"] == "run_abc"

    @patch("strawpot.cli.is_pid_alive", return_value=False)
    def test_sessions_no_running_empty(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_stale")
        _make_running_symlink(tmp_path, "run_stale")

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["sessions"])
        assert result.exit_code == 0
        assert "No sessions found" in result.output

    @patch("strawpot.cli.is_pid_alive", return_value=False)
    def test_sessions_status_stale(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_stale")
        _make_running_symlink(tmp_path, "run_stale")

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["sessions", "--status", "stale"])
        assert result.exit_code == 0
        assert "stale" in result.output

    @patch("strawpot.cli.is_pid_alive", return_value=False)
    def test_sessions_all_includes_archived(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_archived")
        _make_archive_symlink(tmp_path, "run_archived")

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["sessions", "--all"])
        assert result.exit_code == 0
        assert "archived" in result.output


# ---------------------------------------------------------------------------
# agents command
# ---------------------------------------------------------------------------


class TestAgentsCommand:
    def _agents_data(self):
        return {
            "agent-a": {
                "role": "orchestrator", "runtime": "cc", "parent": None,
                "state": "running", "pid": 100,
            },
            "agent-b": {
                "role": "implementer", "runtime": "cc", "parent": "agent-a",
                "state": "completed", "pid": 200,
            },
            "agent-c": {
                "role": "reviewer", "runtime": "cc", "parent": "agent-a",
                "state": "cancelled", "pid": 300, "cancel_reason": "user",
            },
        }

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_agents_with_session_id(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_abc", agents=self._agents_data())

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["agents", "run_abc"])
        assert result.exit_code == 0
        assert "agent-a" in result.output
        assert "orchestrator" in result.output

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_agents_auto_detect_session(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_abc", agents=self._agents_data())
        _make_running_symlink(tmp_path, "run_abc")

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["agents"])
        assert result.exit_code == 0
        assert "agent-a" in result.output

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_agents_status_filter(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_abc", agents=self._agents_data())

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["agents", "run_abc", "--status", "completed", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["agent_id"] == "agent-b"

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_agents_role_filter(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_abc", agents=self._agents_data())

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["agents", "run_abc", "--role", "reviewer", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["agent_id"] == "agent-c"

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_agents_parent_filter(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_abc", agents=self._agents_data())

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["agents", "run_abc", "--parent", "agent-a", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        # Only children of agent-a, not agent-a itself
        agent_ids = {a["agent_id"] for a in data}
        assert "agent-b" in agent_ids
        assert "agent-c" in agent_ids
        assert "agent-a" not in agent_ids

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_agents_json_output(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_abc", agents=self._agents_data())

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["agents", "run_abc", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 3
        agent_ids = {a["agent_id"] for a in data}
        assert agent_ids == {"agent-a", "agent-b", "agent-c"}

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_agents_tree_view(self, mock_alive, tmp_path):
        _make_session_dir(tmp_path, "run_abc", agents=self._agents_data())

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["agents", "run_abc", "--tree"])
        assert result.exit_code == 0
        # Children should be indented
        lines = result.output.strip().split("\n")
        # Find orchestrator (depth 0) and implementer (depth 1)
        orch_line = [l for l in lines if "orchestrator" in l][0]
        impl_line = [l for l in lines if "implementer" in l][0]
        # Implementer should have more leading spaces
        assert len(impl_line) - len(impl_line.lstrip()) > len(orch_line) - len(orch_line.lstrip())

    @patch("strawpot.cli.is_pid_alive", return_value=True)
    def test_agents_backward_compat_positional(self, mock_alive, tmp_path):
        """Old-style `strawpot agents run_abc` still works."""
        _make_session_dir(tmp_path, "run_abc", agents=self._agents_data())

        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            result = runner.invoke(cli, ["agents", "run_abc"])
        assert result.exit_code == 0
        assert "agent-a" in result.output

    def test_agents_no_session_found(self, tmp_path):
        runner = CliRunner()
        with patch("strawpot.cli._sessions_dir", return_value=tmp_path / ".strawpot" / "sessions"):
            with patch("strawpot.cli._latest_running_session", return_value=None):
                result = runner.invoke(cli, ["agents"])
        assert result.exit_code != 0
        assert "No running session" in result.output
