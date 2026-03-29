"""Tests for the adaptive questionnaire."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from strawpot.init.questionnaire import (
    detect_language,
    run_questionnaire,
    suggest_component_paths,
)


# ---------------------------------------------------------------------------
# suggest_component_paths
# ---------------------------------------------------------------------------


class TestSuggestComponentPaths:
    def test_finds_cmake(self, tmp_path):
        (tmp_path / "engine").mkdir()
        (tmp_path / "engine" / "CMakeLists.txt").touch()
        result = suggest_component_paths(tmp_path)
        assert "engine" in result

    def test_finds_cargo(self, tmp_path):
        (tmp_path / "server").mkdir()
        (tmp_path / "server" / "Cargo.toml").touch()
        result = suggest_component_paths(tmp_path)
        assert "server" in result

    def test_finds_package_json(self, tmp_path):
        (tmp_path / "client").mkdir()
        (tmp_path / "client" / "package.json").touch()
        result = suggest_component_paths(tmp_path)
        assert "client" in result

    def test_respects_max_depth(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "CMakeLists.txt").touch()
        result = suggest_component_paths(tmp_path)
        assert "d" not in result

    def test_skips_hidden_dirs(self, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "CMakeLists.txt").touch()
        result = suggest_component_paths(tmp_path)
        assert ".hidden" not in result

    def test_empty_project(self, tmp_path):
        result = suggest_component_paths(tmp_path)
        assert result == {}


# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_detects_cpp(self, tmp_path):
        for name in ["main.cpp", "util.cpp", "math.hpp", "render.cc"]:
            (tmp_path / name).touch()
        assert detect_language(tmp_path) == "C++"

    def test_detects_python(self, tmp_path):
        for name in ["app.py", "models.py", "utils.py", "tests.py", "main.py"]:
            (tmp_path / name).touch()
        assert detect_language(tmp_path) == "Python"

    def test_detects_rust(self, tmp_path):
        for name in ["main.rs", "lib.rs", "utils.rs"]:
            (tmp_path / name).touch()
        assert detect_language(tmp_path) == "Rust"

    def test_detects_typescript(self, tmp_path):
        for name in ["app.ts", "index.ts", "utils.ts", "types.ts"]:
            (tmp_path / name).touch()
        assert detect_language(tmp_path) == "TypeScript"

    def test_detects_go(self, tmp_path):
        for name in ["main.go", "server.go", "handler.go"]:
            (tmp_path / name).touch()
        assert detect_language(tmp_path) == "Go"

    def test_mixed_returns_none(self, tmp_path):
        (tmp_path / "main.cpp").touch()
        (tmp_path / "app.py").touch()
        (tmp_path / "server.go").touch()
        assert detect_language(tmp_path) is None

    def test_empty_returns_none(self, tmp_path):
        assert detect_language(tmp_path) is None

    def test_skips_node_modules(self, tmp_path):
        (tmp_path / "main.py").touch()
        nm = tmp_path / "node_modules"
        nm.mkdir()
        for i in range(10):
            (nm / f"dep{i}.js").touch()
        assert detect_language(tmp_path) == "Python"


# ---------------------------------------------------------------------------
# run_questionnaire — non-interactive mode
# ---------------------------------------------------------------------------


class TestRunQuestionnaireNonInteractive:
    def test_returns_project_config(self, tmp_path):
        result = run_questionnaire(tmp_path, non_interactive=True)
        assert result.project_name == tmp_path.name
        assert result.project_type == "Other"
        assert len(result.components) >= 1

    def test_non_interactive_uses_defaults(self, tmp_path):
        result = run_questionnaire(tmp_path, non_interactive=True)
        # Should produce at least one component without prompting
        assert len(result.components) >= 1
        for comp in result.components:
            assert comp.name


# ---------------------------------------------------------------------------
# run_questionnaire — interactive mode (mocked)
# ---------------------------------------------------------------------------


class TestRunQuestionnaireInteractive:
    @patch("strawpot.init.questionnaire._ask_select")
    @patch("strawpot.init.questionnaire._ask_checkbox")
    @patch("strawpot.init.questionnaire._ask_text")
    def test_single_component_fast_path(self, mock_text, mock_checkbox, mock_select, tmp_path):
        """Single component skips selection and path questions."""
        # Q1: project type → CLI (single component by default)
        # Q4: language
        mock_select.side_effect = ["CLI", "Python"]
        mock_checkbox.return_value = ["cli"]

        result = run_questionnaire(tmp_path)
        assert result.project_type == "CLI"
        assert len(result.components) == 1
        assert result.components[0].name == "cli"
        # Path should be empty (root) for single component
        assert result.components[0].path == ""

    @patch("strawpot.init.questionnaire._ask_select")
    @patch("strawpot.init.questionnaire._ask_checkbox")
    @patch("strawpot.init.questionnaire._ask_text")
    def test_multi_component_game(self, mock_text, mock_checkbox, mock_select, tmp_path):
        """Game project with multiple components."""
        # Set up archetype so questions are asked
        mock_select.side_effect = [
            "Game",           # Q1: project type
            "C++",            # Q4: language for engine
            "Vulkan",         # Q5: render_api
            "Archetype-based",# Q5: ecs_style
            "Job system",     # Q5: threading
        ]
        mock_checkbox.return_value = ["engine"]
        mock_text.side_effect = ["engine/"]  # Q3: path for engine

        result = run_questionnaire(tmp_path)
        assert result.project_type == "Game"
        assert len(result.components) == 1
        engine = result.components[0]
        assert engine.name == "engine"
        assert engine.archetype == "game-engine"
        assert engine.archetype_answers.get("render_api") == "Vulkan"

    @patch("strawpot.init.questionnaire._ask_select")
    @patch("strawpot.init.questionnaire._ask_checkbox")
    @patch("strawpot.init.questionnaire._ask_text")
    @patch("strawpot.init.questionnaire.click.prompt")
    def test_other_fallback(self, mock_click_prompt, mock_text, mock_checkbox, mock_select, tmp_path):
        """'Other' project type uses generic flow."""
        mock_select.side_effect = ["Other", "Python"]
        mock_click_prompt.return_value = 1  # 1 component
        mock_text.side_effect = ["mylib", "lib/"]  # name, path

        result = run_questionnaire(tmp_path)
        assert result.project_type == "Other"
        assert len(result.components) == 1
        assert result.components[0].archetype == "generic"


# ---------------------------------------------------------------------------
# Existing CLAUDE.md detection
# ---------------------------------------------------------------------------


class TestExistingClaudeMd:
    def test_no_existing_file(self, tmp_path):
        from strawpot.init.questionnaire import check_existing_claude_md
        assert check_existing_claude_md(tmp_path) is None

    @patch("strawpot.init.questionnaire.click.prompt", return_value="S")
    def test_existing_file_skip(self, mock_prompt, tmp_path):
        from strawpot.init.questionnaire import check_existing_claude_md
        (tmp_path / "CLAUDE.md").write_text("existing content")
        result = check_existing_claude_md(tmp_path)
        assert result == "skip"

    @patch("strawpot.init.questionnaire.click.prompt", return_value="B")
    def test_existing_file_backup(self, mock_prompt, tmp_path):
        from strawpot.init.questionnaire import check_existing_claude_md
        (tmp_path / "CLAUDE.md").write_text("existing content")
        result = check_existing_claude_md(tmp_path)
        assert result == "backup"
