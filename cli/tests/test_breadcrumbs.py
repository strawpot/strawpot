"""Tests for breadcrumbs and MCP status check."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from strawpot_memory.memory_protocol import (
    ForgetResult,
    ListEntry,
    ListResult,
    RecallEntry,
    RecallResult,
    RememberResult,
)

from strawpot.mcp.setup import _SERVER_NAME
from strawpot.mcp.status import check_mcp_status


# -- MCP status ---------------------------------------------------------------


class TestCheckMcpStatus:
    def test_not_configured(self, tmp_path):
        with patch("strawpot.mcp.status._global_config_candidates", return_value=[tmp_path / "config.json"]):
            with patch("strawpot.mcp.status._project_config_path", return_value=tmp_path / ".claude" / "mcp.json"):
                configured, path = check_mcp_status()
                assert configured is False
                assert path == ""

    def test_configured_globally(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "mcpServers": {_SERVER_NAME: {"command": "strawpot"}}
        }))
        with patch("strawpot.mcp.status._global_config_candidates", return_value=[config_path]):
            with patch("strawpot.mcp.status._project_config_path", return_value=tmp_path / ".claude" / "mcp.json"):
                configured, path = check_mcp_status()
                assert configured is True
                assert str(config_path) == path

    def test_configured_project_level(self, tmp_path):
        project_config = tmp_path / ".claude" / "mcp.json"
        project_config.parent.mkdir(parents=True)
        project_config.write_text(json.dumps({
            "mcpServers": {_SERVER_NAME: {"command": "strawpot"}}
        }))
        with patch("strawpot.mcp.status._project_config_path", return_value=project_config):
            configured, path = check_mcp_status()
            assert configured is True

    def test_corrupt_config_returns_false(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text("not json")
        with patch("strawpot.mcp.status._global_config_candidates", return_value=[config_path]):
            with patch("strawpot.mcp.status._project_config_path", return_value=tmp_path / "no"):
                configured, _ = check_mcp_status()
                assert configured is False


# -- Breadcrumb output in CLI commands ----------------------------------------


def _invoke(args, *, provider=None):
    """Invoke CLI with a mocked standalone provider."""
    from strawpot.cli import cli

    if provider is None:
        provider = MagicMock()

    with patch(
        "strawpot.memory.standalone.get_standalone_provider",
        return_value=provider,
    ):
        runner = CliRunner()
        return runner.invoke(cli, args)


class TestRememberBreadcrumb:
    @patch("strawpot.mcp.status.check_mcp_status", return_value=(False, ""))
    def test_shows_mcp_warning_when_not_configured(self, mock_status):
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="accepted", entry_id="k_test1234"
        )
        result = _invoke(["remember", "Test fact"], provider=provider)
        assert "MCP not configured" in result.output
        assert "strawpot mcp setup" in result.output

    @patch("strawpot.mcp.status.check_mcp_status", return_value=(True, "/some/path"))
    def test_shows_claude_confirmation_when_configured(self, mock_status):
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="accepted", entry_id="k_test1234"
        )
        result = _invoke(["remember", "Test fact"], provider=provider)
        assert "Claude Code will see this" in result.output


class TestRecallBreadcrumb:
    def test_shows_memory_list_hint(self):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(
            entries=[
                RecallEntry(
                    entry_id="k_r1", content="Test", keywords=[],
                    scope="project", score=1.0,
                ),
            ]
        )
        result = _invoke(["recall", "test"], provider=provider)
        assert "strawpot memory list" in result.output

    def test_json_output_no_breadcrumbs(self):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(entries=[])
        result = _invoke(["recall", "--json", "test"], provider=provider)
        assert "strawpot memory list" not in result.output


class TestForgetBreadcrumb:
    def test_shows_breadcrumb_on_success(self):
        provider = MagicMock()
        provider.forget.return_value = ForgetResult(
            status="deleted", entry_id="k_del12345"
        )
        result = _invoke(["forget", "k_del12345"], provider=provider)
        assert "no longer see this" in result.output


class TestListBreadcrumb:
    def test_shows_forget_hint(self):
        provider = MagicMock()
        provider.list_entries.return_value = ListResult(
            entries=[
                ListEntry(
                    entry_id="k_l1", content="Fact", keywords=[],
                    scope="project", ts="2026-03-26T12:00:00Z",
                ),
            ],
            total_count=1,
        )
        result = _invoke(["memory", "list"], provider=provider)
        assert "strawpot forget" in result.output

    def test_json_output_no_breadcrumbs(self):
        provider = MagicMock()
        provider.list_entries.return_value = ListResult(entries=[], total_count=0)
        result = _invoke(["memory", "list", "--json"], provider=provider)
        assert "strawpot forget" not in result.output
