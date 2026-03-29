"""Tests for the template evaluation engine."""

from __future__ import annotations

import pytest

from strawpot.init.engine import (
    EvaluatedRule,
    InvalidTemplateCondition,
    ParsedCondition,
    UnknownConditionVariable,
    evaluate_condition,
    evaluate_rules,
    extract_interpolation_vars,
    extract_variables,
    interpolate_text,
    parse_condition,
)


# ---------------------------------------------------------------------------
# parse_condition
# ---------------------------------------------------------------------------


class TestParseCondition:
    def test_always(self):
        assert parse_condition("always") == ParsedCondition(kind="always")

    def test_equality_single_quotes(self):
        result = parse_condition("render_api == 'Vulkan'")
        assert result == ParsedCondition(kind="eq", variable="render_api", value="Vulkan")

    def test_equality_double_quotes(self):
        result = parse_condition('render_api == "Vulkan"')
        assert result == ParsedCondition(kind="eq", variable="render_api", value="Vulkan")

    def test_inequality(self):
        result = parse_condition("threading != 'Single-threaded'")
        assert result == ParsedCondition(kind="neq", variable="threading", value="Single-threaded")

    def test_has_component(self):
        result = parse_condition("has_component('server')")
        assert result == ParsedCondition(kind="has_component", value="server")

    def test_has_component_double_quotes(self):
        result = parse_condition('has_component("shared")')
        assert result == ParsedCondition(kind="has_component", value="shared")

    def test_boolean(self):
        result = parse_condition("use_ecs")
        assert result == ParsedCondition(kind="boolean", variable="use_ecs")

    def test_whitespace_stripped(self):
        result = parse_condition("  always  ")
        assert result == ParsedCondition(kind="always")

    def test_malformed_raises(self):
        with pytest.raises(InvalidTemplateCondition):
            parse_condition("render_api === 'Vulkan'")

    def test_empty_raises(self):
        with pytest.raises(InvalidTemplateCondition):
            parse_condition("")

    def test_and_or_not_supported(self):
        with pytest.raises(InvalidTemplateCondition):
            parse_condition("render_api == 'Vulkan' AND use_ecs")


# ---------------------------------------------------------------------------
# evaluate_condition
# ---------------------------------------------------------------------------


class TestEvaluateCondition:
    def test_always(self):
        assert evaluate_condition("always", {}) is True

    def test_eq_match(self):
        assert evaluate_condition("render_api == 'Vulkan'", {"render_api": "Vulkan"}) is True

    def test_eq_no_match(self):
        assert evaluate_condition("render_api == 'Vulkan'", {"render_api": "OpenGL"}) is False

    def test_eq_missing_key(self):
        assert evaluate_condition("render_api == 'Vulkan'", {}) is False

    def test_neq_match(self):
        assert evaluate_condition(
            "threading != 'Single-threaded'",
            {"threading": "Job system"},
        ) is True

    def test_neq_no_match(self):
        assert evaluate_condition(
            "threading != 'Single-threaded'",
            {"threading": "Single-threaded"},
        ) is False

    def test_neq_missing_key(self):
        # None != "Single-threaded" → True
        assert evaluate_condition("threading != 'Single-threaded'", {}) is True

    def test_has_component_present(self):
        ctx = {"components": ["server", "client"]}
        assert evaluate_condition("has_component('server')", {}, ctx) is True

    def test_has_component_absent(self):
        ctx = {"components": ["client"]}
        assert evaluate_condition("has_component('server')", {}, ctx) is False

    def test_has_component_no_context(self):
        assert evaluate_condition("has_component('server')", {}) is False

    def test_boolean_true(self):
        assert evaluate_condition("use_ecs", {"use_ecs": True}) is True

    def test_boolean_false(self):
        assert evaluate_condition("use_ecs", {"use_ecs": False}) is False

    def test_boolean_missing(self):
        assert evaluate_condition("use_ecs", {}) is False

    def test_boolean_truthy_string(self):
        assert evaluate_condition("use_ecs", {"use_ecs": "yes"}) is True


# ---------------------------------------------------------------------------
# evaluate_rules
# ---------------------------------------------------------------------------


