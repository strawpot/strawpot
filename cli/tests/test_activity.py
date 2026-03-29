"""Tests for strawpot.activity — log line activity parser."""

from strawpot.activity import (
    get_agent_log_path,
    parse_activity,
    read_last_activity_line,
)


# ---------------------------------------------------------------------------
# parse_activity
# ---------------------------------------------------------------------------


class TestParseActivity:
    """Tests for parse_activity()."""

    def test_empty_string_returns_none(self):
        assert parse_activity("") is None

    def test_none_like_input(self):
        assert parse_activity("   ") is None

    def test_reading_file(self):
        result = parse_activity("⠋ Reading src/app.ts...")
        assert result is not None
        tool, summary = result
        assert tool == "Read"
        assert "Reading src/app.ts" in summary

    def test_editing_file(self):
        result = parse_activity("⠙ Editing src/component.tsx...")
        assert result is not None
        assert result[0] == "Edit"
        assert "Editing src/component.tsx" in result[1]

    def test_writing_file(self):
        result = parse_activity("⠹ Writing to src/index.ts...")
        assert result is not None
        assert result[0] == "Write"

    def test_writing_without_to(self):
        result = parse_activity("⠹ Writing src/index.ts...")
        assert result is not None
        assert result[0] == "Write"

    def test_running_bash_command(self):
        result = parse_activity("⠸ Running bash command: npm test...")
        assert result is not None
        assert result[0] == "Bash"

    def test_running_command(self):
        result = parse_activity("⠼ Running npm install...")
        assert result is not None
        assert result[0] == "Bash"

    def test_executing_command(self):
        result = parse_activity("⠴ Executing pytest...")
        assert result is not None
        assert result[0] == "Bash"

    def test_searching(self):
        result = parse_activity("⠦ Searching for files...")
        assert result is not None
        assert result[0] == "Search"

    def test_thinking(self):
        result = parse_activity("⠧ Thinking...")
        assert result is not None
        assert result[0] == "Think"

    def test_planning(self):
        result = parse_activity("⠇ Planning...")
        assert result is not None
        assert result[0] == "Think"

    def test_spawning_agent(self):
        result = parse_activity("⠏ Launching agent code-reviewer...")
        assert result is not None
        assert result[0] == "Agent"

    def test_ansi_codes_stripped(self):
        result = parse_activity("\x1b[32m⠋ Reading file.py...\x1b[0m")
        assert result is not None
        assert result[0] == "Read"

    def test_generic_activity_with_ellipsis(self):
        result = parse_activity("⠋ Analyzing dependencies...")
        assert result is not None
        assert result[0] == "Tool"
        assert "Analyzing dependencies" in result[1]

    def test_generic_activity_with_unicode_ellipsis(self):
        result = parse_activity("⠋ Processing…")
        assert result is not None
        assert result[0] == "Tool"

    def test_plain_text_no_activity(self):
        # Regular output text should not be parsed as activity
        result = parse_activity("Here is the implementation of the function:")
        assert result is None

    def test_long_line_truncated(self):
        long_path = "a" * 200
        result = parse_activity(f"⠋ Reading {long_path}...")
        assert result is not None
        assert len(result[1]) <= 120

    def test_case_insensitive(self):
        result = parse_activity("⠋ READING src/app.ts...")
        assert result is not None
        assert result[0] == "Read"

    def test_no_spinner_prefix(self):
        # Activity text without spinner chars should still match
        result = parse_activity("Reading src/app.ts...")
        assert result is not None
        assert result[0] == "Read"

    def test_same_activity_returns_same_tuple(self):
        # Ensure tuple equality works for dedup checks
        r1 = parse_activity("⠋ Reading file.py...")
        r2 = parse_activity("⠋ Reading file.py...")
        assert r1 == r2

    def test_different_activity_returns_different_tuple(self):
        r1 = parse_activity("⠋ Reading file.py...")
        r2 = parse_activity("⠋ Editing file.py...")
        assert r1 != r2


# ---------------------------------------------------------------------------
# read_last_activity_line
# ---------------------------------------------------------------------------


class TestReadLastActivityLine:
    """Tests for read_last_activity_line()."""

    def test_empty_file(self, tmp_path):
        log = tmp_path / "test.log"
        log.write_text("")
        assert read_last_activity_line(str(log)) is None

    def test_single_line(self, tmp_path):
        log = tmp_path / "test.log"
        log.write_text("⠋ Reading file.py...\n")
        result = read_last_activity_line(str(log))
        assert result is not None
        assert "Reading file.py" in result

    def test_multiple_lines_returns_last(self, tmp_path):
        log = tmp_path / "test.log"
        log.write_text("⠋ Reading file.py...\n⠙ Editing file.py...\n")
        result = read_last_activity_line(str(log))
        assert result is not None
        assert "Editing file.py" in result

    def test_trailing_empty_lines_skipped(self, tmp_path):
        log = tmp_path / "test.log"
        log.write_text("⠋ Reading file.py...\n\n\n")
        result = read_last_activity_line(str(log))
        assert result is not None
        assert "Reading file.py" in result

    def test_nonexistent_file_returns_none(self):
        assert read_last_activity_line("/nonexistent/path.log") is None

    def test_large_file_reads_last_line(self, tmp_path):
        log = tmp_path / "test.log"
        # Write enough lines to exceed 4KB
        lines = ["Line " + str(i) + "\n" for i in range(500)]
        lines.append("⠋ Final activity...\n")
        log.write_text("".join(lines))
        result = read_last_activity_line(str(log))
        assert result == "⠋ Final activity..."


# ---------------------------------------------------------------------------
# get_agent_log_path
# ---------------------------------------------------------------------------


class TestGetAgentLogPath:
    def test_path_format(self):
        result = get_agent_log_path("/sessions/run_abc", "agent_123")
        assert result == "/sessions/run_abc/agents/agent_123/.log"
