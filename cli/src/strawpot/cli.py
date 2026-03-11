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
from strawpot.agents.interactive import (
    DirectWrapperRuntime,
    InteractiveWrapperRuntime,
)
from strawpot.agents.registry import parse_agent_md, resolve_agent, validate_agent
from strawpot.memory.registry import resolve_memory
from strawpot.agents.wrapper import WrapperRuntime
from strawpot.config import get_strawpot_home, load_config
from strawpot.session import Session, recover_stale_sessions, resolve_isolator


@click.group()
@click.version_option(version=__version__)
def cli():
    """StrawPot — lightweight agent orchestration."""


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------


def _get_agent_install_cmd(agent_dir: Path) -> str | None:
    """Read metadata.strawpot.install.<os> from AGENT.md frontmatter."""
    try:
        from strawpot.agents.registry import _current_os
        frontmatter, _ = parse_agent_md(agent_dir / "AGENT.md")
        install_map = frontmatter.get("metadata", {}).get("strawpot", {}).get("install", {})
        return install_map.get(_current_os())
    except (ValueError, OSError):
        return None


def _ensure_agent_installed(name: str, working_dir: str, *, auto_setup: bool = False) -> None:
    """Prompt to install an agent from StrawHub if it is not found locally."""
    try:
        resolve_agent(name, working_dir)
    except FileNotFoundError:
        pass  # not installed — continue to prompt
    except ValueError:
        pass  # installed but binary missing — need to run install script
    else:
        return  # already available

    # Check if agent files exist but binary is missing (needs install)
    agent_dirs = [
        Path(working_dir) / ".strawpot" / "agents" / name,
        get_strawpot_home() / "agents" / name,
    ]
    for agent_dir in agent_dirs:
        if (agent_dir / "AGENT.md").is_file():
            # 1. Try metadata.strawpot.install.<os> from AGENT.md frontmatter
            install_cmd = _get_agent_install_cmd(agent_dir)
            if install_cmd:
                click.echo(f"Running install for '{name}'...")
                result = subprocess.run(
                    ["sh", "-c", install_cmd],
                    cwd=str(agent_dir),
                    env={**os.environ, "INSTALL_DIR": str(agent_dir)},
                    stdin=sys.stdin,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                )
                if result.returncode != 0:
                    click.echo(f"Install failed for '{name}'.", err=True)
                return
            # 2. Fallback to install.sh on disk
            install_script = agent_dir / "install.sh"
            if install_script.is_file():
                click.echo(f"Running install script for '{name}'...")
                result = subprocess.run(
                    ["sh", str(install_script)],
                    cwd=str(agent_dir),
                    env={**os.environ, "INSTALL_DIR": str(agent_dir)},
                    stdin=sys.stdin,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                )
                if result.returncode != 0:
                    click.echo(f"Install script failed for '{name}'.", err=True)
                return
            click.echo(f"Agent '{name}' binary is missing and no install command found.", err=True)
            return

    if not auto_setup:
        if not click.confirm(
            f"Agent '{name}' is not installed. Install from StrawHub?", default=True
        ):
            return

    cmd = shutil.which("strawhub")
    if cmd is None:
        click.echo("Error: strawhub CLI not found on PATH.", err=True)
        click.echo("Install it with: pip install strawhub", err=True)
        return

    result = subprocess.run(
        [cmd, "install", "agent", name, "--global"],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        click.echo(f"Failed to install agent '{name}'.", err=True)
        return

    # Run install command from AGENT.md or fallback to install.sh
    global_agent_dir = get_strawpot_home() / "agents" / name
    install_cmd = _get_agent_install_cmd(global_agent_dir)
    if install_cmd:
        click.echo(f"Running install for '{name}'...")
        result = subprocess.run(
            ["sh", "-c", install_cmd],
            cwd=str(global_agent_dir),
            env={**os.environ, "INSTALL_DIR": str(global_agent_dir)},
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        if result.returncode != 0:
            click.echo(f"Install failed for '{name}'.", err=True)
    else:
        install_script = global_agent_dir / "install.sh"
        if install_script.is_file():
            click.echo(f"Running install script for '{name}'...")
            result = subprocess.run(
                ["sh", str(install_script)],
                cwd=str(global_agent_dir),
                env={**os.environ, "INSTALL_DIR": str(global_agent_dir)},
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            if result.returncode != 0:
                click.echo(f"Install script failed for '{name}'.", err=True)


def _ensure_skill_installed(name: str, working_dir: str, *, auto_setup: bool = False) -> None:
    """Prompt to install a skill from StrawHub if it is not found locally."""
    candidates = [
        Path(working_dir) / ".strawpot" / "skills" / name,
        get_strawpot_home() / "skills" / name,
    ]
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file():
            return  # already installed

    if not auto_setup:
        if not click.confirm(
            f"Skill '{name}' is not installed. Install from StrawHub?", default=True
        ):
            return

    cmd = shutil.which("strawhub")
    if cmd is None:
        click.echo("Error: strawhub CLI not found on PATH.", err=True)
        click.echo("Install it with: pip install strawhub", err=True)
        return

    result = subprocess.run(
        [cmd, "install", "skill", name, "--global"],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        click.echo(f"Failed to install skill '{name}'.", err=True)


def _ensure_memory_installed(name: str, working_dir: str, *, auto_setup: bool = False) -> None:
    """Prompt to install a memory provider from StrawHub if not found locally."""
    try:
        resolve_memory(name, working_dir)
    except FileNotFoundError:
        pass  # not installed — continue to prompt
    else:
        return  # already available

    if not auto_setup:
        if not click.confirm(
            f"Memory provider '{name}' is not installed. Install from StrawHub?",
            default=True,
        ):
            return

    cmd = shutil.which("strawhub")
    if cmd is None:
        click.echo("Error: strawhub CLI not found on PATH.", err=True)
        click.echo("Install it with: pip install strawhub", err=True)
        return

    result = subprocess.run(
        [cmd, "install", "memory", name, "--global"],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        click.echo(f"Failed to install memory provider '{name}'.", err=True)


def _ensure_role_installed(name: str, working_dir: str, *, auto_setup: bool = False) -> None:
    """Prompt to install a role from StrawHub if it is not found locally."""
    candidates = [
        Path(working_dir) / ".strawpot" / "roles" / name,
        get_strawpot_home() / "roles" / name,
    ]
    for candidate in candidates:
        if (candidate / "ROLE.md").is_file():
            return  # already installed

    if not auto_setup:
        if not click.confirm(
            f"Role '{name}' is not installed. Install from StrawHub?", default=True
        ):
            return

    cmd = shutil.which("strawhub")
    if cmd is None:
        click.echo("Error: strawhub CLI not found on PATH.", err=True)
        click.echo("Install it with: pip install strawhub", err=True)
        return

    result = subprocess.run(
        [cmd, "install", "role", name, "--global"],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        click.echo(f"Failed to install role '{name}'.", err=True)


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
@click.option("--task", default=None, help="Run noninteractively with a task string.")
@click.option(
    "--headless",
    is_flag=True,
    default=False,
    help="Run detached with output to log file (requires --task).",
)
@click.option("--run-id", "run_id", default=None, help="Pre-assigned run ID (used by GUI).")
@click.option("--system-prompt", "system_prompt", default=None, help="Custom system prompt appended to role instructions.")
@click.option("--no-cache-delegations", "no_cache_delegations", is_flag=True, default=False, help="Disable caching of delegation results within the session.")
@click.option("--cache-max-entries", "cache_max_entries", type=int, default=None, help="Max cached delegation results (0 = unlimited).")
@click.option("--cache-ttl-seconds", "cache_ttl_seconds", type=int, default=None, help="Max age in seconds for cached results (0 = unlimited).")
@click.option("--memory", "memory_override", default=None, help="Memory provider to use (overrides config).")
@click.option("--max-num-delegations", "max_num_delegations", type=int, default=None, help="Max delegation calls per session (0 = unlimited).")
def start(role, runtime, isolation, merge_strategy, pull, host, port, task, headless, run_id, system_prompt, no_cache_delegations, cache_max_entries, cache_ttl_seconds, memory_override, max_num_delegations):
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
    if no_cache_delegations:
        config.cache_delegations = False
    if cache_max_entries is not None:
        config.cache_max_entries = cache_max_entries
    if cache_ttl_seconds is not None:
        config.cache_ttl_seconds = cache_ttl_seconds
    if memory_override is not None:
        config.memory = memory_override
    if max_num_delegations is not None:
        config.max_num_delegations = max_num_delegations
    if host or port:
        current_host, current_port = config.denden_addr.rsplit(":", 1)
        config.denden_addr = f"{host or current_host}:{port or current_port}"

    working_dir = str(Path.cwd())

    # 0. Recover stale sessions from previous crashes
    recovered = recover_stale_sessions(working_dir, config)
    for rid in recovered:
        click.echo(f"Recovered stale session: {rid}")

    # 0b. Auto-install default dependencies if not found
    _ensure_agent_installed(config.runtime, working_dir, auto_setup=headless)
    _ensure_skill_installed("denden", working_dir, auto_setup=headless)
    _ensure_role_installed(config.orchestrator_role, working_dir, auto_setup=headless)
    _ensure_role_installed("ai-employee", working_dir, auto_setup=headless)
    if config.memory:
        _ensure_memory_installed(config.memory, working_dir, auto_setup=headless)

    # 1. Resolve agent spec
    try:
        spec = resolve_agent(
            config.runtime, working_dir, config.agents.get(config.runtime)
        )
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    # 2. Validate agent dependencies
    validation = validate_agent(spec)
    if validation.missing_tools:
        click.echo("Missing required tools:", err=True)
        for tool, hint in validation.missing_tools:
            msg = f"  - {tool}"
            if hint:
                msg += f"  (install: {hint})"
            click.echo(msg, err=True)
        sys.exit(1)

    if validation.missing_env:
        if headless:
            click.echo(
                f"Error: missing environment variables: {', '.join(validation.missing_env)}",
                err=True,
            )
            sys.exit(1)
        for var in validation.missing_env:
            value = click.prompt(f"Enter value for {var}")
            os.environ[var] = value

    # 2b. Validate skill env requirements for orchestrator role
    try:
        from strawhub.resolver import resolve as _resolve

        from strawpot.delegation import (
            _collect_saved_env,
            _get_default_agent,
            collect_skill_env,
            discover_global_skills,
            validate_skill_env,
        )

        resolved = _resolve(config.orchestrator_role, kind="role")
        global_skills = discover_global_skills(resolved)
        skill_env = collect_skill_env(resolved, global_skills=global_skills or None)
        saved_env = _collect_saved_env(config, resolved, global_skills=global_skills or None)
        skill_validation = validate_skill_env(skill_env, saved_env=saved_env)

        if skill_validation.missing_env:
            if headless:
                click.echo(
                    f"Error: missing skill environment variables: "
                    f"{', '.join(skill_validation.missing_env)}",
                    err=True,
                )
                sys.exit(1)
            for var in skill_validation.missing_env:
                desc = skill_env[var].get("description", "")
                prompt_text = f"Enter value for {var}"
                if desc:
                    prompt_text += f" ({desc})"
                value = click.prompt(prompt_text)
                os.environ[var] = value

        # 2c. Check orchestrator role's default_agent (config > frontmatter)
        # Only apply when no explicit --runtime flag was given.
        if not runtime:
            orch_role_cfg = config.roles.get(config.orchestrator_role, {})
            orch_default_agent = orch_role_cfg.get(
                "default_agent", _get_default_agent(resolved["path"])
            )
        else:
            orch_default_agent = None
        if orch_default_agent and orch_default_agent != config.runtime:
            try:
                spec = resolve_agent(
                    orch_default_agent,
                    working_dir,
                    config.agents.get(orch_default_agent),
                )
                config.runtime = orch_default_agent
            except FileNotFoundError:
                click.echo(
                    f"Warning: default_agent '{orch_default_agent}' not found "
                    f"for role '{config.orchestrator_role}'; "
                    f"using '{config.runtime}'",
                    err=True,
                )
    except Exception:
        pass  # Role resolution failures handled by Session.start()

    # 3. Build runtimes (session_dir set later by Session.start())
    if headless and not task:
        click.echo("Error: --headless requires --task", err=True)
        sys.exit(1)

    if run_id and not run_id.startswith("run_"):
        click.echo("Error: --run-id must start with 'run_'", err=True)
        sys.exit(1)

    wrapper = WrapperRuntime(spec)
    if headless:
        rt = wrapper  # WrapperRuntime directly → output to .log file
    elif task:
        rt = DirectWrapperRuntime(wrapper)
    elif shutil.which("tmux"):
        rt = InteractiveWrapperRuntime(wrapper)
    else:
        rt = DirectWrapperRuntime(wrapper)

    # 4. Isolator
    isolator = resolve_isolator(config.isolation)

    # 5. Resolver callables (lazy import strawhub)
    def _resolve_role(slug, kind="role"):
        from strawhub.resolver import resolve

        return resolve(slug, kind=kind)

    def _resolve_role_dirs(slug):
        from strawhub.resolver import resolve

        try:
            return resolve(slug, kind="role").get("path")
        except Exception:
            return None

    # 6. Create and run session
    session = Session(
        config=config,
        wrapper=wrapper,
        runtime=rt,
        isolator=isolator,
        resolve_role=_resolve_role,
        resolve_role_dirs=_resolve_role_dirs,
        task=task or "",
        run_id=run_id,
        headless=headless,
        system_prompt=system_prompt or "",
    )
    session.start(working_dir)


@cli.command(name="config")
def show_config():
    """Show merged configuration."""
    config = load_config(Path.cwd())
    click.echo(f"runtime:              {config.runtime}")
    click.echo(f"isolation:            {config.isolation}")
    click.echo(f"denden_addr:          {config.denden_addr}")
    click.echo(f"orchestrator_role:    {config.orchestrator_role}")
    click.echo(f"permission_mode:      {config.permission_mode}")
    click.echo(f"max_depth:            {config.max_depth}")
    click.echo(f"agent_timeout:        {config.agent_timeout}")
    click.echo(f"merge_strategy:       {config.merge_strategy}")
    click.echo(f"pull_before_session:  {config.pull_before_session}")
    click.echo(f"pr_command:           {config.pr_command}")
    click.echo(f"agents:               {config.agents}")
    click.echo(f"skills:               {config.skills}")
    click.echo(f"roles:                {config.roles}")


def _sessions_dir() -> Path:
    """Return the sessions directory, searching CWD then global."""
    local = Path.cwd() / ".strawpot" / "sessions"
    if local.is_dir():
        return local
    return get_strawpot_home() / "sessions"


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
    running_path = sessions_path.parent / "running"
    if not running_path.is_dir():
        click.echo("No sessions found.")
        return

    entries = sorted(running_path.iterdir())
    if not entries:
        click.echo("No sessions found.")
        return

    # Header
    click.echo(f"{'RUN ID':<20} {'STATUS':<8} {'ISOLATION':<10} {'RUNTIME':<14} {'DENDEN':<20} {'UPTIME':<10}")
    click.echo("-" * 82)

    for entry in entries:
        if not entry.name.startswith("run_"):
            continue
        session_file = sessions_path / entry.name / "session.json"
        data = _load_session(session_file)
        if data is None:
            continue
        run_id = data.get("run_id", entry.name)
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
    session_file = sessions_path / session_id / "session.json"
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
# GUI
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--port", default=None, type=int, help="Port for GUI server (default: 8741).")
def gui(port):
    """Launch the StrawPot web dashboard."""
    try:
        from strawpot_gui.server import DEFAULT_PORT
        from strawpot_gui.server import main as gui_main
    except ImportError:
        click.echo("Error: strawpot-gui package is not installed.", err=True)
        click.echo("Install it with: pip install strawpot-gui", err=True)
        sys.exit(1)

    gui_main(port=port or DEFAULT_PORT)


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


def _make_passthrough(strawhub_cmd: str, help_text: str):
    """Create a click command that forwards all args to strawhub."""

    @click.command(
        name=strawhub_cmd,
        help=help_text,
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    )
    @click.pass_context
    def cmd(ctx):
        _strawhub(strawhub_cmd, *ctx.args)

    return cmd


# Package management
cli.add_command(_make_passthrough("install", "Install a skill, role, agent, or memory from StrawHub."))
cli.add_command(_make_passthrough("uninstall", "Remove an installed skill, role, agent, or memory."))
cli.add_command(_make_passthrough("update", "Update installed packages to latest versions."))
cli.add_command(_make_passthrough("init", "Create strawpot.toml from installed packages."))
cli.add_command(_make_passthrough("install-tools", "Install system tools declared by packages."))

# Discovery
cli.add_command(_make_passthrough("search", "Search the StrawHub registry."))
cli.add_command(_make_passthrough("list", "Browse skills, roles, agents, and memories on the registry."))
cli.add_command(_make_passthrough("info", "Show detailed information about a package."))
cli.add_command(_make_passthrough("resolve", "Resolve a slug to its installed path."))

# Publishing
cli.add_command(_make_passthrough("publish", "Publish a skill, role, agent, or memory to StrawHub."))

# Authentication
cli.add_command(_make_passthrough("login", "Authenticate with the StrawHub registry."))
cli.add_command(_make_passthrough("logout", "Remove stored StrawHub credentials."))
cli.add_command(_make_passthrough("whoami", "Show current authenticated user."))
