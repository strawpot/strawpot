"""Markdown renderer — composes template layers into CLAUDE.md content."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from strawpot.init.engine import EvaluatedRule, evaluate_rules
from strawpot.init.types import (
    ArchetypeTemplate,
    ComponentConfig,
    GeneratedFile,
    LanguageLayer,
    ProjectConfig,
)


def render_inline_metadata(
    component: ComponentConfig,
    rule_count: int,
    *,
    dirs_at_gen: list[str] | None = None,
    build_file_hash: str = "",
) -> str:
    """Generate the ``<!-- strawpot:meta -->`` inline metadata block."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dirs = ", ".join(dirs_at_gen) if dirs_at_gen else ""

    lines = [
        "<!-- strawpot:meta",
        f"generated: {timestamp}",
        f"archetype: {component.archetype}",
        f"language: {component.language}",
        f"component: {component.name}",
        f"rule_count: {rule_count}",
    ]
    if dirs:
        lines.append(f"dirs_at_gen: [{dirs}]")
    if build_file_hash:
        lines.append(f"build_file_hash: {build_file_hash}")
    lines.append("-->")
    return "\n".join(lines)


def _build_project_context(
    component: ComponentConfig,
    project: ProjectConfig,
) -> dict:
    """Build the project_context dict for engine evaluation."""
    return {
        "components": [c.name for c in project.components],
        "component": {
            "name": component.name,
            "path": component.path,
            "language": component.language,
        },
        "shared": {
            "path": next(
                (c.path for c in project.components if c.name == "shared"),
                "",
            ),
        },
        "project": {
            "name": project.project_name,
        },
    }


def _evaluate_layer(
    rules_dict: dict,
    cross_component: list | None,
    answers: dict,
    project_context: dict,
) -> list[EvaluatedRule]:
    """Evaluate a single template layer (archetype or language)."""
    template = {"rules": rules_dict}
    if cross_component:
        template["cross_component"] = cross_component
    return evaluate_rules(template, answers, project_context)


def render_component_claude_md(
    component: ComponentConfig,
    project: ProjectConfig,
    archetype: ArchetypeTemplate,
    language_layer: LanguageLayer | None = None,
) -> GeneratedFile:
    """Render a CLAUDE.md for a single component.

    Composes 4 layers in order:
    1. Language layer rules
    2. Archetype hard rules
    3. Archetype conditional (soft) rules
    4. Cross-component rules
    """
    ctx = _build_project_context(component, project)
    answers = dict(component.archetype_answers)

    # Layer 1: Language rules
    lang_rules: list[EvaluatedRule] = []
    if language_layer:
        lang_rules = _evaluate_layer(
            language_layer.rules, None, answers, ctx,
        )

    # Layers 2-4: Archetype rules (hard + soft + cross_component)
    archetype_rules = _evaluate_layer(
        archetype.rules, archetype.cross_component, answers, ctx,
    )

    # Partition archetype rules by section
    hard_rules = [r for r in archetype_rules if r.section == "hard"]
    soft_rules = [r for r in archetype_rules if r.section == "soft"]
    cross_rules = [r for r in archetype_rules if r.section == "cross_component"]

    all_rules = lang_rules + archetype_rules
    rule_count = len(all_rules)

    # Build Markdown
    sections: list[str] = []

    # Inline metadata
    sections.append(render_inline_metadata(component, rule_count))
    sections.append("")

    # Identity
    sections.append(f"# {component.name}")
    sections.append("")
    sections.append(
        f"This is the **{component.name}** component of {project.project_name}, "
        f"written in {component.language}."
    )
    if component.archetype:
        sections.append(f"Archetype: {component.archetype}.")
    sections.append("")

    # Build Commands
    if component.build_system:
        sections.append("## Build Commands")
        sections.append("")
        sections.append(f"Build system: {component.build_system}")
        sections.append("")
        sections.append("```bash")
        sections.append("# TODO: Add your build commands here")
        sections.append("```")
        sections.append("")

    # Language Rules (from language layer)
    if lang_rules:
        sections.append("## Language Conventions")
        sections.append("")
        for rule in lang_rules:
            sections.append(f"- {rule.text}")
        sections.append("")

    # Hard Rules
    if hard_rules:
        sections.append("## Hard Rules")
        sections.append("")
        sections.append("These rules must always be followed:")
        sections.append("")
        for rule in hard_rules:
            sections.append(f"- {rule.text}")
        sections.append("")

    # Soft Rules
    if soft_rules:
        sections.append("## Soft Rules")
        sections.append("")
        sections.append("Follow these conventions unless there's a good reason not to:")
        sections.append("")
        for rule in soft_rules:
            sections.append(f"- {rule.text}")
        sections.append("")

    # Cross-Component Awareness
    if cross_rules:
        sections.append("## Cross-Component Awareness")
        sections.append("")
        for rule in cross_rules:
            sections.append(f"- {rule.text}")
        sections.append("")

    # Architecture Guide
    sections.append("## Architecture Guide")
    sections.append("")
    sections.append("<!-- TODO: Add architecture-specific guidance for this component -->")
    sections.append("")

    # Project-Specific Rules
    sections.append("## Project-Specific Rules")
    sections.append("")
    sections.append("<!-- TODO: Add rules specific to your project that templates can't cover -->")
    sections.append("")

    content = "\n".join(sections)
    path = f"{component.path}CLAUDE.md" if not component.path.endswith("/") or component.path == "" else f"{component.path}CLAUDE.md"
    if component.path and not component.path.endswith("/"):
        path = f"{component.path}/CLAUDE.md"

    return GeneratedFile(path=path, content=content, rule_count=rule_count)


def render_root_claude_md(project: ProjectConfig) -> GeneratedFile:
    """Render a root-level CLAUDE.md with project overview and component listing."""
    sections: list[str] = []

    sections.append(f"# {project.project_name}")
    sections.append("")
    sections.append(f"Project type: {project.project_type}")
    sections.append("")

    if project.components:
        sections.append("## Components")
        sections.append("")
        for comp in project.components:
            sections.append(f"- **{comp.name}** (`{comp.path}`) — {comp.language}")
        sections.append("")
        sections.append(
            "Each component has its own `CLAUDE.md` with detailed rules and conventions."
        )
        sections.append("")

    sections.append("## Cross-Component Guidelines")
    sections.append("")
    sections.append("<!-- TODO: Add project-wide guidelines that span components -->")
    sections.append("")

    content = "\n".join(sections)
    return GeneratedFile(path="CLAUDE.md", content=content, rule_count=0)
