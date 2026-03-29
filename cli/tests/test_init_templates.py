"""Tests for archetype templates and language layers.

Validates template integrity: conditions parse, variables exist, interpolation
vars are in the allowed set, and all condition combinations produce valid output.
"""

from __future__ import annotations

import itertools

import pytest

from strawpot.init.engine import (
    evaluate_rules,
    extract_interpolation_vars,
    extract_variables,
    parse_condition,
)
from strawpot.init.loader import load_archetype, load_language_layer


# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------


class TestGameEngineTemplate:
    @pytest.fixture()
    def template(self):
        return load_archetype("game-engine")

    def test_loads_successfully(self, template):
        assert template.name == "Game Engine"
        assert template.slug == "game-engine"

    def test_has_questions(self, template):
        ids = {q.id for q in template.questions}
        assert ids == {"render_api", "ecs_style", "threading"}

    def test_all_conditions_parse(self, template):
        """Every condition string in the template must be parseable."""
        for section in ("hard", "soft"):
            for rule in template.rules.get(section, []):
                parse_condition(rule["condition"])
        for rule in template.cross_component:
            parse_condition(rule["condition"])

    def test_condition_variables_reference_questions(self, template):
        """Condition variables must reference question IDs or be builtins."""
        question_ids = {q.id for q in template.questions}
        for section in ("hard", "soft"):
            for rule in template.rules.get(section, []):
                for var in extract_variables(rule["condition"]):
                    assert var in question_ids, (
                        f"Condition variable '{var}' not in questions: {question_ids}"
                    )

    def test_interpolation_vars_are_valid(self, template):
        """All {{var}} references must be in the allowed set."""
        from strawpot.init.engine import _VALID_INTERPOLATION_VARS

        for section in ("hard", "soft"):
            for rule in template.rules.get(section, []):
                for var in extract_interpolation_vars(rule["text"]):
                    assert var in _VALID_INTERPOLATION_VARS, (
                        f"Invalid interpolation var '{{{{var}}}}' in rule: {rule['text']}"
                    )
        for rule in template.cross_component:
            for var in extract_interpolation_vars(rule["text"]):
                assert var in _VALID_INTERPOLATION_VARS

    def test_produces_at_least_23_rules(self, template):
        """Full answer set should produce ≥23 rules."""
        answers = {
            "render_api": "Vulkan",
            "ecs_style": "Archetype-based",
            "threading": "Job system",
        }
        ctx = {
            "components": ["engine", "server", "client", "shared"],
            "component": {"name": "engine", "path": "engine/", "language": "C++"},
            "shared": {"path": "shared/"},
            "project": {"name": "TestGame"},
        }
        result = evaluate_rules(
            {"rules": template.rules, "cross_component": template.cross_component},
            answers,
            ctx,
        )
        assert len(result) >= 23, f"Expected ≥23 rules, got {len(result)}"

    @pytest.mark.parametrize(
        "render_api,ecs_style,threading",
        list(
            itertools.product(
                ["Vulkan", "DirectX 12", "OpenGL", "Metal", "Custom"],
                ["Archetype-based", "Sparse set", "No ECS"],
                ["Job system", "Thread-per-subsystem", "Single-threaded"],
            )
        ),
    )
    def test_all_condition_combinations(self, template, render_api, ecs_style, threading):
        """Every condition combination must produce valid output (no exceptions)."""
        answers = {
            "render_api": render_api,
            "ecs_style": ecs_style,
            "threading": threading,
        }
        ctx = {
            "components": ["engine"],
            "component": {"name": "engine", "path": "engine/", "language": "C++"},
            "shared": {"path": ""},
            "project": {"name": "TestGame"},
        }
        result = evaluate_rules(
            {"rules": template.rules, "cross_component": template.cross_component},
            answers,
            ctx,
        )
        # Always-true rules should always be present
        assert len(result) >= 10, f"Expected ≥10 rules for {answers}, got {len(result)}"


