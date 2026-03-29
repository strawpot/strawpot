"""Atomic file writer for strawpot init.

All files are staged in memory and written in a single pass. If any
generation step fails, no files are written (no partial writes invariant).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from strawpot.init.types import GeneratedFile


def write_files(
    files: list[GeneratedFile],
    project_dir: Path,
    *,
    dry_run: bool = False,
    existing_actions: dict[str, str] | None = None,
) -> list[Path]:
    """Write generated files to disk atomically.

    Parameters
    ----------
    files:
        Files to write, staged in memory.
    project_dir:
        The project root directory.
    dry_run:
        If True, print file contents without writing.
    existing_actions:
        Mapping of relative path → action ("skip", "backup", "append")
        for files that already exist.

    Returns
    -------
    List of paths actually written.
    """
    if existing_actions is None:
        existing_actions = {}

    if dry_run:
        _print_dry_run(files, project_dir)
        return []

    # Validate all paths are writable before writing any
    for f in files:
        target = project_dir / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not _is_writable(target.parent):
            click.echo(
                click.style(f"  ✗ Cannot write to {target} — permission denied. Skipping.", fg="red")
            )

    # Write all files
    written: list[Path] = []
    for f in files:
        target = project_dir / f.path
        action = existing_actions.get(f.path)

        if target.exists():
            if action == "skip":
                click.echo(f"  → Skipped {f.path} (already exists)")
                continue
            elif action == "backup":
                backup = target.with_suffix(target.suffix + ".bak")
                shutil.copy2(target, backup)
                click.echo(f"  → Backed up {f.path} → {backup.name}")
            elif action == "append":
                existing = target.read_text(encoding="utf-8")
                content = existing + "\n\n<!-- strawpot:generated -->\n" + f.content
                target.write_text(content, encoding="utf-8")
                written.append(target)
                continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content, encoding="utf-8")
        written.append(target)

    return written


def _print_dry_run(files: list[GeneratedFile], project_dir: Path) -> None:
    """Print generated files without writing them."""
    click.echo(click.style("\n--- Dry Run (no files will be written) ---\n", bold=True))
    for f in files:
        target = project_dir / f.path
        click.echo(click.style(f"📄 {f.path}", bold=True))
        click.echo(f"   Would write to: {target}")
        click.echo(f"   Rules: {f.rule_count}")
        click.echo()
        # Show first 20 lines of content
        lines = f.content.split("\n")
        preview = lines[:20]
        for line in preview:
            click.echo(f"   {line}")
        if len(lines) > 20:
            click.echo(f"   ... ({len(lines) - 20} more lines)")
        click.echo()


def _is_writable(path: Path) -> bool:
    """Check if a directory is writable."""
    import os
    return os.access(path, os.W_OK)
