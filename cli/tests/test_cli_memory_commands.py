"""Tests for strawpot remember and strawpot recall CLI commands."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from strawpot_memory.memory_protocol import RecallEntry, RecallResult, RememberResult

from strawpot.cli import cli


@patch("strawpot.cli.get_standalone_provider", create=True)
def _invoke_remember(args, mock_provider_fn, *, provider=None):
    """Helper — invoke `remember` with a mocked provider."""
    if provider is None:
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="accepted", entry_id="k_test1234"
        )
    mock_provider_fn.return_value = provider

    with patch(
        "strawpot.memory.standalone.get_standalone_provider",
        return_value=provider,
    ):
        runner = CliRunner()
        return runner.invoke(cli, ["remember", *args])


@patch("strawpot.cli.get_standalone_provider", create=True)
def _invoke_recall(args, mock_provider_fn, *, provider=None):
    """Helper — invoke `recall` with a mocked provider."""
    if provider is None:
        provider = MagicMock()
        provider.recall.return_value = RecallResult(entries=[])
    mock_provider_fn.return_value = provider

    with patch(
        "strawpot.memory.standalone.get_standalone_provider",
        return_value=provider,
    ):
        runner = CliRunner()
        return runner.invoke(cli, ["recall", *args])


# -- remember -----------------------------------------------------------------


class TestRememberCommand:
    def test_remember_basic(self):
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="accepted", entry_id="k_abc12345"
        )
        result = _invoke_remember(["My project uses pytest"], provider=provider)
        assert result.exit_code == 0
        assert "Remembered" in result.output
        assert "k_abc12345" in result.output
        assert "project" in result.output

    def test_remember_duplicate(self):
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="duplicate", entry_id=""
        )
        result = _invoke_remember(["Already known fact"], provider=provider)
        assert result.exit_code == 0
        assert "Already remembered" in result.output
        assert "duplicate" in result.output

    def test_remember_with_scope(self):
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="accepted", entry_id="k_glob1234"
        )
        result = _invoke_remember(
            ["--scope", "global", "Global fact"], provider=provider
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
        result = _invoke_remember(
            ["-k", "auth,jwt", "Uses JWT for auth"], provider=provider
        )
        assert result.exit_code == 0
        call_kwargs = provider.remember.call_args.kwargs
        assert call_kwargs["keywords"] == ["auth", "jwt"]

    def test_remember_shows_breadcrumb(self):
        provider = MagicMock()
        provider.remember.return_value = RememberResult(
            status="accepted", entry_id="k_test1234"
        )
        result = _invoke_remember(["Some fact"], provider=provider)
        assert "strawpot mcp setup" in result.output


# -- recall -------------------------------------------------------------------


class TestRecallCommand:
    def test_recall_empty(self):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(entries=[])
        result = _invoke_recall(["authentication"], provider=provider)
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
        result = _invoke_recall(["authentication"], provider=provider)
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
        result = _invoke_recall(["query"], provider=provider)
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
        result = _invoke_recall(["--json", "test"], provider=provider)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["entry_id"] == "k_json1234"
        assert data[0]["score"] == 0.85

    def test_recall_with_scope_filter(self):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(entries=[])
        _invoke_recall(["--scope", "global", "query"], provider=provider)
        call_kwargs = provider.recall.call_args.kwargs
        assert call_kwargs["scope"] == "global"

    def test_recall_with_max_results(self):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(entries=[])
        _invoke_recall(["-n", "5", "query"], provider=provider)
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
