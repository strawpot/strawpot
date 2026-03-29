"""Click command for ``strawpot init`` — generate CLAUDE.md via questionnaire."""

from __future__ import annotations

from pathlib import Path

import click

from strawpot.init.exceptions import QuestionnaireAbort


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
    from strawpot.init.generator import generate_files
    from strawpot.init.questionnaire import run_questionnaire
    from strawpot.init.writer import write_files

    project_dir = Path.cwd()

    if check:
        from strawpot.init.drift import check_drift
        warnings = check_drift(project_dir, verbose=verbose)
        raise SystemExit(1 if warnings else 0)

    # Run questionnaire
    try:
        config = run_questionnaire(project_dir, non_interactive=non_interactive)
    except (KeyboardInterrupt, EOFError):
        click.echo("\nAborted. No files were written.")
        raise SystemExit(0)

    # Generate files
    try:
        files = generate_files(config, verbose=verbose)
    except Exception as exc:
        click.echo(click.style(f"\nGeneration failed: {exc}", fg="red"))
        click.echo("No files were written.")
        raise SystemExit(1)

    if not files:
        click.echo("No files to generate.")
        return

    # Write files
    written = write_files(files, project_dir, dry_run=dry_run)

    # Summary
    if dry_run:
        click.echo(click.style("Dry run complete. No files were written.", bold=True))
    else:
        click.echo()
        for f in files:
            path = project_dir / f.path
            if path in written:
                click.echo(
                    click.style("  ✓ ", fg="green")
                    + f"{f.path} ({f.rule_count} rules)"
                )
        click.echo()
        click.echo(
            f"Generated {len(written)} file(s). "
            f"Run {click.style('strawpot init --check', bold=True)} later to detect drift."
        )
