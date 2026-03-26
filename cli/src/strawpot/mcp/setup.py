"""Auto-configure Claude Code to use the StrawPot MCP memory server."""

from __future__ import annotations

import json
import logging
import platform
import shutil
import sys
from pathlib import Path

import click

log = logging.getLogger(__name__)

_SERVER_NAME = "strawpot-memory"


def _global_config_candidates() -> list[Path]:
    """Return candidate paths for the global Claude Code MCP config."""
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
        return [
            base / "Claude" / "claude_desktop_config.json",
            base / "Claude Code" / "claude_desktop_config.json",
        ]
    elif system == "Linux":
        return [
            Path.home() / ".config" / "claude" / "claude_desktop_config.json",
        ]
    else:  # Windows
        app_data = Path.home() / "AppData" / "Roaming"
        return [
            app_data / "Claude" / "claude_desktop_config.json",
        ]


def _project_config_path() -> Path:
    """Return the project-level MCP config path."""
    return Path(".claude") / "mcp.json"


def _build_server_entry() -> dict:
    """Build the MCP server config entry for strawpot-memory."""
    cmd = shutil.which("strawpot")
    if cmd:
        command = "strawpot"
    else:
        # Fall back to running as a Python module
        command = sys.executable
        return {
            "command": command,
            "args": ["-m", "strawpot.mcp.server"],
            "env": {},
        }
    return {
        "command": command,
        "args": ["mcp", "serve"],
        "env": {},
    }


def _read_config(path: Path) -> dict:
    """Read JSON config, handling missing or corrupt files."""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # Backup corrupt file and start fresh
        backup = path.with_suffix(".json.bak")
        try:
            path.rename(backup)
            log.warning("Backed up corrupt config to %s", backup)
        except OSError:
            pass
        click.echo(
            click.style("⚠️  ", fg="yellow")
            + f"Existing config was corrupt — backed up to {backup}"
        )
        return {}


def _write_config(path: Path, data: dict) -> None:
    """Write JSON config with pretty formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def configure_mcp(project: bool = False) -> None:
    """Add/update the StrawPot MCP server in Claude Code config.

    Args:
        project: If True, configure per-project (.claude/mcp.json).
                 If False, configure globally.
    """
    # Resolve config path
    if project:
        config_path = _project_config_path()
    else:
        candidates = _global_config_candidates()
        config_path = None
        for candidate in candidates:
            if candidate.is_file():
                config_path = candidate
                break
        if config_path is None:
            # Use the first candidate (most likely location)
            config_path = candidates[0]

    # Warn if strawpot not in PATH
    if not shutil.which("strawpot"):
        click.echo(
            click.style("⚠️  ", fg="yellow")
            + "'strawpot' not found in PATH. Using Python module fallback.\n"
            + "   For best results, ensure 'strawpot' is in your PATH."
        )

    # Read, update, write
    config = _read_config(config_path)
    existing = _SERVER_NAME in config.get("mcpServers", {})

    config.setdefault("mcpServers", {})
    config["mcpServers"][_SERVER_NAME] = _build_server_entry()
    _write_config(config_path, config)

    # Print confirmation
    action = "Updated" if existing else "Configured"
    click.echo(
        click.style(f"✅ Claude Code MCP {action.lower()}!", fg="green")
    )
    click.echo()
    click.echo(f"   Server: {_SERVER_NAME}")
    click.echo(f"   Command: strawpot mcp serve")
    click.echo(f"   Config: {config_path}")
    click.echo()
    click.echo("   Next: Restart Claude Code to activate memory.")
    click.echo()
    click.echo(
        click.style("💡 Tip: ", fg="cyan")
        + "Run "
        + click.style('strawpot remember "fact"', bold=True)
        + " to store your first memory."
    )
