"""lt skills — manage skill module directories.

Skills are folder-based modules.  Each skill is a directory under a pool:

    global  → ~/.strawpot/skills/<module>/
    project → <workdir>/.strawpot/skills/<module>/
    agent   → <workdir>/.strawpot/skills/<agent-name>/<module>/

Commands::

    lt skills list                          # global + project (project view, default)
    lt skills list --global                 # only global pool
    lt skills list --agent <name>           # global + project + agent (full agent view)

    lt skills install <module>              # scaffold in project pool (default)
    lt skills install --global <module>     # scaffold in global pool
    lt skills install --agent <name> <module>

    lt skills remove <module>               # remove from project pool (default)
    lt skills remove --global <module>
    lt skills remove --agent <name> <module>

    lt skills edit <module>                 # open module in $EDITOR (project pool)
    lt skills edit --global <module>
    lt skills edit --agent <name> <module>

    lt skills show <module>                 # print all .md content (project pool)
    lt skills show --global <module>
    lt skills show --agent <name> <module>
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from core.skills.loader import SkillsLoader
from core.skills.types import PoolScope, SkillPool
from core.workdir import WorkdirError, resolve_workdir

_GLOBAL_ROOT = Path.home() / ".strawpot"

# ---------------------------------------------------------------------------
# Pool resolution
# ---------------------------------------------------------------------------


def _pool_path(
    scope: PoolScope,
    workdir: Path | None,
    agent_name: str | None,
    global_root: Path,
) -> Path:
    if scope == "global":
        return global_root / "skills"
    if scope == "project":
        assert workdir is not None
        return workdir / ".strawpot" / "skills"
    # agent
    assert workdir is not None and agent_name is not None
    return workdir / ".strawpot" / "skills" / agent_name


def _resolve_target_pool(
    args,  # type: ignore[type-arg]
    workdir: Path | None,
    global_root: Path,
) -> tuple[PoolScope, Path]:
    """Return (scope, pool_path) based on CLI flags."""
    if getattr(args, "global_flag", False):
        return "global", global_root / "skills"
    agent = getattr(args, "agent", None)
    if agent:
        if workdir is None:
            raise WorkdirError("--agent requires a strawpot project directory")
        return "agent", workdir / ".strawpot" / "skills" / agent
    # Default: project pool
    if workdir is None:
        raise WorkdirError("project pool requires a strawpot project directory")
    return "project", workdir / ".strawpot" / "skills"




# ---------------------------------------------------------------------------
# Sub-command: list
# ---------------------------------------------------------------------------


def _cmd_list(
    workdir: Path | None,
    global_only: bool,
    agent_name: str | None,
    global_root: Path,
) -> None:
    """Enumerate skill modules across relevant pools."""
    # Determine which pools to show
    pools: list[tuple[str, Path]] = []

    if global_only:
        pools.append(("GLOBAL", global_root / "skills"))
    elif agent_name:
        if workdir is None:
            print("error: --agent requires a strawpot project directory", file=sys.stderr)
            sys.exit(1)
        pools.append(("GLOBAL", global_root / "skills"))
        pools.append(("PROJECT", workdir / ".strawpot" / "skills"))
        pools.append((f"AGENT ({agent_name})", workdir / ".strawpot" / "skills" / agent_name))
    else:
        # Default project view: global + project
        if workdir is None:
            print("error: not in a strawpot project (no .strawpot/ found)", file=sys.stderr)
            sys.exit(1)
        pools.append(("GLOBAL", global_root / "skills"))
        pools.append(("PROJECT", workdir / ".strawpot" / "skills"))

    found_any = False
    for label, pool_path in pools:
        pool = SkillPool(path=pool_path, scope="project")  # scope unused for display
        modules = SkillsLoader.list_modules(pool)
        if not modules:
            continue
        found_any = True
        print(f"\n{label} ({pool_path})")
        for mod in modules:
            desc = SkillsLoader.module_description(mod)
            name_col = f"  {mod.name:<30}"
            print(f"{name_col}{desc}" if desc else f"  {mod.name}")

    if not found_any:
        print("No skill modules found.")


# ---------------------------------------------------------------------------
# Sub-command: install
# ---------------------------------------------------------------------------

_STARTER_README = """\
# {title}

