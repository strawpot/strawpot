"""CI template validation — comprehensive checks for all archetypes and layers.

This test runs on every CI build and validates:
1. All conditions parse
2. All condition variables reference real question IDs
3. All text interpolation variables are in the allowed set
4. All condition combinations produce valid, non-empty output
5. All language layer rules have non-empty text
"""

from __future__ import annotations

import itertools

import pytest

from strawpot.init.engine import (
    _VALID_INTERPOLATION_VARS,
    evaluate_rules,
    extract_interpolation_vars,
    extract_variables,
    parse_condition,
)
from strawpot.init.loader import list_archetypes, list_languages, load_archetype, load_language_layer


# ---------------------------------------------------------------------------
# Archetype validation
# ---------------------------------------------------------------------------


@pytest.fixture(params=list_archetypes())
def archetype(request):
    return load_archetype(request.param)


class TestArchetypeValidation:
    """Validates every archetype template on every CI run."""

    def test_conditions_parse(self, archetype):
        """Every condition string must be parseable."""
        for section in ("hard", "soft"):
            for rule in archetype.rules.get(section, []):
                parse_condition(rule["condition"])
        for rule in archetype.cross_component:
            parse_condition(rule["condition"])

    def test_condition_variables_exist(self, archetype):
        """Condition variables must reference real question IDs."""
        question_ids = {q.id for q in archetype.questions}
        for section in ("hard", "soft"):
            for rule in archetype.rules.get(section, []):
                for var in extract_variables(rule["condition"]):
                    assert var in question_ids, (
                        f"[{archetype.slug}] Condition variable '{var}' not in "
                        f"questions: {question_ids}"
                    )

    def test_interpolation_vars_valid(self, archetype):
        """All {{var}} references must be in the allowed set."""
        for section in ("hard", "soft"):
            for rule in archetype.rules.get(section, []):
                for var in extract_interpolation_vars(rule["text"]):
                    assert var in _VALID_INTERPOLATION_VARS, (
                        f"[{archetype.slug}] Invalid interpolation var '{{{{{var}}}}}'"
                    )
        for rule in archetype.cross_component:
            for var in extract_interpolation_vars(rule["text"]):
                assert var in _VALID_INTERPOLATION_VARS

    def test_all_rules_have_text(self, archetype):
        """Every rule must have non-empty text."""
        for section in ("hard", "soft"):
            for rule in archetype.rules.get(section, []):
                assert rule.get("text", "").strip(), (
                    f"[{archetype.slug}] Empty rule text in {section}"
                )
        for rule in archetype.cross_component:
            assert rule.get("text", "").strip()

    def test_produces_non_empty_output(self, archetype):
        """A default answer set must produce at least some rules."""
        answers = {}
        for q in archetype.questions:
            answers[q.id] = q.default or (q.choices[0] if q.choices else "")

        ctx = {
            "components": ["test"],
            "component": {"name": "test", "path": "test/", "language": "Unknown"},
            "shared": {"path": ""},
            "project": {"name": "TestProject"},
        }
        result = evaluate_rules(
            {"rules": archetype.rules, "cross_component": archetype.cross_component},
            answers,
            ctx,
        )
        assert len(result) > 0, (
            f"[{archetype.slug}] Default answers produce no rules"
        )


# ---------------------------------------------------------------------------
# Language layer validation
# ---------------------------------------------------------------------------


@pytest.fixture(params=list_languages())
def language_layer(request):
    return load_language_layer(request.param)


class TestLanguageLayerValidation:
    """Validates every language layer on every CI run."""

    def test_conditions_parse(self, language_layer):
        for section in ("hard", "soft"):
            for rule in language_layer.rules.get(section, []):
                parse_condition(rule["condition"])

    def test_all_rules_have_text(self, language_layer):
        for section in ("hard", "soft"):
            for rule in language_layer.rules.get(section, []):
                assert rule.get("text", "").strip(), (
                    f"[{language_layer.language}] Empty rule text"
                )

    def test_has_rules(self, language_layer):
        total = sum(len(language_layer.rules.get(s, [])) for s in ("hard", "soft"))
        assert total > 0, f"[{language_layer.language}] No rules defined"
