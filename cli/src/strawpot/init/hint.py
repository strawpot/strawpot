"""Discovery hint — tells users about ``strawpot init`` when no CLAUDE.md exists."""

from __future__ import annotations

import json
from pathlib import Path

import click

from strawpot.config import get_strawpot_home


_HINTS_FILE = "hints.json"


def _hints_path() -> Path:
    return get_strawpot_home() / _HINTS_FILE


def _load_hints() -> dict:
    path = _hints_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_hints(data: dict) -> None:
    path = _hints_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def should_show_init_hint(project_dir: Path) -> bool:
    """Return True if the init hint should be shown for this project.

    Conditions:
    - No CLAUDE.md exists at the project root
    - Hint hasn't been dismissed for this project path
    """
    if (project_dir / "CLAUDE.md").exists():
        return False

    hints = _load_hints()
    dismissed = hints.get("dismissed_init", [])
    return str(project_dir) not in dismissed


def show_init_hint() -> None:
    """Print the discovery hint."""
    click.echo()
    click.echo(
        click.style("Tip:", bold=True)
        + " Run "
        + click.style("strawpot init", bold=True)
        + " to generate agent configuration for this project."
    )


def dismiss_init_hint(project_dir: Path) -> None:
    """Dismiss the init hint for the given project directory."""
    hints = _load_hints()
    dismissed = hints.get("dismissed_init", [])
    project_str = str(project_dir)
    if project_str not in dismissed:
        dismissed.append(project_str)
    hints["dismissed_init"] = dismissed
    _save_hints(hints)