<!-- Describe this skill module here. -->
"""


def _cmd_install(
    module: str,
    scope: PoolScope,
    pool_path: Path,
) -> None:
    mod_dir = pool_path / module
    if mod_dir.exists():
        print(f"error: skill module {module!r} already exists at {mod_dir}", file=sys.stderr)
        sys.exit(1)
    mod_dir.mkdir(parents=True, exist_ok=True)

    # Create a starter README.md
    title = module.replace("-", " ").replace("_", " ").title()
    readme = mod_dir / "README.md"
    readme.write_text(_STARTER_README.format(title=title))

    print(f"Created skill module: {mod_dir}")
    print(f"  Edit {readme} to add your skill content.")


# ---------------------------------------------------------------------------
# Sub-command: remove
# ---------------------------------------------------------------------------


def _cmd_remove(module: str, scope: PoolScope, pool_path: Path) -> None:
    mod_dir = pool_path / module
    if not mod_dir.exists():
        print(
            f"error: skill module {module!r} not found in {pool_path}",
            file=sys.stderr,
        )
        sys.exit(1)
    shutil.rmtree(mod_dir)
    print(f"Removed skill module: {mod_dir}")


# ---------------------------------------------------------------------------
# Sub-command: edit
# ---------------------------------------------------------------------------


def _cmd_edit(module: str, scope: PoolScope, pool_path: Path) -> None:
    mod_dir = pool_path / module
    if not mod_dir.exists():
        print(
            f"error: skill module {module!r} not found in {pool_path}\n"
            f"Run 'lt skills install {module}' to create it.",
            file=sys.stderr,
        )
        sys.exit(1)

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        print(
            f"error: $EDITOR is not set. Edit the module manually: {mod_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Prefer README.md, then first .md file, then the directory itself
    target: Path = mod_dir
    readme = mod_dir / "README.md"
    if readme.exists():
        target = readme
    else:
        mds = sorted(mod_dir.glob("*.md"))
        if mds:
            target = mds[0]

    subprocess.run([editor, str(target)], check=False)


# ---------------------------------------------------------------------------
# Sub-command: show
# ---------------------------------------------------------------------------


def _cmd_show(module: str, scope: PoolScope, pool_path: Path) -> None:
    mod_dir = pool_path / module
    if not mod_dir.exists():
        print(
            f"error: skill module {module!r} not found in {pool_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    skill_files = SkillsLoader.list_files(mod_dir)
    if not skill_files:
        print(f"No .md files found in {mod_dir}")
        return

    for i, sf in enumerate(skill_files):
        if i > 0:
            print("\n" + "─" * 60 + "\n")
        rel = sf.path.relative_to(mod_dir)
        print(f"# {rel}\n")
        print(sf.content)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def add_parser(subparsers) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser("skills", help="Manage skill module directories")
    sub = p.add_subparsers(dest="skills_cmd", metavar="<subcommand>")
    sub.required = True

    # -- list --
    list_p = sub.add_parser("list", help="List skill modules across pools")
    scope_group = list_p.add_mutually_exclusive_group()
    scope_group.add_argument(
        "--global",
        dest="global_flag",
        action="store_true",
        help="Show only global pool (~/.strawpot/skills/)",
    )
    scope_group.add_argument(
        "--agent",
        metavar="NAME",
        help="Show global + project + agent pools for this agent",
    )

    # -- install --
    install_p = sub.add_parser("install", help="Scaffold a new skill module")
    install_p.add_argument("module", help="Module directory name (e.g. react-patterns)")
    scope_grp_i = install_p.add_mutually_exclusive_group()
    scope_grp_i.add_argument(
        "--global",
        dest="global_flag",
        action="store_true",
        help="Install into global pool (~/.strawpot/skills/)",
    )
    scope_grp_i.add_argument(
        "--agent",
        metavar="NAME",
        help="Install into agent pool",
    )

    # -- remove --
    remove_p = sub.add_parser("remove", help="Remove a skill module")
    remove_p.add_argument("module", help="Module directory name")
    scope_grp_r = remove_p.add_mutually_exclusive_group()
    scope_grp_r.add_argument(
        "--global",
        dest="global_flag",
        action="store_true",
    )
    scope_grp_r.add_argument("--agent", metavar="NAME")

    # -- edit --
    edit_p = sub.add_parser("edit", help="Open skill module in $EDITOR")
    edit_p.add_argument("module", help="Module directory name")
    scope_grp_e = edit_p.add_mutually_exclusive_group()
    scope_grp_e.add_argument("--global", dest="global_flag", action="store_true")
    scope_grp_e.add_argument("--agent", metavar="NAME")

    # -- show --
    show_p = sub.add_parser("show", help="Print all .md content in a module")
    show_p.add_argument("module", help="Module directory name")
    scope_grp_s = show_p.add_mutually_exclusive_group()
    scope_grp_s.add_argument("--global", dest="global_flag", action="store_true")
    scope_grp_s.add_argument("--agent", metavar="NAME")

    p.set_defaults(func=_cli_handler)


def _cli_handler(args) -> None:  # type: ignore[type-arg]
    global_root = Path.home() / ".strawpot"

    # Resolve workdir — non-fatal for global-only operations
    workdir: Path | None = None
    if not getattr(args, "global_flag", False):
        try:
            workdir = resolve_workdir()
        except WorkdirError:
            pass  # will fail later if project/agent pool is needed

    cmd = args.skills_cmd

    if cmd == "list":
        _cmd_list(
            workdir=workdir,
            global_only=getattr(args, "global_flag", False),
            agent_name=getattr(args, "agent", None),
            global_root=global_root,
        )
        return

    # All other commands need a specific pool
    try:
        scope, pool_path = _resolve_target_pool(args, workdir=workdir, global_root=global_root)
    except WorkdirError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    module = args.module
    if cmd == "install":
        _cmd_install(module=module, scope=scope, pool_path=pool_path)
    elif cmd == "remove":
        _cmd_remove(module=module, scope=scope, pool_path=pool_path)
    elif cmd == "edit":
        _cmd_edit(module=module, scope=scope, pool_path=pool_path)
    elif cmd == "show":
        _cmd_show(module=module, scope=scope, pool_path=pool_path)
