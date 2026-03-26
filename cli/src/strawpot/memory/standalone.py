"""Standalone memory access — use a MemoryProvider without a Session."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from strawpot.config import load_config
from strawpot.memory.registry import load_provider, resolve_memory
from strawpot_memory.memory_protocol import MemoryProvider

log = logging.getLogger(__name__)

# Synthetic context for CLI-originated memory calls.
CLI_SESSION_ID = "cli-standalone"
CLI_AGENT_ID = "cli-user"
CLI_ROLE = "user"

_PROJECT_MARKERS = ("strawpot.toml", ".strawpot")


def detect_project_dir(start: str | None = None) -> str:
    """Walk up from *start* (or CWD) to find the project root.

    A project root is a directory containing ``strawpot.toml`` or a
    ``.strawpot/`` directory.

    Returns:
        Absolute path to the project root.

    Raises:
        click.ClickException: If no project root is found.
    """
    current = Path(start or ".").resolve()
    for directory in (current, *current.parents):
        for marker in _PROJECT_MARKERS:
            if (directory / marker).exists():
                return str(directory)
    raise click.ClickException(
        f"No StrawPot project found (searched from {current} to /).\n"
        "Run 'strawpot init' to create one, or pass --project-dir explicitly."
    )


def get_standalone_provider(
    project_dir: str | None = None,
    memory_name: str | None = None,
) -> MemoryProvider:
    """Instantiate a memory provider for standalone CLI use.

    Args:
        project_dir: Project root. Auto-detected from CWD if None.
        memory_name: Provider name. Read from strawpot.toml if None.

    Returns:
        Ready-to-use MemoryProvider instance.

    Raises:
        FileNotFoundError: If no memory provider found.
        click.ClickException: If project detection fails.
    """
    proj = project_dir or detect_project_dir()
    config = load_config(Path(proj))

    name = memory_name or config.memory or "dial"
    user_config = dict(config.memory_config) if config.memory_config else {}

    spec = resolve_memory(name, proj, user_config)
    return load_provider(spec)
