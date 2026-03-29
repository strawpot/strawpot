"""Data types for the strawpot init template system."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ArchetypeQuestion:
    """A question defined in an archetype template."""

    id: str
    question: str
    choices: list[str] = field(default_factory=list)
    default: str = ""
    affects: list[str] = field(default_factory=list)


@dataclass
class ArchetypeTemplate:
    """Parsed archetype template from YAML."""

    name: str
    slug: str
    languages: list[str] = field(default_factory=list)
    build_systems: list[str] = field(default_factory=list)
    questions: list[ArchetypeQuestion] = field(default_factory=list)
    rules: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    cross_component: list[dict[str, str]] = field(default_factory=list)


@dataclass
class LanguageLayer:
    """Parsed language layer from YAML."""

    language: str
    rules: dict[str, list[dict[str, str]]] = field(default_factory=dict)


@dataclass
class ComponentConfig:
    """Configuration for a single project component."""

    name: str
    path: str
    language: str
    build_system: str = ""
    archetype: str = ""
    archetype_answers: dict[str, str] = field(default_factory=dict)


@dataclass
class ProjectConfig:
    """Full project configuration from the questionnaire."""

    project_name: str
    project_type: str
    components: list[ComponentConfig] = field(default_factory=list)


@dataclass
class GeneratedFile:
    """A file to be written (staged in memory for atomic writes)."""

    path: str  # relative to project root
    content: str
    rule_count: int = 0
