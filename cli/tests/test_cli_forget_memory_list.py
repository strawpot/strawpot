"""Tests for strawpot forget and strawpot memory list CLI commands."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from strawpot_memory.memory_protocol import ForgetResult, ListEntry, ListResult

from strawpot.cli import cli


def _make_provider():
    return MagicMock()


def _invoke(args, *, provider=None):
    """Invoke CLI with a mocked standalone provider."""
    if provider is None:
        provider = _make_provider()

    with patch(
        "strawpot.memory.standalone.get_standalone_provider",
        return_value=provider,
    ):
        runner = CliRunner()
        return runner.invoke(cli, args)


# -- forget -------------------------------------------------------------------


class TestForgetCommand:
    def test_forget_success(self):
        provider = _make_provider()
        provider.forget.return_value = ForgetResult(
            status="deleted", entry_id="k_abc12345"
        )
        result = _invoke(["forget", "k_abc12345"], provider=provider)
        assert result.exit_code == 0
        assert "Deleted memory k_abc12345" in result.output

    def test_forget_not_found(self):
        provider = _make_provider()
        provider.forget.return_value = ForgetResult(
            status="not_found", entry_id="k_missing"
        )
        result = _invoke(["forget", "k_missing"], provider=provider)
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_forget_calls_provider_correctly(self):
        provider = _make_provider()
        provider.forget.return_value = ForgetResult(
            status="deleted", entry_id="k_test1234"
        )
        _invoke(["forget", "k_test1234"], provider=provider)
        provider.forget.assert_called_once_with(entry_id="k_test1234")


# -- memory list --------------------------------------------------------------


class TestMemoryListCommand:
    def test_list_empty(self):
        provider = _make_provider()
        provider.list_entries.return_value = ListResult(entries=[], total_count=0)
        result = _invoke(["memory", "list"], provider=provider)
        assert result.exit_code == 0
        assert "No memories stored yet" in result.output
        assert "strawpot remember" in result.output

    def test_list_with_entries(self):
        provider = _make_provider()
        provider.list_entries.return_value = ListResult(
            entries=[
                ListEntry(
                    entry_id="k_abc12345",
                    content="Uses JWT for auth",
                    keywords=["auth", "jwt"],
                    scope="project",
                    ts="2026-03-26T12:00:00Z",
                ),
                ListEntry(
                    entry_id="k_def67890",
                    content="Database is PostgreSQL",
                    keywords=[],
                    scope="global",
                    ts="2026-03-25T10:00:00Z",
                ),
            ],
            total_count=2,
        )
        result = _invoke(["memory", "list"], provider=provider)
        assert result.exit_code == 0
        assert "2 memories stored" in result.output
        assert "k_abc12345" in result.output
        assert "Uses JWT for auth" in result.output
        assert "auth, jwt" in result.output
        assert "2026-03-26" in result.output
        assert "k_def67890" in result.output

    def test_list_single_entry(self):
        provider = _make_provider()
        provider.list_entries.return_value = ListResult(
            entries=[
                ListEntry(
                    entry_id="k_single11",
                    content="One fact",
                    keywords=[],
                    scope="project",
                    ts="2026-03-26T12:00:00Z",
                ),
            ],
            total_count=1,
        )
        result = _invoke(["memory", "list"], provider=provider)
        assert "1 memory stored" in result.output

    def test_list_with_scope_filter(self):
        provider = _make_provider()
        provider.list_entries.return_value = ListResult(entries=[], total_count=0)
        _invoke(["memory", "list", "--scope", "global"], provider=provider)
        call_kwargs = provider.list_entries.call_args.kwargs
        assert call_kwargs["scope"] == "global"

    def test_list_json_output(self):
        provider = _make_provider()
        provider.list_entries.return_value = ListResult(
            entries=[
                ListEntry(
                    entry_id="k_json1234",
                    content="Test fact",
                    keywords=["test"],
                    scope="project",
                    ts="2026-03-26T12:00:00Z",
                ),
            ],
            total_count=1,
        )
        result = _invoke(["memory", "list", "--json"], provider=provider)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["entry_id"] == "k_json1234"

    def test_list_default_limit_20(self):
        provider = _make_provider()
        provider.list_entries.return_value = ListResult(entries=[], total_count=0)
        _invoke(["memory", "list"], provider=provider)
        call_kwargs = provider.list_entries.call_args.kwargs
        assert call_kwargs["limit"] == 20

    def test_list_all_flag(self):
        provider = _make_provider()
        provider.list_entries.return_value = ListResult(entries=[], total_count=0)
        _invoke(["memory", "list", "--all"], provider=provider)
        call_kwargs = provider.list_entries.call_args.kwargs
        assert call_kwargs["limit"] == 10000

    def test_list_truncation_footer(self):
        """Shows 'showing X of Y' when there are more entries than displayed."""
        entries = [
            ListEntry(
                entry_id=f"k_{i:08d}",
                content=f"Fact {i}",
                keywords=[],
                scope="project",
                ts="2026-03-26T12:00:00Z",
            )
            for i in range(3)
        ]
        provider = _make_provider()
        provider.list_entries.return_value = ListResult(
            entries=entries, total_count=25
        )
        result = _invoke(["memory", "list"], provider=provider)
        assert "showing 3 of 25" in result.output
        assert "--all" in result.output

    def test_list_long_content_truncated(self):
        provider = _make_provider()
        long_content = "A" * 200
        provider.list_entries.return_value = ListResult(
            entries=[
                ListEntry(
                    entry_id="k_long1234",
                    content=long_content,
                    keywords=[],
                    scope="project",
                    ts="2026-03-26T12:00:00Z",
                ),
            ],
            total_count=1,
        )
        result = _invoke(["memory", "list"], provider=provider)
        # Content should be truncated at 100 chars + ellipsis
        assert "…" in result.output
        assert long_content not in result.output


# -- command group ------------------------------------------------------------


class TestCommandGroup:
    def test_forget_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "forget" in result.output

    def test_memory_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "memory" in result.output
