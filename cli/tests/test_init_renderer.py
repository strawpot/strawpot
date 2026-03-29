"""Tests for the Markdown renderer."""

from __future__ import annotations

from strawpot.init.renderer import (
    render_component_claude_md,
    render_inline_metadata,
    render_root_claude_md,
)
from strawpot.init.types import (
    ArchetypeTemplate,
    ComponentConfig,
    LanguageLayer,
    ProjectConfig,
)


def _make_project(**overrides) -> ProjectConfig:
    defaults = {
        "project_name": "TestProject",
        "project_type": "game",
        "components": [],
    }
    defaults.update(overrides)
    return ProjectConfig(**defaults)


def _make_component(**overrides) -> ComponentConfig:
    defaults = {
        "name": "engine",
        "path": "engine/",
        "language": "C++",
        "build_system": "CMake",
        "archetype": "game-engine",
        "archetype_answers": {},
    }
    defaults.update(overrides)
    return ComponentConfig(**defaults)


def _make_archetype(**overrides) -> ArchetypeTemplate:
    defaults = {
        "name": "Game Engine",
        "slug": "game-engine",
        "languages": ["C++"],
        "build_systems": ["CMake"],
        "questions": [],
        "rules": {
            "hard": [
                {"condition": "always", "text": "No raw new/delete."},
            ],
            "soft": [
                {"condition": "always", "text": "PascalCase for types."},
            ],
        },
        "cross_component": [],
    }
    defaults.update(overrides)
    return ArchetypeTemplate(**defaults)


def _make_language_layer(**overrides) -> LanguageLayer:
    defaults = {
        "language": "C++",
        "rules": {
            "hard": [
                {"condition": "always", "text": "Use RAII."},
            ],
        },
    }
    defaults.update(overrides)
    return LanguageLayer(**defaults)


class TestRenderInlineMetadata:
    def test_basic_metadata(self):
        component = _make_component()
        result = render_inline_metadata(component, rule_count=5)
        assert "<!-- strawpot:meta" in result
        assert "-->" in result
        assert "archetype: game-engine" in result
        assert "language: C++" in result
        assert "component: engine" in result
        assert "rule_count: 5" in result

    def test_with_dirs_and_hash(self):
        component = _make_component()
        result = render_inline_metadata(
            component, rule_count=3,
            dirs_at_gen=["src", "include"],
            build_file_hash="abc123",
        )
        assert "dirs_at_gen: [src, include]" in result
        assert "build_file_hash: abc123" in result


class TestRenderComponentClaudeMd:
    def test_has_all_sections(self):
        component = _make_component()
        project = _make_project(components=[component])
        archetype = _make_archetype()

        result = render_component_claude_md(component, project, archetype)
        assert "# engine" in result.content
        assert "## Build Commands" in result.content
        assert "## Hard Rules" in result.content
        assert "## Soft Rules" in result.content
        assert "## Architecture Guide" in result.content
        assert "## Project-Specific Rules" in result.content

    def test_identity_section(self):
        component = _make_component()
        project = _make_project(components=[component])
        archetype = _make_archetype()

        result = render_component_claude_md(component, project, archetype)
        assert "**engine** component of TestProject" in result.content
        assert "C++" in result.content

    def test_includes_hard_rules(self):
        component = _make_component()
        project = _make_project(components=[component])
        archetype = _make_archetype()

        result = render_component_claude_md(component, project, archetype)
        assert "No raw new/delete." in result.content

    def test_includes_soft_rules(self):
        component = _make_component()
        project = _make_project(components=[component])
        archetype = _make_archetype()

        result = render_component_claude_md(component, project, archetype)
        assert "PascalCase for types." in result.content

    def test_four_layer_composition(self):
        """Language + archetype hard + archetype soft + cross_component."""
        server = _make_component(name="server", path="server/")
        component = _make_component()
        project = _make_project(components=[component, server])
        archetype = _make_archetype(
            cross_component=[
                {"condition": "has_component('server')", "text": "Server is authority."},
            ],
        )
        lang_layer = _make_language_layer()

        result = render_component_claude_md(component, project, archetype, lang_layer)
        # Language layer
        assert "Use RAII." in result.content
        assert "## Language Conventions" in result.content
        # Archetype hard
        assert "No raw new/delete." in result.content
        # Archetype soft
        assert "PascalCase for types." in result.content
        # Cross-component
        assert "Server is authority." in result.content
        assert "## Cross-Component Awareness" in result.content

    def test_inline_metadata_present(self):
        component = _make_component()
        project = _make_project(components=[component])
        archetype = _make_archetype()

        result = render_component_claude_md(component, project, archetype)
        assert "<!-- strawpot:meta" in result.content

    def test_generated_file_path(self):
        component = _make_component(path="engine/")
        project = _make_project(components=[component])
        archetype = _make_archetype()

        result = render_component_claude_md(component, project, archetype)
        assert result.path == "engine/CLAUDE.md"

    def test_rule_count(self):
        component = _make_component()
        project = _make_project(components=[component])
        archetype = _make_archetype()

        result = render_component_claude_md(component, project, archetype)
        # 1 hard + 1 soft = 2 rules
        assert result.rule_count == 2

    def test_conditional_rules(self):
        component = _make_component(
            archetype_answers={"render_api": "Vulkan"},
        )
        project = _make_project(components=[component])
        archetype = _make_archetype(
            rules={
                "hard": [
                    {"condition": "render_api == 'Vulkan'", "text": "Vulkan order."},
                    {"condition": "render_api == 'OpenGL'", "text": "GL context."},
                ],
                "soft": [],
            },
        )

        result = render_component_claude_md(component, project, archetype)
        assert "Vulkan order." in result.content
        assert "GL context." not in result.content


class TestRenderRootClaudeMd:
    def test_basic_root(self):
        project = _make_project(
            components=[
                _make_component(name="engine", path="engine/", language="C++"),
                _make_component(name="server", path="server/", language="Rust"),
            ],
        )
        result = render_root_claude_md(project)

        assert result.path == "CLAUDE.md"
        assert "# TestProject" in result.content
        assert "game" in result.content
        assert "**engine**" in result.content
        assert "**server**" in result.content
        assert "`engine/`" in result.content
        assert "C++" in result.content
        assert "Rust" in result.content

    def test_no_components(self):
        project = _make_project(components=[])
        result = render_root_claude_md(project)
        assert "## Components" not in result.content

    def test_cross_component_section(self):
        project = _make_project()
        result = render_root_claude_md(project)
        assert "## Cross-Component Guidelines" in result.content
