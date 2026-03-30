"""Tests for strawpot remember and strawpot recall CLI commands."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from strawpot_memory.memory_protocol import (
    ForgetResult,
    ListEntry,
    ListResult,
    RecallEntry,
    RecallResult,
    RememberResult,
)

from strawpot.cli import cli
from strawpot.memory.consolidation import ConsolidationAction, ConsolidationReport


def _invoke(args, *, provider=None):
    """Invoke CLI with a mocked standalone provider."""
    if provider is None:
        provider = MagicMock()

    with patch(
        "strawpot.memory.standalone.get_standalone_provider",
        return_value=provider,
    ):
        runner = CliRunner()
        return runner.invoke(cli, args)


# -- remember -----------------------------------------------------------------


class TestRememberCommand:
    def test_remember_basic(self):
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="accepted", entry_id="k_abc12345"
        )
        result = _invoke(["remember", "My project uses pytest"], provider=provider)
        assert result.exit_code == 0
        assert "Remembered" in result.output
        assert "k_abc12345" in result.output
        assert "project" in result.output

    def test_remember_duplicate(self):
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="duplicate", entry_id=""
        )
        result = _invoke(["remember", "Already known fact"], provider=provider)
        assert result.exit_code == 0
        assert "Already remembered" in result.output
        assert "duplicate" in result.output

    def test_remember_with_scope(self):
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="accepted", entry_id="k_glob1234"
        )
        result = _invoke(
            ["remember", "--scope", "global", "Global fact"], provider=provider
        )
        assert result.exit_code == 0
        assert "global" in result.output
        provider.remember.assert_called_once()
        call_kwargs = provider.remember.call_args.kwargs
        assert call_kwargs["scope"] == "global"

    def test_remember_with_keywords(self):
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="accepted", entry_id="k_kw123456"
        )
        result = _invoke(
            ["remember", "-k", "auth,jwt", "Uses JWT for auth"], provider=provider
        )
        assert result.exit_code == 0
        call_kwargs = provider.remember.call_args.kwargs
        assert call_kwargs["keywords"] == ["auth", "jwt"]

    def test_remember_shows_breadcrumb(self):
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="accepted", entry_id="k_test1234"
        )
        result = _invoke(["remember", "Some fact"], provider=provider)
        assert "strawpot mcp setup" in result.output


# -- recall -------------------------------------------------------------------


class TestRecallCommand:
    def test_recall_empty(self):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(entries=[])
        result = _invoke(["recall", "authentication"], provider=provider)
        assert result.exit_code == 0
        assert "No memories found" in result.output
        assert "strawpot remember" in result.output

    def test_recall_with_results(self):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(
            entries=[
                RecallEntry(
                    entry_id="k_abc12345",
                    content="Uses JWT with RS256",
                    keywords=["auth", "jwt"],
                    scope="project",
                    score=0.92,
                ),
                RecallEntry(
                    entry_id="k_def67890",
                    content="OAuth 2.0 for third-party",
                    keywords=["auth", "oauth"],
                    scope="global",
                    score=0.71,
                ),
            ]
        )
        result = _invoke(["recall", "authentication"], provider=provider)
        assert result.exit_code == 0
        assert "Found 2 memories" in result.output
        assert "k_abc12345" in result.output
        assert "Uses JWT with RS256" in result.output
        assert "0.92" in result.output
        assert "k_def67890" in result.output

    def test_recall_single_result(self):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(
            entries=[
                RecallEntry(
                    entry_id="k_one11111",
                    content="Single entry",
                    keywords=[],
                    scope="project",
                    score=1.0,
                ),
            ]
        )
        result = _invoke(["recall", "query"], provider=provider)
        assert "Found 1 memory" in result.output

    def test_recall_json_output(self):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(
            entries=[
                RecallEntry(
                    entry_id="k_json1234",
                    content="Test fact",
                    keywords=["test"],
                    scope="project",
                    score=0.85,
                ),
            ]
        )
        result = _invoke(["recall", "--json", "test"], provider=provider)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["entry_id"] == "k_json1234"
        assert data[0]["score"] == 0.85

    def test_recall_with_scope_filter(self):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(entries=[])
        _invoke(["recall", "--scope", "global", "query"], provider=provider)
        call_kwargs = provider.recall.call_args.kwargs
        assert call_kwargs["scope"] == "global"

    def test_recall_with_max_results(self):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(entries=[])
        _invoke(["recall", "-n", "5", "query"], provider=provider)
        call_kwargs = provider.recall.call_args.kwargs
        assert call_kwargs["max_results"] == 5


# -- command group ------------------------------------------------------------


class TestMemoryCommandGroup:
    def test_remember_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "remember" in result.output

    def test_recall_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "recall" in result.output

    def test_memory_group_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "Memory" in result.output


# -- memory consolidate ------------------------------------------------------


def _invoke_consolidate(args, *, report=None, provider=None):
    """Invoke ``memory consolidate`` with mocked consolidation."""
    if report is None:
        report = ConsolidationReport()
    if provider is None:
        provider = MagicMock()

    with patch(
        "strawpot.memory.standalone.get_standalone_provider",
        return_value=provider,
    ), patch(
        "strawpot.memory.consolidation.consolidate",
        return_value=report,
    ) as mock_consolidate, patch(
        "strawpot.memory.standalone.detect_project_dir",
        return_value="/fake/project",
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["memory", "consolidate"] + args)
        return result, mock_consolidate


class TestMemoryConsolidateCommand:
    """Tests for `strawpot memory consolidate` CLI command (AC #4)."""

    def test_no_actions_needed(self):
        """Clean run with nothing to consolidate shows success message."""
        report = ConsolidationReport(total_entries_scanned=15)
        result, _ = _invoke_consolidate([], report=report)

        assert result.exit_code == 0
        assert "No consolidation needed" in result.output
        assert "15" in result.output

    def test_dry_run_flag(self):
        """--dry-run is passed through to consolidate()."""
        report = ConsolidationReport(
            total_entries_scanned=5,
            groups_found=1,
            actions=[
                ConsolidationAction(
                    action="delete_duplicate",
                    entry_id="dup_1",
                    reason="Near-duplicate of keep_1",
                ),
            ],
        )
        result, mock_consolidate = _invoke_consolidate(
            ["--dry-run"], report=report
        )

        assert result.exit_code == 0
        assert "Would consolidate" in result.output
        call_kwargs = mock_consolidate.call_args.kwargs
        assert call_kwargs["dry_run"] is True

    def test_scope_flag(self):
        """--scope is passed through to consolidate()."""
        report = ConsolidationReport()
        _, mock_consolidate = _invoke_consolidate(
            ["--scope", "global"], report=report
        )

        call_kwargs = mock_consolidate.call_args.kwargs
        assert call_kwargs["scope"] == "global"

    def test_json_output(self):
        """--json renders the report as JSON."""
        report = ConsolidationReport(
            total_entries_scanned=10,
            groups_found=2,
            actions=[
                ConsolidationAction(
                    action="delete_duplicate",
                    entry_id="dup_1",
                    reason="Near-duplicate of keep_1",
                ),
                ConsolidationAction(
                    action="archive_stale",
                    entry_id="old_1",
                    reason="Importance 0.050 < 0.1, age 90 days",
                ),
            ],
        )
        result, _ = _invoke_consolidate(["--json"], report=report)

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_entries_scanned"] == 10
        assert data["groups_found"] == 2
        assert data["duplicates_removed"] == 1
        assert data["entries_archived"] == 1
        assert len(data["actions"]) == 2
        assert data["actions"][0]["action"] == "delete_duplicate"
        assert data["actions"][1]["action"] == "archive_stale"

    def test_json_dry_run_combined(self):
        """--json --dry-run outputs JSON with dry_run=true."""
        report = ConsolidationReport(total_entries_scanned=3)
        result, _ = _invoke_consolidate(
            ["--json", "--dry-run"], report=report
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True

    def test_displays_action_details(self):
        """Actions are rendered with entry IDs and reasons."""
        report = ConsolidationReport(
            total_entries_scanned=5,
            groups_found=1,
            actions=[
                ConsolidationAction(
                    action="delete_duplicate",
                    entry_id="dup_abc",
                    reason="Near-duplicate of keep_xyz (similarity >= 0.8)",
                ),
            ],
        )
        result, _ = _invoke_consolidate([], report=report)

        assert result.exit_code == 0
        assert "dup_abc" in result.output
        assert "Duplicates" in result.output