class TestWebApiTemplate:
    @pytest.fixture()
    def template(self):
        return load_archetype("web-api")

    def test_loads_successfully(self, template):
        assert template.name == "Web API"
        assert template.slug == "web-api"

    def test_has_questions(self, template):
        ids = {q.id for q in template.questions}
        assert ids == {"framework", "database", "api_style", "auth"}

    def test_all_conditions_parse(self, template):
        for section in ("hard", "soft"):
            for rule in template.rules.get(section, []):
                parse_condition(rule["condition"])
        for rule in template.cross_component:
            parse_condition(rule["condition"])

    def test_condition_variables_reference_questions(self, template):
        question_ids = {q.id for q in template.questions}
        for section in ("hard", "soft"):
            for rule in template.rules.get(section, []):
                for var in extract_variables(rule["condition"]):
                    assert var in question_ids

    def test_interpolation_vars_are_valid(self, template):
        from strawpot.init.engine import _VALID_INTERPOLATION_VARS

        for section in ("hard", "soft"):
            for rule in template.rules.get(section, []):
                for var in extract_interpolation_vars(rule["text"]):
                    assert var in _VALID_INTERPOLATION_VARS
        for rule in template.cross_component:
            for var in extract_interpolation_vars(rule["text"]):
                assert var in _VALID_INTERPOLATION_VARS

    def test_produces_at_least_15_rules(self, template):
        answers = {
            "framework": "FastAPI",
            "database": "PostgreSQL",
            "api_style": "REST",
            "auth": "JWT",
        }
        ctx = {
            "components": ["api", "client", "shared"],
            "component": {"name": "api", "path": "api/", "language": "Python"},
            "shared": {"path": "shared/"},
            "project": {"name": "TestAPI"},
        }
        result = evaluate_rules(
            {"rules": template.rules, "cross_component": template.cross_component},
            answers,
            ctx,
        )
        assert len(result) >= 15, f"Expected ≥15 rules, got {len(result)}"


# ---------------------------------------------------------------------------
# Language layers
# ---------------------------------------------------------------------------


class TestGameServerTemplate:
    @pytest.fixture()
    def template(self):
        return load_archetype("game-server")

    def test_loads_successfully(self, template):
        assert template.name == "Game Server"
        assert template.slug == "game-server"

    def test_has_questions(self, template):
        ids = {q.id for q in template.questions}
        assert ids == {"networking", "state_management", "concurrency"}

    def test_all_conditions_parse(self, template):
        for section in ("hard", "soft"):
            for rule in template.rules.get(section, []):
                parse_condition(rule["condition"])
        for rule in template.cross_component:
            parse_condition(rule["condition"])

    def test_condition_variables_reference_questions(self, template):
        question_ids = {q.id for q in template.questions}
        for section in ("hard", "soft"):
            for rule in template.rules.get(section, []):
                for var in extract_variables(rule["condition"]):
                    assert var in question_ids

    def test_produces_at_least_15_rules(self, template):
        answers = {
            "networking": "TCP",
            "state_management": "In-memory",
            "concurrency": "Async",
        }
        ctx = {
            "components": ["server", "engine", "client", "shared"],
            "component": {"name": "server", "path": "server/", "language": "Rust"},
            "shared": {"path": "shared/"},
            "project": {"name": "TestGame"},
        }
        result = evaluate_rules(
            {"rules": template.rules, "cross_component": template.cross_component},
            answers,
            ctx,
        )
        assert len(result) >= 15, f"Expected ≥15 rules, got {len(result)}"


class TestGameClientTemplate:
    @pytest.fixture()
    def template(self):
        return load_archetype("game-client")

    def test_loads_successfully(self, template):
        assert template.name == "Game Client"
        assert template.slug == "game-client"

    def test_has_questions(self, template):
        ids = {q.id for q in template.questions}
        assert ids == {"ui_framework", "asset_pipeline", "platform"}

    def test_all_conditions_parse(self, template):
        for section in ("hard", "soft"):
            for rule in template.rules.get(section, []):
                parse_condition(rule["condition"])
        for rule in template.cross_component:
            parse_condition(rule["condition"])

    def test_condition_variables_reference_questions(self, template):
        question_ids = {q.id for q in template.questions}
        for section in ("hard", "soft"):
            for rule in template.rules.get(section, []):
                for var in extract_variables(rule["condition"]):
                    assert var in question_ids

    def test_produces_at_least_15_rules(self, template):
        answers = {
            "ui_framework": "React",
            "asset_pipeline": "Vite",
            "platform": "Web",
        }
        ctx = {
            "components": ["client", "server", "engine", "shared"],
            "component": {"name": "client", "path": "client/", "language": "TypeScript"},
            "shared": {"path": "shared/"},
            "project": {"name": "TestGame"},
        }
        result = evaluate_rules(
            {"rules": template.rules, "cross_component": template.cross_component},
            answers,
            ctx,
        )
        assert len(result) >= 15, f"Expected ≥15 rules, got {len(result)}"


