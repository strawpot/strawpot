"""Workflow templates — pre-built scheduled workflows."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_TEMPLATE_DIR = Path(__file__).parent


@dataclass
class WorkflowTemplate:
    """A pre-built workflow template definition."""

    slug: str = ""
    name: str = ""
    description: str = ""
    default_cron: str = ""
    role: str = ""
    task: str = ""
    requires_tools: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)


def list_templates() -> list[WorkflowTemplate]:
    """List all available workflow templates."""
    templates = []
    for path in sorted(_TEMPLATE_DIR.glob("*.yaml")):
        tpl = load_template(path.stem)
        if tpl:
            templates.append(tpl)
    return templates


def load_template(slug: str) -> WorkflowTemplate | None:
    """Load a workflow template by slug name."""
    path = _TEMPLATE_DIR / f"{slug}.yaml"
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    requires = data.get("requires", {})
    return WorkflowTemplate(
        slug=slug,
        name=data.get("name", slug),
        description=data.get("description", ""),
        default_cron=data.get("default_cron", ""),
        role=data.get("role", ""),
        task=data.get("task", ""),
        requires_tools=requires.get("tools", []) if isinstance(requires, dict) else [],
        requires_env=requires.get("env", []) if isinstance(requires, dict) else [],
    )


def validate_prerequisites(template: WorkflowTemplate) -> list[str]:
    """Check if template prerequisites are met. Returns list of issues."""
    issues = []
    for tool in template.requires_tools:
        if not shutil.which(tool):
            issues.append(f"Required tool '{tool}' not found in PATH")
    for env_var in template.requires_env:
        if not os.environ.get(env_var):
            issues.append(f"Required environment variable '{env_var}' not set")
    return issues
