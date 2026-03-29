"""YAML template loader for archetypes and language layers."""

from __future__ import annotations

from pathlib import Path

import yaml

from strawpot.init.types import ArchetypeQuestion, ArchetypeTemplate, LanguageLayer

_TEMPLATE_DIR = Path(__file__).parent
_ARCHETYPES_DIR = _TEMPLATE_DIR / "archetypes"
_LAYERS_DIR = _TEMPLATE_DIR / "layers"


def load_archetype(slug: str) -> ArchetypeTemplate:
    """Load an archetype template from ``archetypes/{slug}/template.yaml``.

    Raises :class:`FileNotFoundError` if the template does not exist.
    """
    path = _ARCHETYPES_DIR / slug / "template.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Archetype template not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    questions = [
        ArchetypeQuestion(
            id=q["id"],
            question=q.get("question", ""),
            choices=q.get("choices", []),
            default=q.get("default", ""),
            affects=q.get("affects", []),
        )
        for q in data.get("questions", [])
    ]

    return ArchetypeTemplate(
        name=data.get("name", slug),
        slug=slug,
        languages=data.get("languages", []),
        build_systems=data.get("build_systems", []),
        questions=questions,
        rules=data.get("rules", {}),
        cross_component=data.get("cross_component", []),
    )


def load_language_layer(language: str) -> LanguageLayer:
    """Load a language layer from ``layers/{language}.yaml``.

    Raises :class:`FileNotFoundError` if the layer does not exist.
    """
    path = _LAYERS_DIR / f"{language}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Language layer not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    return LanguageLayer(
        language=data.get("language", language),
        rules=data.get("rules", {}),
    )


def list_archetypes() -> list[str]:
    """Return available archetype slugs (directories with template.yaml)."""
    if not _ARCHETYPES_DIR.is_dir():
        return []
    return sorted(
        d.name
        for d in _ARCHETYPES_DIR.iterdir()
        if d.is_dir() and (d / "template.yaml").is_file()
    )


def list_languages() -> list[str]:
    """Return available language layer slugs."""
    if not _LAYERS_DIR.is_dir():
        return []
    return sorted(p.stem for p in _LAYERS_DIR.glob("*.yaml"))