class TestGenericTemplate:
    @pytest.fixture()
    def template(self):
        return load_archetype("generic")

    def test_loads_successfully(self, template):
        assert template.name == "Generic"
        assert template.slug == "generic"

    def test_no_questions(self, template):
        assert template.questions == []

    def test_all_conditions_parse(self, template):
        for section in ("hard", "soft"):
            for rule in template.rules.get(section, []):
                parse_condition(rule["condition"])

    def test_produces_at_least_10_rules(self, template):
        result = evaluate_rules(
            {"rules": template.rules, "cross_component": template.cross_component},
            {},
            {"components": [], "component": {"name": "lib", "path": "lib/", "language": "Python"},
             "project": {"name": "Test"}},
        )
        assert len(result) >= 10, f"Expected ≥10 rules, got {len(result)}"


# ---------------------------------------------------------------------------
# Language layers
# ---------------------------------------------------------------------------


class TestCppLayer:
    def test_loads_successfully(self):
        layer = load_language_layer("cpp")
        assert layer.language == "C++"

    def test_has_at_least_8_rules(self):
        layer = load_language_layer("cpp")
        total = sum(len(layer.rules.get(s, [])) for s in ("hard", "soft"))
        assert total >= 8, f"Expected ≥8 rules, got {total}"

    def test_all_conditions_parse(self):
        layer = load_language_layer("cpp")
        for section in ("hard", "soft"):
            for rule in layer.rules.get(section, []):
                parse_condition(rule["condition"])


class TestPythonLayer:
    def test_loads_successfully(self):
        layer = load_language_layer("python")
        assert layer.language == "Python"

    def test_has_at_least_8_rules(self):
        layer = load_language_layer("python")
        total = sum(len(layer.rules.get(s, [])) for s in ("hard", "soft"))
        assert total >= 8, f"Expected ≥8 rules, got {total}"

    def test_all_conditions_parse(self):
        layer = load_language_layer("python")
        for section in ("hard", "soft"):
            for rule in layer.rules.get(section, []):
                parse_condition(rule["condition"])


class TestRustLayer:
    def test_loads_successfully(self):
        layer = load_language_layer("rust")
        assert layer.language == "Rust"

    def test_has_at_least_8_rules(self):
        layer = load_language_layer("rust")
        total = sum(len(layer.rules.get(s, [])) for s in ("hard", "soft"))
        assert total >= 8, f"Expected ≥8 rules, got {total}"

    def test_all_conditions_parse(self):
        layer = load_language_layer("rust")
        for section in ("hard", "soft"):
            for rule in layer.rules.get(section, []):
                parse_condition(rule["condition"])


class TestTypescriptLayer:
    def test_loads_successfully(self):
        layer = load_language_layer("typescript")
        assert layer.language == "TypeScript"

    def test_has_at_least_8_rules(self):
        layer = load_language_layer("typescript")
        total = sum(len(layer.rules.get(s, [])) for s in ("hard", "soft"))
        assert total >= 8, f"Expected ≥8 rules, got {total}"

    def test_all_conditions_parse(self):
        layer = load_language_layer("typescript")
        for section in ("hard", "soft"):
            for rule in layer.rules.get(section, []):
                parse_condition(rule["condition"])


class TestGoLayer:
    def test_loads_successfully(self):
        layer = load_language_layer("go")
        assert layer.language == "Go"

    def test_has_at_least_8_rules(self):
        layer = load_language_layer("go")
        total = sum(len(layer.rules.get(s, [])) for s in ("hard", "soft"))
        assert total >= 8, f"Expected ≥8 rules, got {total}"

    def test_all_conditions_parse(self):
        layer = load_language_layer("go")
        for section in ("hard", "soft"):
            for rule in layer.rules.get(section, []):
                parse_condition(rule["condition"])
