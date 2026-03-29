"""Drift detection for generated CLAUDE.md files."""

from __future__ import annotations

from pathlib import Path

import click


def check_drift(project_dir: Path, *, verbose: bool = False) -> None:
    """Check for drift between generated and current CLAUDE.md files.

    Stub implementation — full drift detection is in sub-issue #620.
    """
    click.echo(click.style("strawpot init --check", bold=True) + " is not yet implemented.")
    click.echo("Drift detection will be available soon.")
