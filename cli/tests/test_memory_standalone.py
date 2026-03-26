"""Tests for strawpot.memory.standalone."""

from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import click
import pytest

from strawpot.memory.standalone import (
    CLI_AGENT_ID,
    CLI_ROLE,
    CLI_SESSION_ID,
    detect_project_dir,
    get_standalone_provider,
)


# -- CLI constants ------------------------------------------------------------


class TestCLIConstants:
    def test_cli_session_id_defined(self):
        assert CLI_SESSION_ID == "cli-standalone"

    def test_cli_agent_id_defined(self):
        assert CLI_AGENT_ID == "cli-user"

    def test_cli_role_defined(self):
        assert CLI_ROLE == "user"


# -- detect_project_dir -------------------------------------------------------


class TestDetectProjectDir:
    def test_finds_strawpot_toml(self, tmp_path):
        (tmp_path / "strawpot.toml").touch()
        subdir = tmp_path / "a" / "b"
        subdir.mkdir(parents=True)
        result = detect_project_dir(str(subdir))
        assert result == str(tmp_path)

    def test_finds_dot_strawpot_dir(self, tmp_path):
        (tmp_path / ".strawpot").mkdir()
        subdir = tmp_path / "nested"
        subdir.mkdir()
        result = detect_project_dir(str(subdir))
        assert result == str(tmp_path)

    def test_prefers_closest_marker(self, tmp_path):
        """Closest project root wins (child over parent)."""
        (tmp_path / "strawpot.toml").touch()
        child = tmp_path / "sub"
        child.mkdir()
        (child / "strawpot.toml").touch()
        result = detect_project_dir(str(child))
        assert result == str(child)

    def test_raises_when_not_found(self, tmp_path):
        # tmp_path is a clean dir with no markers
        with pytest.raises(click.ClickException, match="No StrawPot project found"):
            detect_project_dir(str(tmp_path))

    def test_defaults_to_cwd(self, tmp_path, monkeypatch):
        (tmp_path / ".strawpot").mkdir()
        monkeypatch.chdir(tmp_path)
        result = detect_project_dir()
        assert result == str(tmp_path)


# -- get_standalone_provider --------------------------------------------------


class TestGetStandaloneProvider:
    @patch("strawpot.memory.standalone.load_provider")
    @patch("strawpot.memory.standalone.resolve_memory")
    @patch("strawpot.memory.standalone.load_config")
    def test_returns_provider(self, mock_config, mock_resolve, mock_load, tmp_path):
        (tmp_path / "strawpot.toml").touch()
        mock_cfg = MagicMock()
        mock_cfg.memory = "dial"
        mock_cfg.memory_config = {}
        mock_config.return_value = mock_cfg

        mock_spec = MagicMock()
        mock_resolve.return_value = mock_spec

        mock_provider = MagicMock()
        mock_load.return_value = mock_provider

        result = get_standalone_provider(project_dir=str(tmp_path))
        assert result is mock_provider
        mock_resolve.assert_called_once_with("dial", str(tmp_path), {})
        mock_load.assert_called_once_with(mock_spec)

    @patch("strawpot.memory.standalone.load_provider")
    @patch("strawpot.memory.standalone.resolve_memory")
    @patch("strawpot.memory.standalone.load_config")
    def test_uses_custom_memory_name(self, mock_config, mock_resolve, mock_load, tmp_path):
        (tmp_path / "strawpot.toml").touch()
        mock_cfg = MagicMock()
        mock_cfg.memory = "dial"
        mock_cfg.memory_config = {}
        mock_config.return_value = mock_cfg

        mock_resolve.return_value = MagicMock()
        mock_load.return_value = MagicMock()

        get_standalone_provider(project_dir=str(tmp_path), memory_name="custom")
        mock_resolve.assert_called_once_with("custom", str(tmp_path), {})

    @patch("strawpot.memory.standalone.load_provider")
    @patch("strawpot.memory.standalone.resolve_memory")
    @patch("strawpot.memory.standalone.load_config")
    def test_reads_memory_config_from_toml(self, mock_config, mock_resolve, mock_load, tmp_path):
        (tmp_path / "strawpot.toml").touch()
        mock_cfg = MagicMock()
        mock_cfg.memory = "dial"
        mock_cfg.memory_config = {"storage_dir": "/custom/path"}
        mock_config.return_value = mock_cfg

        mock_resolve.return_value = MagicMock()
        mock_load.return_value = MagicMock()

        get_standalone_provider(project_dir=str(tmp_path))
        mock_resolve.assert_called_once_with(
            "dial", str(tmp_path), {"storage_dir": "/custom/path"}
        )

    @patch("strawpot.memory.standalone.load_provider")
    @patch("strawpot.memory.standalone.resolve_memory")
    @patch("strawpot.memory.standalone.load_config")
    def test_defaults_to_dial_when_no_config(self, mock_config, mock_resolve, mock_load, tmp_path):
        (tmp_path / "strawpot.toml").touch()
        mock_cfg = MagicMock()
        mock_cfg.memory = ""
        mock_cfg.memory_config = {}
        mock_config.return_value = mock_cfg

        mock_resolve.return_value = MagicMock()
        mock_load.return_value = MagicMock()

        get_standalone_provider(project_dir=str(tmp_path))
        mock_resolve.assert_called_once_with("dial", str(tmp_path), {})

    @patch("strawpot.memory.standalone.detect_project_dir")
    @patch("strawpot.memory.standalone.load_provider")
    @patch("strawpot.memory.standalone.resolve_memory")
    @patch("strawpot.memory.standalone.load_config")
    def test_auto_detects_project_dir(self, mock_config, mock_resolve, mock_load, mock_detect, tmp_path):
        mock_detect.return_value = str(tmp_path)
        mock_cfg = MagicMock()
        mock_cfg.memory = "dial"
        mock_cfg.memory_config = {}
        mock_config.return_value = mock_cfg

        mock_resolve.return_value = MagicMock()
        mock_load.return_value = MagicMock()

        get_standalone_provider()  # no project_dir
        mock_detect.assert_called_once()


# -- No forbidden imports -----------------------------------------------------


class TestModuleImports:
    def test_no_session_import(self):
        """standalone.py must not import Session or denden."""
        import inspect
        import strawpot.memory.standalone as mod

        source = inspect.getsource(mod)
        assert "from strawpot.session" not in source
        assert "import strawpot.session" not in source
        assert "denden" not in source
