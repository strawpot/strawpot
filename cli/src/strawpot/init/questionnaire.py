"""Adaptive questionnaire for strawpot init.

Walks users through project type selection, component discovery, path/language
configuration, and archetype-specific questions.  Returns a fully populated
:class:`ProjectConfig`.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import click

from strawpot.init.loader import list_archetypes, load_archetype
from strawpot.init.types import ComponentConfig, ProjectConfig

# ---------------------------------------------------------------------------
# Project type → archetype mapping
# ---------------------------------------------------------------------------

_PROJECT_TYPES = ["Game", "Web", "Mobile", "CLI", "Monorepo", "Other"]

_DEFAULT_COMPONENTS: dict[str, list[dict[str, str]]] = {
    "Game": [
        {"name": "engine", "archetype": "game-engine"},
        {"name": "server", "archetype": "game-server"},
        {"name": "client", "archetype": "game-client"},
        {"name": "shared", "archetype": "generic"},
    ],
    "Web": [
        {"name": "api", "archetype": "web-api"},
        {"name": "client", "archetype": "generic"},
        {"name": "shared", "archetype": "generic"},
    ],
    "Mobile": [
        {"name": "app", "archetype": "generic"},
        {"name": "api", "archetype": "web-api"},
    ],
    "CLI": [
        {"name": "cli", "archetype": "generic"},
    ],
}

# Build files that indicate a component root
_BUILD_FILES = {
    "CMakeLists.txt",
    "Cargo.toml",
    "package.json",
    "pyproject.toml",
    "go.mod",
    "Makefile",
    "build.gradle",
    "pom.xml",
    "meson.build",
    "premake5.lua",
}

# File extension → language mapping
_EXTENSION_MAP: dict[str, str] = {
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++", ".h": "C++",
    ".c": "C",
    ".rs": "Rust",
    ".py": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript",
    ".go": "Go",
    ".java": "Java",
    ".cs": "C#",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".rb": "Ruby",
}

_MAX_SCAN_DEPTH = 3
_MAX_SUGGESTIONS = 20


# ---------------------------------------------------------------------------
# Auto-detection helpers
# ---------------------------------------------------------------------------


def suggest_component_paths(project_dir: Path) -> dict[str, Path]:
    """Scan *project_dir* for directories containing build files.

    Returns a mapping of directory names to paths, max depth 3,
    capped at 20 suggestions.
    """
    suggestions: dict[str, Path] = {}

    for root, dirs, files in os.walk(project_dir):
        depth = Path(root).relative_to(project_dir).parts
        if len(depth) >= _MAX_SCAN_DEPTH:
            dirs.clear()
            continue
        # Skip hidden/vendor dirs
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "vendor", "__pycache__", "venv", ".venv"}]

        if _BUILD_FILES & set(files):
            rel = Path(root).relative_to(project_dir)
            name = rel.name or project_dir.name
            suggestions[name] = rel
            if len(suggestions) >= _MAX_SUGGESTIONS:
                break

    return suggestions


def detect_language(component_path: Path) -> str | None:
    """Detect the primary language of a component by counting file extensions.

    Returns the language name if ≥80% of source files share a language,
    otherwise ``None``.
    """
    counter: Counter[str] = Counter()
    for root, dirs, files in os.walk(component_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "vendor", "__pycache__", "venv", ".venv"}]
        for f in files:
            ext = Path(f).suffix.lower()
            lang = _EXTENSION_MAP.get(ext)
            if lang:
                counter[lang] += 1

    if not counter:
        return None

    total = sum(counter.values())
    top_lang, top_count = counter.most_common(1)[0]
    if top_count / total >= 0.8:
        return top_lang
    return None


# ---------------------------------------------------------------------------
# Existing CLAUDE.md handling
# ---------------------------------------------------------------------------


def check_existing_claude_md(path: Path) -> str | None:
    """Check if a CLAUDE.md already exists at *path*.

    Returns ``"skip"``, ``"backup"``, or ``"append"`` based on user choice,
    or ``None`` if no existing file.
    """
    claude_md = path / "CLAUDE.md" if path.is_dir() else path
    if not claude_md.exists():
        return None

    click.echo(f"\n{claude_md} already exists.")
    choice = click.prompt(
        "  [S]kip / [B]ackup and replace / [A]ppend generated section",
        type=click.Choice(["S", "B", "A"], case_sensitive=False),
        default="S",
    )
    return {"s": "skip", "b": "backup", "a": "append"}[choice.lower()]


# ---------------------------------------------------------------------------
# Questionnaire flow
# ---------------------------------------------------------------------------


def _ask_select(prompt: str, choices: list[str], default: str | None = None) -> str:
    """Ask a selection question using questionary (or click fallback)."""
    try:
        import questionary
        result = questionary.select(prompt, choices=choices, default=default).unsafe_ask()
        if result is None:
            raise KeyboardInterrupt
        return result
    except ImportError:
        return click.prompt(prompt, type=click.Choice(choices), default=default or choices[0])


def _ask_checkbox(prompt: str, choices: list[str]) -> list[str]:
    """Ask a checkbox question using questionary (or click fallback)."""
    try:
        import questionary
        result = questionary.checkbox(prompt, choices=choices).unsafe_ask()
        if result is None:
            raise KeyboardInterrupt
        return result
    except ImportError:
        click.echo(f"{prompt} (comma-separated)")
        raw = click.prompt("Selection", default=",".join(choices))
        return [c.strip() for c in raw.split(",") if c.strip() in choices]


def _ask_text(prompt: str, default: str = "") -> str:
    """Ask a text input question."""
    try:
        import questionary
        result = questionary.text(prompt, default=default).unsafe_ask()
        if result is None:
            raise KeyboardInterrupt
        return result
    except ImportError:
        return click.prompt(prompt, default=default)


def run_questionnaire(
    project_dir: Path,
    non_interactive: bool = False,
) -> ProjectConfig:
    """Run the adaptive questionnaire and return a :class:`ProjectConfig`.

    Parameters
    ----------
    project_dir:
        The root directory of the project.
    non_interactive:
        If True, use defaults without prompting.
    """
    project_name = project_dir.name

    # Q1: Project type
    if non_interactive:
        project_type = "Other"
    else:
        click.echo(click.style("\n🔧 strawpot init — Project Configuration\n", bold=True))
        project_type = _ask_select(
            "What type of project is this?",
            _PROJECT_TYPES,
            default="Other",
        )

    # Get suggested component paths
    suggestions = suggest_component_paths(project_dir)

    # Q2: Component selection
    default_comps = _DEFAULT_COMPONENTS.get(project_type, [])

    if non_interactive:
        # Use defaults or single generic component
        if default_comps:
            selected_names = [c["name"] for c in default_comps]
        else:
            selected_names = [project_name]
            default_comps = [{"name": project_name, "archetype": "generic"}]
    elif not default_comps or project_type == "Other":
        # Generic flow: ask how many components
        click.echo("\nNo predefined components for this project type.")
        comp_count = click.prompt("How many components?", type=int, default=1)
        selected_names = []
        for i in range(comp_count):
            name = _ask_text(f"Component {i+1} name", default=f"component-{i+1}")
            selected_names.append(name)
        default_comps = [{"name": n, "archetype": "generic"} for n in selected_names]
    else:
        available = [c["name"] for c in default_comps]
        selected_names = _ask_checkbox(
            "Which components does your project have?",
            available,
        )
        if not selected_names:
            selected_names = available[:1]

    # Single-component fast path
    is_single = len(selected_names) == 1

    # Build components
    components: list[ComponentConfig] = []
    available_archetypes = set(list_archetypes())

    for comp_def in default_comps:
        if comp_def["name"] not in selected_names:
            continue

        name = comp_def["name"]
        archetype_slug = comp_def.get("archetype", "generic")

        # Q3: Path per component
        if is_single:
            comp_path = "."
        elif non_interactive:
            comp_path = suggestions.get(name, Path(name))
            comp_path = str(comp_path)
        else:
            suggested = suggestions.get(name)
            default_path = str(suggested) if suggested else name
            comp_path = _ask_text(f"Path for '{name}' component", default=default_path)

        # Resolve and validate path
        full_path = project_dir / comp_path
        if not full_path.exists() and not non_interactive:
            click.echo(f"  ⚠ Path '{comp_path}' does not exist. It will be created.")

        # Q4: Language per component
        detected = None
        if full_path.exists():
            detected = detect_language(full_path)

        if non_interactive:
            language = detected or "Unknown"
        elif detected:
            language = _ask_select(
                f"Language for '{name}'? (detected: {detected})",
                [detected, "C++", "C", "Rust", "Python", "TypeScript", "Go", "Java", "Other"],
                default=detected,
            )
        else:
            language = _ask_select(
                f"Language for '{name}'?",
                ["C++", "C", "Rust", "Python", "TypeScript", "JavaScript", "Go", "Java", "Other"],
            )

        # Q5: Archetype-specific questions
        archetype_answers: dict[str, str] = {}
        if archetype_slug in available_archetypes:
            try:
                archetype = load_archetype(archetype_slug)
                for q in archetype.questions:
                    if non_interactive:
                        answer = q.default or q.choices[0] if q.choices else ""
                    else:
                        answer = _ask_select(
                            f"[{name}] {q.question}",
                            q.choices,
                            default=q.default,
                        )
                    archetype_answers[q.id] = answer
            except FileNotFoundError:
                pass

        components.append(ComponentConfig(
            name=name,
            path=comp_path if comp_path != "." else "",
            language=language,
            build_system="",
            archetype=archetype_slug,
            archetype_answers=archetype_answers,
        ))

    return ProjectConfig(
        project_name=project_name,
        project_type=project_type,
        components=components,
    )
