"""lt role — manage role YAML files.

Commands::

    lt role list                  # list all roles in .loguetown/roles/
    lt role show <name>           # print resolved role YAML
    lt role create <name>         # scaffold new role YAML
    lt role edit <name>           # open role YAML in $EDITOR
    lt role delete <name>         # remove role file
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from core.roles.types import Role
from core.workdir import WorkdirError, resolve_workdir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _roles_dir(workdir: Path) -> Path:
    return workdir / ".loguetown" / "roles"


def _role_path(workdir: Path, name: str) -> Path:
    return _roles_dir(workdir) / f"{name}.yaml"


def _list_role_names(workdir: Path) -> list[str]:
    d = _roles_dir(workdir)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


def _check_agents_using_role(workdir: Path, role_name: str) -> list[str]:
    """Return names of agents that reference *role_name*."""
    agents_dir = workdir / ".loguetown" / "agents"
    if not agents_dir.is_dir():
        return []
    using = []
    for p in agents_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(p.read_text()) or {}
            if data.get("role") == role_name:
                using.append(p.stem)
        except Exception:
            pass
    return using


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------


def _cmd_list(workdir: Path) -> None:
    names = _list_role_names(workdir)
    if not names:
        print("No roles found in .loguetown/roles/")
        return
    # Print name + description
    for name in names:
        path = _role_path(workdir, name)
        desc = ""
        try:
            role = Role.from_yaml(path)
            desc = role.description
        except Exception:
            pass
        suffix = f"  {desc}" if desc else ""
        print(f"  {name}{suffix}")


def _cmd_show(workdir: Path, name: str) -> None:
    path = _role_path(workdir, name)
    if not path.exists():
        print(f"error: role {name!r} not found in .loguetown/roles/", file=sys.stderr)
        sys.exit(1)
    print(path.read_text(), end="")


def _cmd_create(workdir: Path, name: str) -> None:
    path = _role_path(workdir, name)
    if path.exists():
        print(f"error: role {name!r} already exists at {path}", file=sys.stderr)
        sys.exit(1)
    role = Role(
        name=name,
        description="",
        default_tools={"allowed": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]},
        default_model={"provider": "claude_session", "id": "claude-opus-4-6"},
    )
    role.to_yaml(path)
    print(f"Created {path}")


def _cmd_edit(workdir: Path, name: str) -> None:
    path = _role_path(workdir, name)
    if not path.exists():
        print(f"error: role {name!r} not found. Run 'lt role create {name}' first.", file=sys.stderr)
        sys.exit(1)
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        print(f"error: $EDITOR is not set. Edit the file manually: {path}", file=sys.stderr)
        sys.exit(1)
    subprocess.run([editor, str(path)], check=False)


def _cmd_delete(workdir: Path, name: str) -> None:
    path = _role_path(workdir, name)
    if not path.exists():
        print(f"error: role {name!r} not found in .loguetown/roles/", file=sys.stderr)
        sys.exit(1)
    using = _check_agents_using_role(workdir, name)
    if using:
        agents = ", ".join(using)
        print(
            f"warning: the following agents reference role {name!r}: {agents}",
            file=sys.stderr,
        )
    path.unlink()
    print(f"Deleted {path}")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def add_parser(subparsers) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("role", help="Manage role YAML files")
    sub = p.add_subparsers(dest="role_cmd", metavar="<subcommand>")
    sub.required = True

    sub.add_parser("list", help="List all roles in .loguetown/roles/")

    show_p = sub.add_parser("show", help="Print resolved role YAML")
    show_p.add_argument("name", help="Role name")

    create_p = sub.add_parser("create", help="Scaffold a new role YAML")
    create_p.add_argument("name", help="Role name")

    edit_p = sub.add_parser("edit", help="Open role YAML in $EDITOR")
    edit_p.add_argument("name", help="Role name")

    delete_p = sub.add_parser("delete", help="Remove role file")
    delete_p.add_argument("name", help="Role name")

    p.set_defaults(func=_cli_handler)


def _cli_handler(args) -> None:  # type: ignore[type-arg]
    try:
        workdir = resolve_workdir()
    except WorkdirError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    cmd = args.role_cmd
    if cmd == "list":
        _cmd_list(workdir)
    elif cmd == "show":
        _cmd_show(workdir, args.name)
    elif cmd == "create":
        _cmd_create(workdir, args.name)
    elif cmd == "edit":
        _cmd_edit(workdir, args.name)
    elif cmd == "delete":
        _cmd_delete(workdir, args.name)
