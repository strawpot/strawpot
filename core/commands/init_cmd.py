"""lt init — scaffold a new strawpot project.

Creates ``.strawpot/`` in the current directory (or ``--workdir``) with the
standard directory layout and default role YAML files.

Usage::

    lt init               # scaffold .strawpot/ in CWD
    lt init --force       # add missing files only (never overwrites)
    lt init --workdir /path/to/repo
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Default role templates
# ---------------------------------------------------------------------------

_DEFAULT_ROLES: dict[str, dict] = {
    "planner": {
        "name": "planner",
        "description": "Decomposes an objective into a DAG of tasks",
        "default_tools": {"allowed": ["Bash", "Read", "Glob", "Grep"]},
        "default_model": {"provider": "claude_session", "id": "claude-opus-4-6"},
    },
    "implementer": {
        "name": "implementer",
        "description": "Writes code to implement features and fix bugs",
        "default_tools": {
            "allowed": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
        },
        "default_model": {"provider": "claude_session", "id": "claude-opus-4-6"},
    },
    "reviewer": {
        "name": "reviewer",
        "description": "Reviews diffs against acceptance criteria",
        "default_tools": {"allowed": ["Bash", "Read", "Glob", "Grep"]},
        "default_model": {"provider": "claude_session", "id": "claude-opus-4-6"},
    },
    "fixer": {
        "name": "fixer",
        "description": "Fixes failing checks or review blockers",
        "default_tools": {
            "allowed": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
        },
        "default_model": {"provider": "claude_session", "id": "claude-opus-4-6"},
    },
    "documenter": {
        "name": "documenter",
        "description": "Writes and updates documentation and changelogs",
        "default_tools": {
            "allowed": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
        },
        "default_model": {"provider": "claude_session", "id": "claude-opus-4-6"},
    },
}

_DEFAULT_PROJECT_YAML = """\
project:
  name: {name}
  repo_path: .
  default_branch: main

orchestrator:
  model:
    provider: claude_session
    id: claude-opus-4-6
  max_tasks_per_plan: 20
  stale_session_timeout_minutes: 20

scheduler:
  max_parallel_sessions: 3
  max_fix_attempts: 3

checks: {{}}

merge:
  approval_policy: require_human
  strategy: squash
  require_checks: []
  require_review: true
  restricted_paths: []

escalation:
  auto_bump_after_minutes: 30
  critical_task_threshold: 3
"""

_GITIGNORE_ENTRY = ".strawpot/runtime/\n"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run_init(workdir: Path, force: bool = False) -> None:
    """Scaffold ``.strawpot/`` inside *workdir*.

    Args:
        workdir: The project root directory.
        force:   If True, only add missing files without failing on existing ones.

    Raises:
        SystemExit: if ``.strawpot/`` already exists and *force* is False.
    """
    lt_dir = workdir / ".strawpot"

    if lt_dir.exists() and not force:
        print(
            f"error: {lt_dir} already exists. Use --force to add missing files.",
            file=sys.stderr,
        )
        sys.exit(1)

    created: list[str] = []
    skipped: list[str] = []

    def _write(path: Path, content: str) -> None:
        if path.exists():
            skipped.append(str(path.relative_to(workdir)))
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        created.append(str(path.relative_to(workdir)))

    def _mkdir(path: Path) -> None:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)

    # Directory structure
    _mkdir(lt_dir / "roles")
    _mkdir(lt_dir / "agents")
    _mkdir(lt_dir / "skills")

    # project.yaml
    project_name = workdir.name
    _write(lt_dir / "project.yaml", _DEFAULT_PROJECT_YAML.format(name=project_name))

    # Default role YAML files
    for role_name, role_data in _DEFAULT_ROLES.items():
        role_path = lt_dir / "roles" / f"{role_name}.yaml"
        _write(role_path, yaml.dump(role_data, default_flow_style=False, sort_keys=False))

    # .gitignore entry for runtime/
    gitignore = workdir / ".gitignore"
    if not gitignore.exists():
        _write(gitignore, _GITIGNORE_ENTRY)
    else:
        content = gitignore.read_text()
        if ".strawpot/runtime/" not in content:
            gitignore.write_text(content.rstrip("\n") + "\n" + _GITIGNORE_ENTRY)
            created.append(".gitignore (updated)")

    # Summary
    if created:
        print(f"Initialised strawpot project in {workdir}/")
        for item in created:
            print(f"  created  {item}")
    else:
        print("Nothing to do — all files already exist.")
    if skipped and force:
        for item in skipped:
            print(f"  skipped  {item} (already exists)")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def add_parser(subparsers) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("init", help="Scaffold .strawpot/ in the current repo")
    p.add_argument(
        "--force",
        action="store_true",
        help="Add missing files only (never overwrites existing files)",
    )
    p.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Target directory (default: current directory)",
    )
    p.set_defaults(func=_cli_handler)


def _cli_handler(args) -> None:  # type: ignore[type-arg]
    workdir = (args.workdir or Path.cwd()).resolve()
    run_init(workdir=workdir, force=args.force)
