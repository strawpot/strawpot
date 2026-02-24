"""lt agent — manage agent Charter YAML files.

Commands::

    lt agent list                             # name | role | status
    lt agent show <name>                      # Charter YAML + skill pools summary
    lt agent create --name <name> --role <role>
    lt agent edit <name>                      # open Charter YAML in $EDITOR
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core.agents.types import Charter, ModelConfig
from core.workdir import WorkdirError, resolve_workdir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agents_dir(workdir: Path) -> Path:
    return workdir / ".strawpot" / "agents"


def _agent_path(workdir: Path, name: str) -> Path:
    return _agents_dir(workdir) / f"{name}.yaml"


def _list_agent_names(workdir: Path) -> list[str]:
    d = _agents_dir(workdir)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------


def _cmd_list(workdir: Path) -> None:
    names = _list_agent_names(workdir)
    if not names:
        print("No agents found in .strawpot/agents/")
        return
    print(f"{'NAME':<20} {'ROLE':<20}")
    print("-" * 42)
    for name in names:
        path = _agent_path(workdir, name)
        role = "?"
        try:
            charter = Charter.from_yaml(path)
            role = charter.role
        except Exception:
            pass
        print(f"  {name:<18} {role:<20}")


def _cmd_show(workdir: Path, name: str) -> None:
    path = _agent_path(workdir, name)
    if not path.exists():
        print(f"error: agent {name!r} not found in .strawpot/agents/", file=sys.stderr)
        sys.exit(1)

    charter = Charter.from_yaml(path)
    print(f"Name:         {charter.name}")
    print(f"Role:         {charter.role}")
    print(f"Provider:     {charter.model.provider}")
    if charter.model.id:
        print(f"Model:        {charter.model.id}")
    print(f"Max tokens:   {charter.max_tokens}")
    print(f"Tools:        {', '.join(charter.allowed_tools)}")
    if charter.instructions.strip():
        print(f"\nInstructions:\n  {charter.instructions.strip()}")

    # Skill pools summary
    from core.skills.manager import SkillManager
    manager = SkillManager.from_charter(charter, workdir=workdir)
    pools = manager.all_pools()
    print("\nSkill pools:")
    for pool in pools:
        status = "exists" if pool.exists else "not created"
        print(f"  [{pool.scope:<8}] {pool.path}  ({status})")


def _cmd_create(workdir: Path, name: str, role: str) -> None:
    path = _agent_path(workdir, name)
    if path.exists():
        print(f"error: agent {name!r} already exists at {path}", file=sys.stderr)
        sys.exit(1)
    charter = Charter(
        name=name,
        role=role,
        model=ModelConfig(provider="claude_session", id="claude-opus-4-6"),
    )
    charter.to_yaml(path)
    print(f"Created {path}")


def _cmd_edit(workdir: Path, name: str) -> None:
    path = _agent_path(workdir, name)
    if not path.exists():
        print(
            f"error: agent {name!r} not found. "
            f"Run 'lt agent create --name {name} --role <role>' first.",
            file=sys.stderr,
        )
        sys.exit(1)
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        print(f"error: $EDITOR is not set. Edit the file manually: {path}", file=sys.stderr)
        sys.exit(1)
    subprocess.run([editor, str(path)], check=False)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def add_parser(subparsers) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("agent", help="Manage agent Charter YAML files")
    sub = p.add_subparsers(dest="agent_cmd", metavar="<subcommand>")
    sub.required = True

    sub.add_parser("list", help="List all agents")

    show_p = sub.add_parser("show", help="Print Charter + skill pools summary")
    show_p.add_argument("name", help="Agent name")

    create_p = sub.add_parser("create", help="Scaffold a new agent Charter")
    create_p.add_argument("--name", required=True, help="Agent name")
    create_p.add_argument("--role", required=True, help="Role name (e.g. implementer)")

    edit_p = sub.add_parser("edit", help="Open Charter YAML in $EDITOR")
    edit_p.add_argument("name", help="Agent name")

    p.set_defaults(func=_cli_handler)


def _cli_handler(args) -> None:  # type: ignore[type-arg]
    try:
        workdir = resolve_workdir()
    except WorkdirError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    cmd = args.agent_cmd
    if cmd == "list":
        _cmd_list(workdir)
    elif cmd == "show":
        _cmd_show(workdir, args.name)
    elif cmd == "create":
        _cmd_create(workdir, args.name, args.role)
    elif cmd == "edit":
        _cmd_edit(workdir, args.name)
