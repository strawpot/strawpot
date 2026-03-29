"""Template evaluation engine — condition parser and rule evaluator.

The condition language is intentionally minimal: equality, inequality,
presence checks, boolean flags, and ``always``.  No AND/OR — if you need
both, write two rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidTemplateCondition(Exception):
    """Raised when a condition string cannot be parsed."""


class UnknownConditionVariable(Exception):
    """Raised when a condition references an undefined variable."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedCondition:
    """Structured representation of a single condition."""

    kind: str  # "always", "eq", "neq", "has_component", "boolean"
    variable: str | None = None
    value: str | None = None


@dataclass
class EvaluatedRule:
    """A rule whose condition matched, with its origin section."""

    text: str
    section: str  # "hard", "soft", "cross_component"


# ---------------------------------------------------------------------------
# Condition parsing
# ---------------------------------------------------------------------------

_EQ_RE = re.compile(r'^(\w+)\s*==\s*["\'](.+?)["\']$')
_NEQ_RE = re.compile(r'^(\w+)\s*!=\s*["\'](.+?)["\']$')
_HAS_COMPONENT_RE = re.compile(r'^has_component\(\s*["\'](\w+)["\']\s*\)$')
_BOOLEAN_RE = re.compile(r'^(\w+)$')


def parse_condition(condition: str) -> ParsedCondition:
    """Parse a condition string into a :class:`ParsedCondition`.

    Supported forms::

        "always"
        "render_api == 'Vulkan'"
        "threading != 'Single-threaded'"
        "has_component('server')"
        "use_ecs"                          # truthy check

    Raises :class:`InvalidTemplateCondition` for unrecognised syntax.
    """
    condition = condition.strip()

    if condition == "always":
        return ParsedCondition(kind="always")

    m = _EQ_RE.match(condition)
    if m:
        return ParsedCondition(kind="eq", variable=m.group(1), value=m.group(2))

    m = _NEQ_RE.match(condition)
    if m:
        return ParsedCondition(kind="neq", variable=m.group(1), value=m.group(2))

    m = _HAS_COMPONENT_RE.match(condition)
    if m:
        return ParsedCondition(kind="has_component", value=m.group(1))

    m = _BOOLEAN_RE.match(condition)
    if m:
        return ParsedCondition(kind="boolean", variable=m.group(1))

    raise InvalidTemplateCondition(f"Cannot parse condition: {condition!r}")


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------


def evaluate_condition(
    condition: str,
    answers: dict[str, Any],
    project_context: dict[str, Any] | None = None,
) -> bool:
    """Evaluate a condition string against *answers* and *project_context*.

    *project_context* must contain a ``"components"`` key (list of component
    names) for ``has_component`` conditions to work.
    """
    if project_context is None:
        project_context = {}

    parsed = parse_condition(condition)

    if parsed.kind == "always":
        return True

    if parsed.kind == "eq":
        assert parsed.variable is not None
        return answers.get(parsed.variable) == parsed.value

    if parsed.kind == "neq":
        assert parsed.variable is not None
        return answers.get(parsed.variable) != parsed.value

    if parsed.kind == "has_component":
        components = project_context.get("components", [])
        return parsed.value in components

    if parsed.kind == "boolean":
        assert parsed.variable is not None
        return bool(answers.get(parsed.variable))

    raise InvalidTemplateCondition(f"Unknown condition kind: {parsed.kind!r}")


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------


def evaluate_rules(
    template: dict[str, Any],
    answers: dict[str, Any],
    project_context: dict[str, Any] | None = None,
) -> list[EvaluatedRule]:
    """Evaluate all rules in *template* and return those whose conditions match.

    The template dict is expected to have::

        {"rules": {"hard": [...], "soft": [...]}, "cross_component": [...]}

    Each rule dict has ``"condition"`` and ``"text"`` keys.
    """
    if project_context is None:
        project_context = {}

    result: list[EvaluatedRule] = []

    rules_section = template.get("rules", {})
    for section_name in ("hard", "soft"):
        for rule in rules_section.get(section_name, []):
            if evaluate_condition(rule["condition"], answers, project_context):
                text = interpolate_text(rule["text"], answers, project_context)
                result.append(EvaluatedRule(text=text, section=section_name))

    for rule in template.get("cross_component", []):
        if evaluate_condition(rule["condition"], answers, project_context):
            text = interpolate_text(rule["text"], answers, project_context)
            result.append(EvaluatedRule(text=text, section="cross_component"))

    return result


# ---------------------------------------------------------------------------
# Text interpolation
# ---------------------------------------------------------------------------

_INTERPOLATION_RE = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")

_VALID_INTERPOLATION_VARS = frozenset({
    "component.name",
    "component.language",
    "component.path",
    "shared.path",
    "project.name",
})


def interpolate_text(
    text: str,
    answers: dict[str, Any],
    project_context: dict[str, Any] | None = None,
) -> str:
    """Replace ``{{var}}`` placeholders in *text* with actual values.

    Raises :class:`UnknownConditionVariable` for unknown variable references.
    """
    if project_context is None:
        project_context = {}

    def _replace(m: re.Match) -> str:
        var = m.group(1)
        if var not in _VALID_INTERPOLATION_VARS:
            raise UnknownConditionVariable(
                f"Unknown interpolation variable: {{{{{var}}}}}"
            )
        return _resolve_var(var, answers, project_context)

    return _INTERPOLATION_RE.sub(_replace, text)


def _resolve_var(
    var: str,
    answers: dict[str, Any],
    project_context: dict[str, Any],
) -> str:
    """Resolve a dotted variable name to its string value."""
    parts = var.split(".")
    # Look in project_context first (component.*, shared.*, project.*)
    obj: Any = project_context
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part, "")
        else:
            return ""
    return str(obj)


# ---------------------------------------------------------------------------
# Variable extraction (for template validation)
# ---------------------------------------------------------------------------


def extract_variables(condition: str) -> set[str]:
    """Extract variable names referenced in a condition string."""
    parsed = parse_condition(condition)
    if parsed.variable is not None:
        return {parsed.variable}
    if parsed.kind == "has_component":
        return set()  # has_component references project_context, not answers
    return set()


def extract_interpolation_vars(text: str) -> set[str]:
    """Extract ``{{var}}`` variable names from rule text."""
    return set(_INTERPOLATION_RE.findall(text))
