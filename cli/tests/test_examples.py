"""Tests for hand-crafted example CLAUDE.md files.

Validates examples exist, are valid Markdown, and meet rule count minimums.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _count_rules(content: str) -> int:
    """Count bullet-point rules (lines starting with '- ')."""
    # Only count rules in rule sections (Hard Rules, Soft Rules, etc.)
    in_section = False
    count = 0
    for line in content.split("\n"):
        if line.startswith("## ") and any(
            kw in line for kw in ["Hard Rules", "Soft Rules", "Cross-Component", "What NOT"]
        ):
            in_section = True
        elif line.startswith("## "):
            in_section = False
        elif in_section and line.startswith("- "):
            count += 1
    return count


class TestExampleFiles:
    def test_game_engine_exists(self):
        path = _EXAMPLES_DIR / "game-engine-cpp.claude.md"
        assert path.exists(), f"Example not found: {path}"

    def test_web_api_exists(self):
        path = _EXAMPLES_DIR / "web-api-python.claude.md"
        assert path.exists(), f"Example not found: {path}"

    def test_web_frontend_exists(self):
        path = _EXAMPLES_DIR / "web-frontend-react.claude.md"
        assert path.exists(), f"Example not found: {path}"

    def test_readme_exists(self):
        path = _EXAMPLES_DIR / "README.md"
        assert path.exists()


class TestGameEngineExample:
    @pytest.fixture()
    def content(self):
        return (_EXAMPLES_DIR / "game-engine-cpp.claude.md").read_text(encoding="utf-8")

    def test_has_at_least_23_rules(self, content):
        count = _count_rules(content)
        assert count >= 23, f"Expected ≥23 rules, got {count}"

    def test_has_inline_metadata(self, content):
        assert "<!-- strawpot:meta" in content

    def test_has_vulkan_specific_rules(self, content):
        assert "Vulkan" in content
        assert "VkDevice" in content or "VkResult" in content

    def test_has_ecs_rules(self, content):
        assert "ECS" in content
        assert "archetype" in content.lower()

    def test_has_sections(self, content):
        assert "## Hard Rules" in content
        assert "## Soft Rules" in content
        assert "## Cross-Component" in content
        assert "## Architecture Guide" in content


class TestWebApiExample:
    @pytest.fixture()
    def content(self):
        return (_EXAMPLES_DIR / "web-api-python.claude.md").read_text(encoding="utf-8")

    def test_has_at_least_18_rules(self, content):
        count = _count_rules(content)
        assert count >= 18, f"Expected ≥18 rules, got {count}"

    def test_has_security_rules(self, content):
        assert "SQL" in content or "injection" in content.lower()
        assert "JWT" in content or "auth" in content.lower()

    def test_has_sections(self, content):
        assert "## Hard Rules" in content
        assert "## Soft Rules" in content


class TestWebFrontendExample:
    @pytest.fixture()
    def content(self):
        return (_EXAMPLES_DIR / "web-frontend-react.claude.md").read_text(encoding="utf-8")

    def test_has_at_least_16_rules(self, content):
        count = _count_rules(content)
        assert count >= 16, f"Expected ≥16 rules, got {count}"

    def test_has_react_specific_rules(self, content):
        assert "React" in content
        assert "hook" in content.lower() or "Hook" in content

    def test_has_typescript_rules(self, content):
        assert "TypeScript" in content or "strict" in content

    def test_has_sections(self, content):
        assert "## Hard Rules" in content
        assert "## Soft Rules" in content
