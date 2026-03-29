"""Tests for the YAML template loader."""

from __future__ import annotations

import pytest
import yaml

from strawpot.init.loader import (
    list_archetypes,
    list_languages,
    load_archetype,
    load_language_layer,
)


@pytest.fixture()
def archetype_dir(tmp_path, monkeypatch):
    """Set up a temporary archetypes directory with a test template."""
    archetypes = tmp_path / "archetypes"
    archetypes.mkdir()
    monkeypatch.setattr("strawpot.init.loader._ARCHETYPES_DIR", archetypes)

    # Create a minimal archetype
    game_engine = archetypes / "game-engine"
    game_engine.mkdir()
    template = {
        "name": "Game Engine",
        "languages": ["C++", "Rust"],
        "build_systems": ["CMake", "Meson"],
        "questions": [
            {
                "id": "render_api",
                "question": "Which rendering API?",
                "choices": ["Vulkan", "OpenGL"],
                "default": "Vulkan",
                "affects": ["hard_rules"],
            },
        ],
        "rules": {
            "hard": [
                {"condition": "always", "text": "No raw new/delete."},
                {"condition": "render_api == 'Vulkan'", "text": "Vulkan destruction order."},
            ],
            "soft": [
                {"condition": "always", "text": "PascalCase for types."},
            ],
        },
        "cross_component": [
            {"condition": "has_component('server')", "text": "Server has authority."},
        ],
    }
    (game_engine / "template.yaml").write_text(
        yaml.dump(template, default_flow_style=False),
        encoding="utf-8",
    )
    return archetypes


@pytest.fixture()
def layers_dir(tmp_path, monkeypatch):
    """Set up a temporary layers directory."""
    layers = tmp_path / "layers"
    layers.mkdir()
    monkeypatch.setattr("strawpot.init.loader._LAYERS_DIR", layers)

    layer = {
        "language": "C++",
        "rules": {
            "hard": [
                {"condition": "always", "text": "Use RAII for resource management."},
            ],
            "soft": [
                {"condition": "always", "text": "Prefer constexpr where possible."},
            ],
        },
    }
    (layers / "cpp.yaml").write_text(
        yaml.dump(layer, default_flow_style=False),
        encoding="utf-8",
    )
    return layers


class TestLoadArchetype:
    def test_loads_template(self, archetype_dir):
        result = load_archetype("game-engine")
        assert result.name == "Game Engine"
        assert result.slug == "game-engine"
        assert "C++" in result.languages
        assert "CMake" in result.build_systems

    def test_loads_questions(self, archetype_dir):
        result = load_archetype("game-engine")
        assert len(result.questions) == 1
        q = result.questions[0]
        assert q.id == "render_api"
        assert q.choices == ["Vulkan", "OpenGL"]
        assert q.default == "Vulkan"

    def test_loads_rules(self, archetype_dir):
        result = load_archetype("game-engine")
        assert len(result.rules["hard"]) == 2
        assert len(result.rules["soft"]) == 1
        assert len(result.cross_component) == 1

    def test_not_found_raises(self, archetype_dir):
        with pytest.raises(FileNotFoundError):
            load_archetype("nonexistent")


class TestLoadLanguageLayer:
    def test_loads_layer(self, layers_dir):
        result = load_language_layer("cpp")
        assert result.language == "C++"
        assert len(result.rules["hard"]) == 1
        assert len(result.rules["soft"]) == 1

    def test_not_found_raises(self, layers_dir):
        with pytest.raises(FileNotFoundError):
            load_language_layer("nonexistent")


class TestListArchetypes:
    def test_lists_available(self, archetype_dir):
        result = list_archetypes()
        assert "game-engine" in result

    def test_empty_when_no_templates(self, tmp_path, monkeypatch):
        monkeypatch.setattr("strawpot.init.loader._ARCHETYPES_DIR", tmp_path / "empty")
        assert list_archetypes() == []


class TestListLanguages:
    def test_lists_available(self, layers_dir):
        result = list_languages()
        assert "cpp" in result

    def test_empty_when_no_layers(self, tmp_path, monkeypatch):
        monkeypatch.setattr("strawpot.init.loader._LAYERS_DIR", tmp_path / "empty")
        assert list_languages() == []
