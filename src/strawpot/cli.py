"""Strawpot CLI — agent orchestration commands + strawhub passthrough."""

import subprocess
import sys
from pathlib import Path

import click

from strawpot import __version__
from strawpot.config import load_config


@click.group()
@click.version_option(version=__version__)
def cli():
    """Strawpot — lightweight agent orchestration."""


# ---------------------------------------------------------------------------
# Session commands
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--role", default=None, help="Orchestrator role slug from strawhub.")
@click.option("--runtime", default=None, type=click.Choice(["claude_code", "codex", "openhands"]), help="Agent runtime.")
@click.option("--isolation", default=None, type=click.Choice(["worktree", "docker"]), help="Isolation method.")
@click.option("--host", default=None, help="Denden server host.")
@click.option("--port", default=None, type=int, help="Denden server port.")
def start(role, runtime, isolation, host, port):
    """Start an orchestration session.

    Runs in the foreground — creates a worktree, starts the denden server,
    spawns the orchestrator agent, and attaches you to it. On exit (Ctrl+C
    or agent quit), cleans up everything automatically.
    """
    config = load_config(Path.cwd())
    if role:
        config.orchestrator_role = role
    if runtime:
        config.runtime = runtime
    if isolation:
        config.isolation = isolation
    if host or port:
        current_host, current_port = config.denden_addr.rsplit(":", 1)
        config.denden_addr = f"{host or current_host}:{port or current_port}"
    click.echo("strawpot start: not yet implemented")


@cli.command(name="config")
def show_config():
    """Show merged configuration."""
    config = load_config(Path.cwd())
    click.echo(f"runtime:           {config.runtime}")
    click.echo(f"isolation:         {config.isolation}")
    click.echo(f"denden_addr:       {config.denden_addr}")
    click.echo(f"orchestrator_role: {config.orchestrator_role}")
    click.echo(f"allowed_roles:     {config.allowed_roles}")
    click.echo(f"max_depth:         {config.max_depth}")
    click.echo(f"claude_model:      {config.claude_model}")


# ---------------------------------------------------------------------------
# Strawhub passthrough
# ---------------------------------------------------------------------------


def _strawhub(*args: str) -> None:
    """Run a strawhub CLI command, passing through stdout/stderr."""
    result = subprocess.run(
        ["strawhub", *args],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    sys.exit(result.returncode)


@cli.command()
@click.argument("kind", type=click.Choice(["skill", "role"]))
@click.argument("slug")
def install(kind, slug):
    """Install a skill or role from StrawHub."""
    _strawhub("install", kind, slug)


@cli.command()
@click.argument("kind", type=click.Choice(["skill", "role"]))
@click.argument("slug")
def uninstall(kind, slug):
    """Uninstall a skill or role."""
    _strawhub("uninstall", kind, slug)


@cli.command()
@click.argument("query")
def search(query):
    """Search StrawHub for skills and roles."""
    _strawhub("search", query)


@cli.command(name="list")
def list_installed():
    """List installed skills and roles."""
    _strawhub("list")
