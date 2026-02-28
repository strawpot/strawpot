"""StrawPot CLI — agent orchestration commands + strawhub passthrough."""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from strawpot import __version__
from strawpot._process import is_pid_alive
from strawpot.config import get_strawpot_home, load_config


@click.group()
@click.version_option(version=__version__)
def cli():
    """StrawPot — lightweight agent orchestration."""


# ---------------------------------------------------------------------------
# Session commands
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--role", default=None, help="Orchestrator role slug from strawhub.")
@click.option("--runtime", default=None, help="Agent runtime (any registry-resolvable name).")
@click.option(
    "--isolation",
    default=None,
    type=click.Choice(["none", "worktree", "docker"]),
    help="Isolation method.",
)
@click.option(
    "--merge-strategy",
    default=None,
    type=click.Choice(["auto", "local", "pr"]),
    help="How to apply session changes at cleanup.",
)
@click.option(
    "--pull",
    default=None,
    type=click.Choice(["auto", "always", "never", "prompt"]),
    help="Whether to pull latest before creating a session.",
)
@click.option("--host", default=None, help="Denden server host.")
@click.option("--port", default=None, type=int, help="Denden server port.")
def start(role, runtime, isolation, merge_strategy, pull, host, port):
    """Start an orchestration session.

    Runs in the foreground — creates an isolated environment (if configured),
    starts the denden server, spawns the orchestrator agent, and attaches you
    to it. On exit (Ctrl+C or agent quit), cleans up automatically.
    """
    config = load_config(Path.cwd())
    if role:
        config.orchestrator_role = role
    if runtime:
        config.runtime = runtime
    if isolation:
        config.isolation = isolation
    if merge_strategy:
        config.merge_strategy = merge_strategy
    if pull:
        config.pull_before_session = pull
    if host or port:
        current_host, current_port = config.denden_addr.rsplit(":", 1)
        config.denden_addr = f"{host or current_host}:{port or current_port}"
    click.echo("strawpot start: not yet implemented")


@cli.command(name="config")
def show_config():
    """Show merged configuration."""
    config = load_config(Path.cwd())
    click.echo(f"runtime:              {config.runtime}")
    click.echo(f"isolation:            {config.isolation}")
    click.echo(f"denden_addr:          {config.denden_addr}")
    click.echo(f"orchestrator_role:    {config.orchestrator_role}")
    click.echo(f"allowed_roles:        {config.allowed_roles}")
    click.echo(f"max_depth:            {config.max_depth}")
    click.echo(f"merge_strategy:       {config.merge_strategy}")
    click.echo(f"pull_before_session:  {config.pull_before_session}")
    click.echo(f"pr_command:           {config.pr_command}")
    click.echo(f"agents:               {config.agents}")


def _sessions_dir() -> Path:
    """Return the sessions directory, searching CWD then global."""
    local = Path.cwd() / ".strawpot" / "runtime" / "sessions"
    if local.is_dir():
        return local
    return get_strawpot_home() / "runtime" / "sessions"


def _load_session(path: Path) -> dict | None:
    """Load and return a session JSON file, or None if invalid."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _format_uptime(started_at: str) -> str:
    """Format uptime from ISO timestamp to human-readable duration."""
    try:
        start = datetime.fromisoformat(started_at)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - start
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h{minutes}m"
        if minutes > 0:
            return f"{minutes}m{seconds}s"
        return f"{seconds}s"
    except (ValueError, TypeError):
        return "?"


@cli.command()
def sessions():
    """List all running sessions on this machine."""
    sessions_path = _sessions_dir()
    if not sessions_path.is_dir():
        click.echo("No sessions found.")
        return

    session_files = sorted(sessions_path.glob("*.json"))
    if not session_files:
        click.echo("No sessions found.")
        return

    # Header
    click.echo(f"{'RUN ID':<20} {'STATUS':<8} {'ISOLATION':<10} {'RUNTIME':<14} {'DENDEN':<20} {'UPTIME':<10}")
    click.echo("-" * 82)

    for path in session_files:
        data = _load_session(path)
        if data is None:
            continue
        run_id = data.get("run_id", path.stem)
        pid = data.get("pid")
        alive = is_pid_alive(pid) if pid else False
        status = "running" if alive else "stale"
        isolation = data.get("isolation", "?")
        runtime = data.get("runtime", "?")
        addr = data.get("denden_addr", "?")
        uptime = _format_uptime(data.get("started_at", "")) if alive else "-"
        click.echo(f"{run_id:<20} {status:<8} {isolation:<10} {runtime:<14} {addr:<20} {uptime:<10}")


@cli.command()
@click.argument("session_id")
def agents(session_id):
    """List agents running in a session."""
    sessions_path = _sessions_dir()
    session_file = sessions_path / f"{session_id}.json"
    if not session_file.is_file():
        click.echo(f"Session not found: {session_id}")
        sys.exit(1)

    data = _load_session(session_file)
    if data is None:
        click.echo(f"Failed to read session: {session_id}")
        sys.exit(1)

    agents_map = data.get("agents", {})
    if not agents_map:
        click.echo("No agents recorded for this session.")
        return

    click.echo(f"{'AGENT ID':<20} {'ROLE':<16} {'RUNTIME':<14} {'PARENT':<20} {'STATUS':<8}")
    click.echo("-" * 78)

    for agent_id, info in agents_map.items():
        role = info.get("role", "?")
        runtime = info.get("runtime", "?")
        parent = info.get("parent") or "-"
        pid = info.get("pid")
        alive = is_pid_alive(pid) if pid else False
        status = "running" if alive else "exited"
        click.echo(f"{agent_id:<20} {role:<16} {runtime:<14} {parent:<20} {status:<8}")


# ---------------------------------------------------------------------------
# Strawhub passthrough
# ---------------------------------------------------------------------------


def _strawhub(*args: str) -> None:
    """Run a strawhub CLI command, passing through stdout/stderr."""
    cmd = shutil.which("strawhub")
    if cmd is None:
        click.echo("Error: strawhub CLI not found on PATH.", err=True)
        click.echo("Install it with: pip install strawhub", err=True)
        sys.exit(1)
    result = subprocess.run(
        [cmd, *args],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    sys.exit(result.returncode)


@cli.command()
@click.argument("kind", type=click.Choice(["skill", "role", "agent", "memory"]))
@click.argument("slug")
def install(kind, slug):
    """Install a skill, role, agent, or memory provider from StrawHub."""
    _strawhub("install", kind, slug)


@cli.command()
@click.argument("kind", type=click.Choice(["skill", "role", "agent", "memory"]))
@click.argument("slug")
def uninstall(kind, slug):
    """Uninstall a skill, role, agent, or memory provider."""
    _strawhub("uninstall", kind, slug)


@cli.command()
@click.argument("query")
def search(query):
    """Search StrawHub for skills, roles, agents, and memory providers."""
    _strawhub("search", query)


@cli.command(name="list")
def list_installed():
    """List installed packages."""
    _strawhub("list")
