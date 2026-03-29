"""Click command for ``strawpot init`` — generate CLAUDE.md via questionnaire."""

from __future__ import annotations

import click


@click.command()
@click.option("--dry-run", is_flag=True, help="Preview generated files without writing them.")
@click.option("--check", is_flag=True, help="Check for drift between generated and current CLAUDE.md files.")
@click.option("--verbose", is_flag=True, help="Show detailed output during generation.")
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Use defaults instead of prompting (for CI environments).",
)
def init(dry_run: bool, check: bool, verbose: bool, non_interactive: bool) -> None:
    """Generate CLAUDE.md files for your project via an adaptive questionnaire.

    Asks about your project structure, languages, and frameworks, then
    generates tailored CLAUDE.md files from battle-tested templates.
    """
    click.echo(
        click.style("strawpot init", bold=True)
        + " is not yet implemented. Stay tuned!"
    )
