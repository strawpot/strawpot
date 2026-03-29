"""Integration tests for the strawpot init end-to-end pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from strawpot.init.generator import generate_files
from strawpot.init.types import ComponentConfig, GeneratedFile, ProjectConfig
from strawpot.init.writer import write_files


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _game_config(project_name: str = "TestGame") -> ProjectConfig:
    """Create a ProjectConfig for a game with engine component."""
    return ProjectConfig(
        project_name=project_name,
        project_type="Game",
        components=[
            ComponentConfig(
                name="engine",
                path="engine/",
                language="C++",
                build_system="CMake",
                archetype="game-engine",
                archetype_answers={
                    "render_api": "Vulkan",
                    "ecs_style": "Archetype-based",
                    "threading": "Job system",
                },
            ),
        ],
    )


def _web_config(project_name: str = "TestAPI") -> ProjectConfig:
    """Create a ProjectConfig for a web API."""
    return ProjectConfig(
        project_name=project_name,
        project_type="Web",
        components=[
            ComponentConfig(
                name="api",
                path="api/",
                language="Python",
                archetype="web-api",
                archetype_answers={
                    "framework": "FastAPI",
                    "database": "PostgreSQL",
                    "api_style": "REST",
                    "auth": "JWT",
                },
            ),
        ],
    )


# ---------------------------------------------------------------------------
# generate_files
# ---------------------------------------------------------------------------


class TestGenerateFiles:
    def test_generates_game_engine(self):
        config = _game_config()
        files = generate_files(config)
        assert len(files) == 1
        assert files[0].path == "engine/CLAUDE.md"
        assert files[0].rule_count >= 15

    def test_generates_web_api(self):
        config = _web_config()
        files = generate_files(config)
        assert len(files) == 1
        assert files[0].path == "api/CLAUDE.md"
        assert files[0].rule_count >= 10

    def test_multi_component_generates_root(self):
        config = ProjectConfig(
            project_name="MultiProject",
            project_type="Game",
            components=[
                ComponentConfig(
                    name="engine", path="engine/", language="C++",
                    archetype="game-engine",
                    archetype_answers={
                        "render_api": "Vulkan",
                        "ecs_style": "No ECS",
                        "threading": "Single-threaded",
                    },
                ),
                ComponentConfig(
                    name="api", path="api/", language="Python",
                    archetype="web-api",
                    archetype_answers={
                        "framework": "FastAPI",
                        "database": "None",
                        "api_style": "REST",
                        "auth": "None",
                    },
                ),
            ],
        )
        files = generate_files(config)
        paths = {f.path for f in files}
        assert "engine/CLAUDE.md" in paths
        assert "api/CLAUDE.md" in paths
        assert "CLAUDE.md" in paths  # Root file

    def test_unknown_archetype_falls_back_to_generic(self):
        config = ProjectConfig(
            project_name="Test",
            project_type="Other",
            components=[
                ComponentConfig(
                    name="lib", path="lib/", language="Haskell",
                    archetype="nonexistent",
                ),
            ],
        )
        files = generate_files(config, verbose=True)
        # Falls back to generic archetype
        assert len(files) == 1
        assert files[0].rule_count >= 10

    def test_game_engine_content_quality(self):
        """Generated content should include domain-specific rules."""
        config = _game_config()
        files = generate_files(config)
        content = files[0].content

        # Vulkan-specific
        assert "Vulkan" in content
        assert "destruction order" in content.lower() or "VkDevice" in content

        # ECS-specific
        assert "ECS" in content or "component" in content.lower()

        # General sections
        assert "## Hard Rules" in content
        assert "<!-- strawpot:meta" in content


# ---------------------------------------------------------------------------
# write_files
# ---------------------------------------------------------------------------


class TestWriteFiles:
    def test_writes_file_to_disk(self, tmp_path):
        files = [GeneratedFile(path="CLAUDE.md", content="# Test\n", rule_count=1)]
        written = write_files(files, tmp_path)
        assert len(written) == 1
        assert (tmp_path / "CLAUDE.md").read_text() == "# Test\n"

    def test_creates_parent_dirs(self, tmp_path):
        files = [GeneratedFile(path="engine/CLAUDE.md", content="# Engine\n", rule_count=1)]
        written = write_files(files, tmp_path)
        assert (tmp_path / "engine" / "CLAUDE.md").exists()

    def test_dry_run_does_not_write(self, tmp_path):
        files = [GeneratedFile(path="CLAUDE.md", content="# Test\n", rule_count=1)]
        written = write_files(files, tmp_path, dry_run=True)
        assert written == []
        assert not (tmp_path / "CLAUDE.md").exists()

    def test_skip_existing(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("original")
        files = [GeneratedFile(path="CLAUDE.md", content="# New\n", rule_count=1)]
        written = write_files(files, tmp_path, existing_actions={"CLAUDE.md": "skip"})
        assert written == []
        assert (tmp_path / "CLAUDE.md").read_text() == "original"

    def test_backup_existing(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("original")
        files = [GeneratedFile(path="CLAUDE.md", content="# New\n", rule_count=1)]
        written = write_files(files, tmp_path, existing_actions={"CLAUDE.md": "backup"})
        assert len(written) == 1
        assert (tmp_path / "CLAUDE.md").read_text() == "# New\n"
        assert (tmp_path / "CLAUDE.md.bak").read_text() == "original"

    def test_append_existing(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Existing\n")
        files = [GeneratedFile(path="CLAUDE.md", content="# Generated\n", rule_count=1)]
        written = write_files(files, tmp_path, existing_actions={"CLAUDE.md": "append"})
        assert len(written) == 1
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "# Existing" in content
        assert "<!-- strawpot:generated -->" in content
        assert "# Generated" in content

    def test_multiple_files(self, tmp_path):
        files = [
            GeneratedFile(path="engine/CLAUDE.md", content="# Engine\n", rule_count=5),
            GeneratedFile(path="server/CLAUDE.md", content="# Server\n", rule_count=3),
            GeneratedFile(path="CLAUDE.md", content="# Root\n", rule_count=0),
        ]
        written = write_files(files, tmp_path)
        assert len(written) == 3
        assert (tmp_path / "engine" / "CLAUDE.md").exists()
        assert (tmp_path / "server" / "CLAUDE.md").exists()
        assert (tmp_path / "CLAUDE.md").exists()


# ---------------------------------------------------------------------------
# CLI integration (via CliRunner)
# ---------------------------------------------------------------------------


class TestCliIntegration:
    @patch("strawpot.cli.get_strawpot_home")
    def test_init_check_flag(self, mock_home, tmp_path):
        """--check runs drift detection."""
        mock_home.return_value = tmp_path
        (tmp_path / ".first_run_done").touch()

        from click.testing import CliRunner
        from strawpot.cli import cli

        result = CliRunner().invoke(cli, ["init", "--check"])
        assert result.exit_code == 0
        assert "No CLAUDE.md" in result.output or "No drift" in result.output

    @patch("strawpot.cli.get_strawpot_home")
    @patch("strawpot.init.questionnaire.run_questionnaire")
    @patch("strawpot.init.generator.generate_files")
    @patch("strawpot.init.writer.write_files")
    def test_init_dry_run(self, mock_write, mock_gen, mock_quest, mock_home, tmp_path):
        """--dry-run calls write_files with dry_run=True."""
        mock_home.return_value = tmp_path
        (tmp_path / ".first_run_done").touch()
        mock_quest.return_value = _game_config()
        mock_gen.return_value = [
            GeneratedFile(path="engine/CLAUDE.md", content="# Engine", rule_count=10),
        ]
        mock_write.return_value = []

        from click.testing import CliRunner
        from strawpot.cli import cli

        result = CliRunner().invoke(cli, ["init", "--dry-run"])
        assert result.exit_code == 0
        mock_write.assert_called_once()
        _, kwargs = mock_write.call_args
        assert kwargs.get("dry_run") is True
