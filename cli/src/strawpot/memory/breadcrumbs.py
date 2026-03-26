"""Breadcrumb hints for memory CLI commands.

Every CLI command prints a contextual hint to guide users toward
MCP setup, scheduling, and memory management. Hints use dim styling
so they're visually secondary to the primary output.
"""

from __future__ import annotations

import click


def remember_breadcrumb(mcp_configured: bool) -> None:
    """Print breadcrumb after a remember command."""
    click.echo()
    if not mcp_configured:
        click.echo(
            click.style(
                "⚠️  MCP not configured. Run "
                + click.style("strawpot mcp setup", bold=True)
                + " so Claude Code sees this automatically.",
                dim=True,
            )
        )
    else:
        click.echo(
            click.style("✅ Claude Code will see this next session.", dim=True)
        )


def recall_breadcrumb() -> None:
    """Print breadcrumb after a recall command."""
    click.echo()
    click.echo(
        click.style(
            "💡 Tip: Try "
            + click.style("strawpot memory list", bold=True)
            + " to see all stored memories.",
            dim=True,
        )
    )


def forget_breadcrumb() -> None:
    """Print breadcrumb after a forget command."""
    click.echo()
    click.echo(
        click.style(
            "💡 Claude Code will no longer see this memory in future sessions.",
            dim=True,
        )
    )


def list_breadcrumb() -> None:
    """Print breadcrumb after a memory list command."""
    click.echo()
    click.echo(
        click.style(
            "💡 Tip: Use "
            + click.style("strawpot forget <id>", bold=True)
            + " to remove outdated memories.",
            dim=True,
        )
    )
