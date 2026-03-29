"""CLAUDE.md file generator — template evaluation and rendering.

Orchestrates: template loading → rule evaluation → Markdown rendering.
Returns a list of :class:`GeneratedFile` staged in memory (no I/O).
"""

from __future__ import annotations

import click

from strawpot.init.loader import list_archetypes, list_languages, load_archetype, load_language_layer
from strawpot.init.renderer import render_component_claude_md, render_root_claude_md
from strawpot.init.types import GeneratedFile, ProjectConfig

# Language name → layer file slug mapping
_LANG_TO_SLUG: dict[str, str] = {
    "C++": "cpp",
    "C": "cpp",  # C uses C++ layer as closest match
    "Rust": "rust",
    "Python": "python",
    "TypeScript": "typescript",
    "JavaScript": "typescript",  # JS uses TS layer as closest match
    "Go": "go",
}


def generate_files(
    config: ProjectConfig,
    *,
    verbose: bool = False,
) -> list[GeneratedFile]:
    """Generate all CLAUDE.md files for the project.

    Returns files staged in memory — no I/O is performed.
    """
    available_archetypes = set(list_archetypes())
    available_languages = set(list_languages())
    files: list[GeneratedFile] = []

    for component in config.components:
        # Load archetype template
        archetype_slug = component.archetype
        if archetype_slug not in available_archetypes:
            if verbose:
                click.echo(f"  No archetype '{archetype_slug}' found, using generic.")
            archetype_slug = "generic"
            if archetype_slug not in available_archetypes:
                if verbose:
                    click.echo(f"  No generic archetype found, skipping {component.name}.")
                continue

        try:
            archetype = load_archetype(archetype_slug)
        except FileNotFoundError:
            if verbose:
                click.echo(f"  Failed to load archetype '{archetype_slug}', skipping {component.name}.")
            continue

        # Load language layer
        lang_slug = _LANG_TO_SLUG.get(component.language)
        language_layer = None
        if lang_slug and lang_slug in available_languages:
            try:
                language_layer = load_language_layer(lang_slug)
            except FileNotFoundError:
                if verbose:
                    click.echo(f"  Language layer '{lang_slug}' not found.")

        # Render component CLAUDE.md
        generated = render_component_claude_md(
            component, config, archetype, language_layer,
        )
        files.append(generated)

        if verbose:
            click.echo(f"  Generated {generated.path} ({generated.rule_count} rules)")

    # Root CLAUDE.md for multi-component projects
    if len(config.components) > 1:
        root = render_root_claude_md(config)
        files.append(root)

    return files