class TestEvaluateRules:
    @pytest.fixture()
    def sample_template(self):
        return {
            "rules": {
                "hard": [
                    {"condition": "always", "text": "Always rule"},
                    {"condition": "render_api == 'Vulkan'", "text": "Vulkan rule"},
                    {"condition": "render_api == 'OpenGL'", "text": "OpenGL rule"},
                ],
                "soft": [
                    {"condition": "use_ecs", "text": "ECS rule"},
                ],
            },
            "cross_component": [
                {"condition": "has_component('server')", "text": "Server cross-ref"},
            ],
        }

    def test_filters_by_condition(self, sample_template):
        answers = {"render_api": "Vulkan", "use_ecs": True}
        ctx = {"components": ["server"]}
        result = evaluate_rules(sample_template, answers, ctx)

        texts = [r.text for r in result]
        assert "Always rule" in texts
        assert "Vulkan rule" in texts
        assert "OpenGL rule" not in texts
        assert "ECS rule" in texts
        assert "Server cross-ref" in texts

    def test_sections_are_labelled(self, sample_template):
        answers = {"render_api": "Vulkan", "use_ecs": True}
        ctx = {"components": ["server"]}
        result = evaluate_rules(sample_template, answers, ctx)

        sections = {r.text: r.section for r in result}
        assert sections["Always rule"] == "hard"
        assert sections["Vulkan rule"] == "hard"
        assert sections["ECS rule"] == "soft"
        assert sections["Server cross-ref"] == "cross_component"

    def test_order_hard_then_soft_then_cross(self, sample_template):
        answers = {"render_api": "Vulkan", "use_ecs": True}
        ctx = {"components": ["server"]}
        result = evaluate_rules(sample_template, answers, ctx)

        section_order = [r.section for r in result]
        # Hard rules come first, then soft, then cross_component
        hard_end = max(i for i, s in enumerate(section_order) if s == "hard")
        soft_start = min(i for i, s in enumerate(section_order) if s == "soft")
        cross_start = min(i for i, s in enumerate(section_order) if s == "cross_component")
        assert hard_end < soft_start < cross_start

    def test_empty_template(self):
        result = evaluate_rules({}, {})
        assert result == []

    def test_no_matching_rules(self, sample_template):
        answers = {"render_api": "Metal", "use_ecs": False}
        ctx = {"components": []}
        result = evaluate_rules(sample_template, answers, ctx)

        texts = [r.text for r in result]
        assert texts == ["Always rule"]


# ---------------------------------------------------------------------------
# interpolate_text
# ---------------------------------------------------------------------------


class TestInterpolateText:
    def test_no_variables(self):
        assert interpolate_text("No vars here", {}) == "No vars here"

    def test_component_path(self):
        ctx = {"component": {"path": "engine/", "name": "engine", "language": "C++"}}
        result = interpolate_text("Build {{component.path}} first", {}, ctx)
        assert result == "Build engine/ first"

    def test_multiple_variables(self):
        ctx = {
            "component": {"name": "engine", "language": "C++", "path": "engine/"},
            "project": {"name": "MyGame"},
        }
        result = interpolate_text(
            "{{component.name}} ({{component.language}}) in {{project.name}}",
            {},
            ctx,
        )
        assert result == "engine (C++) in MyGame"

    def test_shared_path(self):
        ctx = {"shared": {"path": "shared/"}}
        result = interpolate_text("Modify {{shared.path}}/*.proto", {}, ctx)
        assert result == "Modify shared//*.proto"

    def test_unknown_variable_raises(self):
        with pytest.raises(UnknownConditionVariable, match="unknown_var"):
            interpolate_text("{{unknown_var}}", {})

    def test_project_name(self):
        ctx = {"project": {"name": "TestProject"}}
        result = interpolate_text("Welcome to {{project.name}}", {}, ctx)
        assert result == "Welcome to TestProject"


# ---------------------------------------------------------------------------
# extract_variables
# ---------------------------------------------------------------------------


class TestExtractVariables:
    def test_always(self):
        assert extract_variables("always") == set()

    def test_eq(self):
        assert extract_variables("render_api == 'Vulkan'") == {"render_api"}

    def test_neq(self):
        assert extract_variables("threading != 'Single-threaded'") == {"threading"}

    def test_has_component(self):
        assert extract_variables("has_component('server')") == set()

    def test_boolean(self):
        assert extract_variables("use_ecs") == {"use_ecs"}


# ---------------------------------------------------------------------------
# extract_interpolation_vars
# ---------------------------------------------------------------------------


class TestExtractInterpolationVars:
    def test_no_vars(self):
        assert extract_interpolation_vars("No vars here") == set()

    def test_single_var(self):
        assert extract_interpolation_vars("{{component.path}}/foo") == {"component.path"}

    def test_multiple_vars(self):
        result = extract_interpolation_vars("{{component.name}} uses {{component.language}}")
        assert result == {"component.name", "component.language"}

    def test_all_valid_vars(self):
        text = "{{component.name}} {{component.language}} {{component.path}} {{shared.path}} {{project.name}}"
        result = extract_interpolation_vars(text)
        assert len(result) == 5
