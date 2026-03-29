"""Drift detection for generated CLAUDE.md files.

Compares inline metadata (``<!-- strawpot:meta -->``) against current project
state to detect when regeneration may be needed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import click
import yaml

from strawpot.init.exceptions import BrokenInlineMetadata


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class DriftType(Enum):
    NEW_DIRECTORY = "new_directory"
    REMOVED_DIRECTORY = "removed_directory"
    BUILD_FILE_CHANGED = "build_file_changed"
    STALE_CONFIG = "stale_config"


@dataclass
class DriftWarning:
    """A single drift warning for a CLAUDE.md file."""

    component_path: str
    drift_type: DriftType
    message: str
    suggestion: str


# ---------------------------------------------------------------------------
# Inline metadata parsing
# ---------------------------------------------------------------------------

_META_RE = re.compile(
    r"<!--\s*strawpot:meta\s*\n(.*?)\n\s*-->",
    re.DOTALL,
)

_FRESHNESS_DAYS = 90

# Build files to hash for change detection
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
}


def parse_inline_metadata(file_path: Path) -> dict | None:
    """Extract and parse the ``<!-- strawpot:meta -->`` block from a CLAUDE.md.

    Returns the parsed metadata dict, or ``None`` if no metadata block found.
    Raises :class:`BrokenInlineMetadata` if the block exists but is malformed.
    """
    if not file_path.exists():
        return None

    content = file_path.read_text(encoding="utf-8")
    m = _META_RE.search(content)
    if not m:
        return None

    yaml_text = m.group(1)
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise BrokenInlineMetadata(
            f"Malformed metadata in {file_path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise BrokenInlineMetadata(
            f"Metadata in {file_path} is not a YAML mapping"
        )

    return data


# ---------------------------------------------------------------------------
# Build file hashing
# ---------------------------------------------------------------------------


def _hash_build_files(component_dir: Path) -> str:
    """Compute a SHA-256 hash of build files in a directory."""
    hasher = hashlib.sha256()
    for name in sorted(_BUILD_FILES):
        path = component_dir / name
        if path.is_file():
            hasher.update(name.encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _list_subdirs(component_dir: Path) -> list[str]:
    """List immediate subdirectory names (shallow)."""
    if not component_dir.is_dir():
        return []
    return sorted(
        d.name for d in component_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def check_drift(
    project_dir: Path,
    *,
    verbose: bool = False,
) -> list[DriftWarning]:
    """Check all CLAUDE.md files with metadata for drift.

    Returns a list of warnings. Also prints formatted output.
    """
    warnings: list[DriftWarning] = []

    # Find all CLAUDE.md files
    claude_files = list(project_dir.rglob("CLAUDE.md"))
    if not claude_files:
        click.echo("No CLAUDE.md files found.")
        return warnings

    for claude_path in sorted(claude_files):
        rel_path = claude_path.relative_to(project_dir)

        meta = None
        try:
            meta = parse_inline_metadata(claude_path)
        except BrokenInlineMetadata as exc:
            click.echo(
                click.style(f"  ⚠ {rel_path}", fg="yellow")
                + f" — broken metadata: {exc}"
            )
            continue

        if meta is None:
            if verbose:
                click.echo(
                    f"  {rel_path} has no strawpot metadata. Treat as manually managed."
                )
            continue

        component_dir = claude_path.parent
        component_name = meta.get("component", str(rel_path.parent))

        # Check directory drift
        dirs_at_gen = meta.get("dirs_at_gen", [])
        if isinstance(dirs_at_gen, str):
            dirs_at_gen = [d.strip() for d in dirs_at_gen.strip("[]").split(",") if d.strip()]
        if dirs_at_gen:
            current_dirs = _list_subdirs(component_dir)
            new_dirs = set(current_dirs) - set(dirs_at_gen)
            removed_dirs = set(dirs_at_gen) - set(current_dirs)

            for d in sorted(new_dirs):
                w = DriftWarning(
                    component_path=str(rel_path),
                    drift_type=DriftType.NEW_DIRECTORY,
                    message=f"New directory '{d}' added since generation",
                    suggestion=f"Run 'strawpot init' to regenerate with updated structure",
                )
                warnings.append(w)

            for d in sorted(removed_dirs):
                w = DriftWarning(
                    component_path=str(rel_path),
                    drift_type=DriftType.REMOVED_DIRECTORY,
                    message=f"Directory '{d}' removed since generation",
                    suggestion=f"Run 'strawpot init' to regenerate with updated structure",
                )
                warnings.append(w)

        # Check build file hash drift
        build_hash_at_gen = meta.get("build_file_hash", "")
        if build_hash_at_gen:
            current_hash = _hash_build_files(component_dir)
            if current_hash != build_hash_at_gen:
                w = DriftWarning(
                    component_path=str(rel_path),
                    drift_type=DriftType.BUILD_FILE_CHANGED,
                    message="Build files have changed since generation",
                    suggestion="Run 'strawpot init' to regenerate with updated build configuration",
                )
                warnings.append(w)

        # Check freshness
        generated_at = meta.get("generated")
        if generated_at:
            try:
                if isinstance(generated_at, datetime):
                    gen_time = generated_at.replace(tzinfo=timezone.utc) if generated_at.tzinfo is None else generated_at
                else:
                    gen_time = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - gen_time).days
                if age_days > _FRESHNESS_DAYS:
                    w = DriftWarning(
                        component_path=str(rel_path),
                        drift_type=DriftType.STALE_CONFIG,
                        message=f"Generated {age_days} days ago (threshold: {_FRESHNESS_DAYS} days)",
                        suggestion="Run 'strawpot init' to refresh with latest templates",
                    )
                    warnings.append(w)
            except (ValueError, TypeError):
                pass

    # Print results
    if warnings:
        click.echo(click.style(f"\n⚠ Found {len(warnings)} drift warning(s):\n", fg="yellow", bold=True))
        for w in warnings:
            click.echo(f"  ⚠ {w.component_path}: {w.message}")
            if verbose:
                click.echo(f"    → {w.suggestion}")
        click.echo()
    else:
        click.echo(click.style("\n✓ No drift detected.\n", fg="green", bold=True))

    return warnings
