"""Tests for strawpot mcp setup auto-configuration."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from strawpot.mcp.setup import (
    _SERVER_NAME,
    _build_server_entry,
    _read_config,
    _write_config,
    configure_mcp,
)


# -- _read_config / _write_config -------------------------------------------


class TestConfigIO:
    def test_read_missing_file(self, tmp_path):
        result = _read_config(tmp_path / "nonexistent.json")
        assert result == {}

    def test_read_valid_config(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"mcpServers": {"other": {}}}')
        result = _read_config(path)
        assert "mcpServers" in result

    def test_read_corrupt_config_backs_up(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("not valid json {{{")
        result = _read_config(path)
        assert result == {}
        assert (tmp_path / "config.json.bak").exists()

    def test_write_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "config.json"
        _write_config(path, {"key": "value"})
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["key"] == "value"

    def test_write_pretty_format(self, tmp_path):
        path = tmp_path / "config.json"
        _write_config(path, {"a": 1})
        content = path.read_text()
        assert "  " in content  # indented


# -- _build_server_entry -----------------------------------------------------


class TestBuildServerEntry:
    @patch("strawpot.mcp.setup.shutil.which", return_value="/usr/bin/strawpot")
    def test_uses_strawpot_command(self, mock_which):
        entry = _build_server_entry()
        assert entry["command"] == "strawpot"
        assert entry["args"] == ["mcp", "serve"]

    @patch("strawpot.mcp.setup.shutil.which", return_value=None)
    def test_falls_back_to_python_module(self, mock_which):
        entry = _build_server_entry()
        assert "python" in entry["command"].lower() or entry["command"].endswith("python3") or entry["command"].endswith("python")
        assert entry["args"] == ["-m", "strawpot.mcp.server"]


# -- configure_mcp -----------------------------------------------------------


class TestConfigureMcp:
    @patch("strawpot.mcp.setup._global_config_candidates")
    @patch("strawpot.mcp.setup.shutil.which", return_value="/usr/bin/strawpot")
    def test_creates_new_config(self, mock_which, mock_candidates, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        mock_candidates.return_value = [config_path]

        configure_mcp(project=False)

        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert _SERVER_NAME in data["mcpServers"]
        assert data["mcpServers"][_SERVER_NAME]["command"] == "strawpot"

    @patch("strawpot.mcp.setup._global_config_candidates")
    @patch("strawpot.mcp.setup.shutil.which", return_value="/usr/bin/strawpot")
    def test_preserves_existing_entries(self, mock_which, mock_candidates, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.write_text(json.dumps({
            "mcpServers": {"other-server": {"command": "other"}}
        }))
        mock_candidates.return_value = [config_path]

        configure_mcp(project=False)

        data = json.loads(config_path.read_text())
        assert "other-server" in data["mcpServers"]
        assert _SERVER_NAME in data["mcpServers"]

    @patch("strawpot.mcp.setup._global_config_candidates")
    @patch("strawpot.mcp.setup.shutil.which", return_value="/usr/bin/strawpot")
    def test_updates_existing_entry(self, mock_which, mock_candidates, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.write_text(json.dumps({
            "mcpServers": {_SERVER_NAME: {"command": "old"}}
        }))
        mock_candidates.return_value = [config_path]

        configure_mcp(project=False)

        data = json.loads(config_path.read_text())
        assert data["mcpServers"][_SERVER_NAME]["command"] == "strawpot"

    @patch("strawpot.mcp.setup._project_config_path")
    @patch("strawpot.mcp.setup.shutil.which", return_value="/usr/bin/strawpot")
    def test_project_flag(self, mock_which, mock_project_path, tmp_path):
        config_path = tmp_path / ".claude" / "mcp.json"
        mock_project_path.return_value = config_path

        configure_mcp(project=True)

        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert _SERVER_NAME in data["mcpServers"]

    @patch("strawpot.mcp.setup._global_config_candidates")
    @patch("strawpot.mcp.setup.shutil.which", return_value="/usr/bin/strawpot")
    def test_uses_existing_config_file(self, mock_which, mock_candidates, tmp_path):
        """If a config file already exists, use it instead of the first candidate."""
        first = tmp_path / "first" / "config.json"
        second = tmp_path / "second" / "config.json"
        second.parent.mkdir(parents=True)
        second.write_text('{"mcpServers": {}}')
        mock_candidates.return_value = [first, second]

        configure_mcp(project=False)

        # Should have written to the existing file (second), not first
        assert second.exists()
        data = json.loads(second.read_text())
        assert _SERVER_NAME in data["mcpServers"]
        assert not first.exists()
