"""End-to-end tests for the memory CLI flow and edge cases.

Uses a real Dial provider with a temporary directory — no mocks.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from strawpot.cli import cli


@pytest.fixture
def memory_env(tmp_path):
    """Set up a real Dial provider backed by a temp directory."""
    dial_memory = pytest.importorskip("dial_memory", reason="dial-memory package not installed")
    from dial_memory.provider import DialMemoryProvider

    provider = DialMemoryProvider(
        {
            "storage_dir": str(tmp_path / "project"),
            "global_storage_dir": str(tmp_path / "global"),
        }
    )
    return provider


@pytest.fixture
def run(memory_env):
    """Invoke CLI commands with a real Dial provider."""

    def _run(args):
        with patch(
            "strawpot.memory.standalone.get_standalone_provider",
            return_value=memory_env,
        ):
            with patch("strawpot.mcp.status.check_mcp_status", return_value=(True, "")):
                runner = CliRunner()
                return runner.invoke(cli, args, catch_exceptions=False)

    return _run


# ---------------------------------------------------------------------------
# Full-flow E2E test
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestFullMemoryFlow:
    def test_remember_recall_list_forget_cycle(self, run):
        """Complete user journey: remember → recall → list → forget → verify."""

        # Step 1: Remember two facts
        r1 = run(["remember", "API uses JWT with RS256 for authentication", "-k", "auth,jwt"])
        assert r1.exit_code == 0
        assert "Remembered" in r1.output
        # Extract entry ID from output
        id1 = _extract_id(r1.output)

        r2 = run(["remember", "Database is PostgreSQL 15 on RDS", "-k", "database,postgres"])
        assert r2.exit_code == 0
        id2 = _extract_id(r2.output)

        # Step 2: Recall by query
        r3 = run(["recall", "authentication"])
        assert r3.exit_code == 0
        assert "JWT" in r3.output or "auth" in r3.output.lower()

        # Step 3: List all
        r4 = run(["memory", "list"])
        assert r4.exit_code == 0
        assert "2 memories" in r4.output
        assert id1 in r4.output
        assert id2 in r4.output

        # Step 4: Forget first entry
        r5 = run(["forget", id1])
        assert r5.exit_code == 0
        assert "Deleted" in r5.output

        # Step 5: Verify recall returns empty for auth
        r6 = run(["recall", "--json", "JWT RS256 authentication"])
        assert r6.exit_code == 0
        data = json.loads(r6.output)
        assert len(data) == 0

        # Step 6: List shows 1 entry
        r7 = run(["memory", "list"])
        assert r7.exit_code == 0
        assert "1 memory" in r7.output
        assert id2 in r7.output


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestEdgeCases:
    def test_empty_recall(self, run):
        """Recall with no memories stored shows helpful message."""
        result = run(["recall", "anything"])
        assert result.exit_code == 0
        assert "No memories found" in result.output

    def test_empty_list(self, run):
        """Memory list with nothing stored shows empty state."""
        result = run(["memory", "list"])
        assert result.exit_code == 0
        assert "No memories stored" in result.output

    def test_very_long_fact(self, run):
        """Facts >1000 chars are accepted and stored."""
        long_fact = "A" * 1500
        result = run(["remember", long_fact])
        assert result.exit_code == 0
        assert "Remembered" in result.output

        # List truncates display
        result = run(["memory", "list"])
        assert "…" in result.output  # Truncated

    def test_unicode_emoji_facts(self, run):
        """Unicode and emoji in facts are handled correctly."""
        fact = "使用 PostgreSQL 数据库 🐘 for persistence"
        result = run(["remember", fact])
        assert result.exit_code == 0

        result = run(["recall", "PostgreSQL"])
        assert "🐘" in result.output or "PostgreSQL" in result.output

    def test_special_characters(self, run):
        """Quotes, newlines, and special chars in facts."""
        fact = 'Config uses "double quotes" and key=value pairs'
        result = run(["remember", fact])
        assert result.exit_code == 0

        # Verify via JSON output
        result = run(["memory", "list", "--json"])
        data = json.loads(result.output)
        assert len(data) == 1
        assert '"double quotes"' in data[0]["content"]

    def test_forget_nonexistent_id(self, run):
        """Forget with non-existent ID exits 1."""
        result = run(["forget", "k_nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_duplicate_detection(self, run):
        """Remember same fact twice detects duplicate."""
        fact = "This project uses pytest for testing with coverage reports"
        run(["remember", fact])
        result = run(["remember", fact])
        assert "Already remembered" in result.output

    def test_global_scope(self, run):
        """Global scope facts are stored and retrievable."""
        run(["remember", "--scope", "global", "Global knowledge shared across all projects"])
        result = run(["memory", "list", "--scope", "global"])
        assert "Global knowledge" in result.output

    def test_recall_json_output(self, run):
        """JSON output is valid and machine-readable."""
        run(["remember", "Test fact for JSON output verification", "-k", "test,json"])
        result = run(["recall", "--json", "JSON output"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        if data:
            assert "entry_id" in data[0]
            assert "score" in data[0]

    def test_list_json_output(self, run):
        """Memory list JSON output is valid."""
        run(["remember", "Test entry for JSON list"])
        result = run(["memory", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------


class TestHelpText:
    def test_remember_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["remember", "--help"])
        assert "Store a fact" in result.output
        assert "--scope" in result.output
        assert "--keywords" in result.output

    def test_recall_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["recall", "--help"])
        assert "Search stored memories" in result.output
        assert "--json" in result.output

    def test_forget_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["forget", "--help"])
        assert "Delete" in result.output

    def test_memory_list_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["memory", "list", "--help"])
        assert "List all stored" in result.output
        assert "--scope" in result.output
        assert "--json" in result.output

    def test_mcp_setup_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "setup", "--help"])
        assert "Auto-configure" in result.output
        assert "--project" in result.output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_id(output: str) -> str:
    """Extract entry ID (k_XXXXXXXX) from command output."""
    for line in output.splitlines():
        if "ID:" in line:
            return line.split("ID:")[1].strip()
    raise ValueError(f"No ID found in output:\n{output}")
