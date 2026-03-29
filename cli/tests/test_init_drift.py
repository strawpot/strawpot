"""Tests for drift detection and inline metadata parsing."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from strawpot.init.drift import (
    DriftType,
    DriftWarning,
    check_drift,
    parse_inline_metadata,
    _hash_build_files,
)
from strawpot.init.exceptions import BrokenInlineMetadata


# ---------------------------------------------------------------------------
# parse_inline_metadata
# ---------------------------------------------------------------------------


class TestParseInlineMetadata:
    def test_valid_metadata(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# Engine\n\n"
            "<!-- strawpot:meta\n"
            "generated: 2026-03-29T12:00:00Z\n"
            "archetype: game-engine\n"
            "language: C++\n"
            "component: engine\n"
            "rule_count: 23\n"
            "-->\n\n"
            "## Hard Rules\n"
        )
        meta = parse_inline_metadata(claude_md)
        assert meta is not None
        assert meta["archetype"] == "game-engine"
        assert meta["language"] == "C++"
        assert meta["rule_count"] == 23

    def test_no_metadata(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Engine\n\nNo metadata here.\n")
        assert parse_inline_metadata(claude_md) is None

    def test_missing_file(self, tmp_path):
        assert parse_inline_metadata(tmp_path / "nonexistent.md") is None

    def test_broken_yaml_raises(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "<!-- strawpot:meta\n"
            "  this: is: broken: yaml: [[\n"
            "-->\n"
        )
        with pytest.raises(BrokenInlineMetadata):
            parse_inline_metadata(claude_md)

    def test_metadata_not_at_start(self, tmp_path):
        """Metadata can appear anywhere in the file."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# Engine\n\nSome content.\n\n"
            "<!-- strawpot:meta\n"
            "archetype: game-engine\n"
            "component: engine\n"
            "-->\n\n"
            "More content.\n"
        )
        meta = parse_inline_metadata(claude_md)
        assert meta is not None
        assert meta["archetype"] == "game-engine"


# ---------------------------------------------------------------------------
# check_drift — directory changes
# ---------------------------------------------------------------------------


class TestDriftDirectories:
    def test_new_directory_detected(self, tmp_path):
        comp = tmp_path / "engine"
        comp.mkdir()
        (comp / "src").mkdir()
        claude_md = comp / "CLAUDE.md"
        claude_md.write_text(
            "<!-- strawpot:meta\n"
            "generated: 2026-03-29T12:00:00Z\n"
            "component: engine\n"
            "dirs_at_gen: [src]\n"
            "-->\n"
        )
        # Add a new directory
        (comp / "tests").mkdir()

        warnings = check_drift(tmp_path)
        dir_warnings = [w for w in warnings if w.drift_type == DriftType.NEW_DIRECTORY]
        assert len(dir_warnings) == 1
        assert "tests" in dir_warnings[0].message

    def test_removed_directory_detected(self, tmp_path):
        comp = tmp_path / "engine"
        comp.mkdir()
        claude_md = comp / "CLAUDE.md"
        claude_md.write_text(
            "<!-- strawpot:meta\n"
            "generated: 2026-03-29T12:00:00Z\n"
            "component: engine\n"
            "dirs_at_gen: [src, tests]\n"
            "-->\n"
        )
        # Only src exists, tests was removed
        (comp / "src").mkdir()

        warnings = check_drift(tmp_path)
        removed = [w for w in warnings if w.drift_type == DriftType.REMOVED_DIRECTORY]
        assert len(removed) == 1
        assert "tests" in removed[0].message

    def test_no_drift_when_dirs_match(self, tmp_path):
        comp = tmp_path / "engine"
        comp.mkdir()
        (comp / "src").mkdir()
        claude_md = comp / "CLAUDE.md"
        claude_md.write_text(
            "<!-- strawpot:meta\n"
            "generated: 2026-03-29T12:00:00Z\n"
            "component: engine\n"
            "dirs_at_gen: [src]\n"
            "-->\n"
        )
        warnings = check_drift(tmp_path)
        dir_warnings = [w for w in warnings if w.drift_type in (DriftType.NEW_DIRECTORY, DriftType.REMOVED_DIRECTORY)]
        assert len(dir_warnings) == 0


# ---------------------------------------------------------------------------
# check_drift — build file changes
# ---------------------------------------------------------------------------


class TestDriftBuildFiles:
    def test_build_file_change_detected(self, tmp_path):
        comp = tmp_path / "engine"
        comp.mkdir()
        cmake = comp / "CMakeLists.txt"
        cmake.write_text("old content")
        old_hash = _hash_build_files(comp)

        claude_md = comp / "CLAUDE.md"
        claude_md.write_text(
            "<!-- strawpot:meta\n"
            f"generated: 2026-03-29T12:00:00Z\n"
            f"component: engine\n"
            f"build_file_hash: {old_hash}\n"
            "-->\n"
        )
        # Modify the build file
        cmake.write_text("new content")

        warnings = check_drift(tmp_path)
        build_warnings = [w for w in warnings if w.drift_type == DriftType.BUILD_FILE_CHANGED]
        assert len(build_warnings) == 1


# ---------------------------------------------------------------------------
# check_drift — freshness
# ---------------------------------------------------------------------------


class TestDriftFreshness:
    def test_stale_config_detected(self, tmp_path):
        old_time = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "<!-- strawpot:meta\n"
            f"generated: {old_time}\n"
            "component: root\n"
            "-->\n"
        )
        warnings = check_drift(tmp_path)
        stale = [w for w in warnings if w.drift_type == DriftType.STALE_CONFIG]
        assert len(stale) == 1
        assert "days ago" in stale[0].message

    def test_fresh_config_no_warning(self, tmp_path):
        recent = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "<!-- strawpot:meta\n"
            f"generated: {recent}\n"
            "component: root\n"
            "-->\n"
        )
        warnings = check_drift(tmp_path)
        stale = [w for w in warnings if w.drift_type == DriftType.STALE_CONFIG]
        assert len(stale) == 0


# ---------------------------------------------------------------------------
# CLI --check flag
# ---------------------------------------------------------------------------


class TestCheckCli:
    @patch("strawpot.cli.get_strawpot_home")
    def test_check_no_drift_exits_zero(self, mock_home, tmp_path):
        mock_home.return_value = tmp_path
        (tmp_path / ".first_run_done").touch()

        # No CLAUDE.md files → no drift
        from click.testing import CliRunner
        from strawpot.cli import cli
        result = CliRunner().invoke(cli, ["init", "--check"])
        assert result.exit_code == 0

    @patch("strawpot.cli.get_strawpot_home")
    def test_check_with_drift_exits_one(self, mock_home, tmp_path, monkeypatch):
        mock_home.return_value = tmp_path
        (tmp_path / ".first_run_done").touch()
        monkeypatch.chdir(tmp_path)

        # Create a stale CLAUDE.md
        old_time = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (tmp_path / "CLAUDE.md").write_text(
            "<!-- strawpot:meta\n"
            f"generated: {old_time}\n"
            "component: root\n"
            "-->\n"
        )

        from click.testing import CliRunner
        from strawpot.cli import cli
        result = CliRunner().invoke(cli, ["init", "--check"])
        assert result.exit_code == 1
