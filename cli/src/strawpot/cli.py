"""StrawPot CLI — agent orchestration commands + strawhub passthrough."""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------
# Grouped help -- shows "Getting Started" commands first in --help
# ---------------------------------------------------------------------------

_COMMAND_GROUPS: list[tuple[str, list[str]]] = [
    ("Getting Started", ["start", "quickstart", "doctor", "gui"]),
    ("Sessions", ["sessions", "agents", "config"]),
    ("Package Management", ["install", "uninstall", "update", "init", "install-tools"]),
    ("Discovery", ["search", "list", "info", "resolve"]),
    ("Publishing", ["publish"]),
    ("Authentication", ["login", "logout", "whoami"]),
    ("Maintenance", ["upgrade"]),
]


class GroupedGroup(click.Group):
    """A Click group that displays commands organized by category in --help."""

    def format_commands(self, ctx, formatter):
        commands = {}
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None or cmd.hidden:
                continue
            commands[subcommand] = cmd
        if not commands:
            return
        grouped = set()
        for group_name, group_cmds in _COMMAND_GROUPS:
            rows = []
            for name in group_cmds:
                if name in commands:
                    rows.append((name, commands[name].get_short_help_str(limit=150)))
                    grouped.add(name)
            if rows:
                with formatter.section(group_name):
                    formatter.write_dl(rows)
        remaining = [(n, commands[n].get_short_help_str(limit=150))
                     for n in sorted(commands) if n not in grouped]
        if remaining:
            with formatter.section("Other"):
                formatter.write_dl(remaining)


def _strawhub_cmd() -> list[str] | None:
    """Locate the strawhub CLI. Returns the command prefix list, or None."""
    path = shutil.which("strawhub")
    if path:
        return [path]
    # pipx only exposes the main package's entry points on PATH, so strawhub
    # (a dependency) won't be found by shutil.which even though it's installed
    # in the same venv.  Fall back to running it as a Python module.
    try:
        subprocess.run(
            [sys.executable, "-m", "strawhub", "--version"],
            capture_output=True,
            check=True,
        )
        return [sys.executable, "-m", "strawhub"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

from strawpot import __version__
from strawpot._process import is_pid_alive
from strawpot.agents.interactive import (
    DirectWrapperRuntime,
    InteractiveWrapperRuntime,
)
from strawpot.agents.registry import (
    check_install_prerequisites,
    parse_agent_md,
    resolve_agent,
    validate_agent,
)
from strawpot.memory.registry import resolve_memory
from strawpot.agents.wrapper import WrapperRuntime
from strawpot.config import get_strawpot_home, has_explicit_runtime, load_config
from strawpot.session import Session, recover_stale_sessions, resolve_isolator


HELP_EPILOG = """\nDocs: https://docs.strawpot.com\n"""

_FIRST_RUN_MARKER = ".first_run_done"


def _first_run_marker_path() -> Path:
    """Return the path to the first-run marker file."""
    return get_strawpot_home() / _FIRST_RUN_MARKER


def _show_first_run_banner() -> None:
    """Show a welcome banner on first run, then create the marker file."""
    marker = _first_run_marker_path()
    if marker.exists():
        return
    click.echo()
    click.echo(click.style("Welcome to StrawPot!", fg="green", bold=True))
    click.echo()
    click.echo("  Get started: run " + click.style("strawpot start", bold=True) + " to launch your first agent.")
    click.echo("  Need help?   run " + click.style("strawpot quickstart", bold=True) + " for a step-by-step guide.")
    click.echo()
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        marker.touch()
    except OSError:
        pass  # Non-fatal -- banner will show again next time



@click.group(cls=GroupedGroup, epilog=HELP_EPILOG)
@click.version_option(version=__version__)
def cli():
    """StrawPot — AI agent orchestration.

    Compose AI agents that delegate tasks, share memory, and coordinate
    through roles and skills. Works with Claude Code, Codex, Gemini,
    and more.
    """
    _show_first_run_banner()

# ---------------------------------------------------------------------------
# Quickstart guide
# ---------------------------------------------------------------------------

_QUICKSTART_TEXT = """\
{header}

{step1}  Check prerequisites
   Run {doctor} to verify your system has the required tools
   (Node.js, npm, git).

{step2}  Launch your first agent
   Run {start} to pick an agent runtime (Claude Code, Gemini,
   or Codex), install it, and start an interactive session.

{step3}  Run a task non-interactively
   Pass a task string to skip the interactive prompt:
   {task_example}

{step4}  Open the web dashboard
   Run {gui} to launch the StrawPot GUI in your browser.

{step5}  Install packages from StrawHub
   Browse available roles, skills, and agents:
   {search_example}

   Install a package:
   {install_example}

{step6}  Learn more
   Documentation:  https://docs.strawpot.com
   GitHub:         https://github.com/strawpot/strawpot
"""


@cli.command()
def quickstart():
    """Print a step-by-step getting-started guide."""
    click.echo(
        _QUICKSTART_TEXT.format(
            header=click.style("StrawPot -- Quick Start Guide", bold=True),
            step1=click.style("1.", bold=True),
            step2=click.style("2.", bold=True),
            step3=click.style("3.", bold=True),
            step4=click.style("4.", bold=True),
            step5=click.style("5.", bold=True),
            step6=click.style("6.", bold=True),
            doctor=click.style("strawpot doctor", bold=True),
            start=click.style("strawpot start", bold=True),
            task_example=click.style('strawpot start --task "Fix the login bug"', bold=True),
            gui=click.style("strawpot gui", bold=True),
            search_example=click.style("strawpot search role", bold=True),
            install_example=click.style("strawpot install role ai-ceo", bold=True),
        )
    )


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


_SEEDED_AGENTS = [
    ("strawpot-claude-code", "Anthropic Claude Code — requires Anthropic account or API key"),
    ("strawpot-gemini", "Google Gemini CLI — requires Google account or API key"),
    ("strawpot-codex", "OpenAI Codex CLI — requires OpenAI API key"),
]


def needs_onboarding(config, working_dir: str) -> bool:
    """Return True when the first-run onboarding wizard should be shown.

    Conditions (all must be true):
    1. No explicit ``runtime`` in any config file (global or project).
    2. The default agent is not installed locally.
    3. Session is interactive (caller checks ``--headless`` separately).
    """
    if has_explicit_runtime(Path(working_dir)):
        return False
    try:
        resolve_agent(config.runtime, working_dir)
        return False  # default agent already installed
    except (FileNotFoundError, ValueError):
        return True


def _pick_agent() -> str | None:
    """Display the agent picker and return the selected agent name.

    Returns ``None`` if the user cancels (Ctrl-C or invalid input).
    """
    click.echo("Choose your default agent:")
    for i, (name, desc) in enumerate(_SEEDED_AGENTS, 1):
        rec = " (recommended)" if i == 1 else ""
        click.echo(f"  {i}) {name}{rec} — {desc}")

    raw = click.prompt(f"Enter number (1-{len(_SEEDED_AGENTS)})", default="1")
    try:
        idx = int(raw)
        if 1 <= idx <= len(_SEEDED_AGENTS):
            return _SEEDED_AGENTS[idx - 1][0]
    except ValueError:
        pass
    click.echo(f"Invalid selection: {raw}", err=True)
    return None


def _authenticate_agent(agent_name: str, working_dir: str) -> None:
    """Offer login-session or API-key auth for a newly installed agent."""
    try:
        spec = resolve_agent(agent_name, working_dir)
    except ValueError as exc:
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + f"Agent binary not available: {exc}\n\n"
            "Skipping authentication — the agent runtime is not installed.\n"
            "Run 'strawpot doctor' to diagnose, then 'strawpot start' to retry.",
            err=True,
        )
        return

    env_vars = list(spec.env_schema.keys())
    has_env = bool(env_vars)

    click.echo("\nHow would you like to authenticate?")
    click.echo("  1) Login session (interactive browser/CLI login)")
    if has_env:
        click.echo(f"  2) API key ({', '.join(env_vars)})")
        click.echo("  3) Skip (configure later)")
        raw = click.prompt("Enter choice", default="1")
    else:
        click.echo("  2) Skip (configure later)")
        raw = click.prompt("Enter choice", default="1")

    choice = raw.strip()

    if choice == "1":
        runtime = WrapperRuntime(spec)
        if not runtime.setup():
            click.echo(
                "Login failed. You can retry later with: strawpot start",
                err=True,
            )
    elif choice == "2" and has_env:
        env_values: dict[str, str] = {}
        for var, meta in spec.env_schema.items():
            desc = meta.get("description", "")
            prompt_text = f"Enter {var}"
            if desc:
                prompt_text += f" ({desc})"
            value = click.prompt(prompt_text, hide_input=True)
            os.environ[var] = value
            env_values[var] = value
        if env_values:
            from strawpot.config import save_resource_config

            save_resource_config(
                None, "agents", agent_name, env_values=env_values
            )
            click.echo("Saved credentials to global config.")
    else:
        click.echo(
            "Skipping authentication. Run 'strawpot start' to configure later."
        )


def _check_system_prerequisites() -> list[tuple[str, str]]:
    """Check that basic system tools required by agent installs are on PATH.

    Returns a list of ``(tool_name, guidance)`` tuples for missing tools.
    Empty list when everything is present.
    """
    from strawpot.doctor import check_prerequisites

    report = check_prerequisites()
    return [(c.name, c.hint) for c in report.missing_required]


def _print_missing_prerequisites(
    missing: list[tuple[str, str]],
    *,
    footer: str = "",
) -> None:
    """Print a formatted list of missing system prerequisites to stderr."""
    click.echo(
        click.style("Missing system prerequisites:", fg="red", bold=True),
        err=True,
    )
    for tool, guidance in missing:
        click.echo(f"  - {tool}: {guidance}", err=True)
    if footer:
        click.echo(f"\n{footer}", err=True)


def _onboarding_wizard(working_dir: str) -> str | None:
    """Run the first-run onboarding wizard.

    Returns the selected agent name so the caller can continue with a
    normal start/gui flow, or ``None`` if the user cancelled.
    """
    click.echo("Welcome to StrawPot! Let's set up your first agent.\n")

    # Step 1: Pre-flight check for system tools
    missing_tools = _check_system_prerequisites()
    if missing_tools:
        _print_missing_prerequisites(
            missing_tools,
            footer="Install the missing tools above, then run 'strawpot start' again.",
        )
        return None

    # Step 2: Agent selection
    agent_name = _pick_agent()
    if agent_name is None:
        return None

    click.echo(f"\nSelected: {agent_name}")

    # Step 3: Install agent wrapper from StrawHub
    _ensure_agent_installed(agent_name, working_dir, auto_setup=True)

    # Step 3b: Verify the agent binary resolved after install
    try:
        resolve_agent(agent_name, working_dir)
    except ValueError as exc:
        click.echo(
            click.style("\nError: ", fg="red", bold=True)
            + "The agent package was installed but its runtime binary is missing.\n\n"
            + f"{exc}\n\n"
            "Run 'strawpot doctor' to check all prerequisites, then "
            "'strawpot start' to retry.",
            err=True,
        )
        return None
    except FileNotFoundError:
        pass  # Will be caught downstream by the start() handler

    # Step 4: Authentication
    _authenticate_agent(agent_name, working_dir)

    # Step 7: Save default runtime to global config
    from strawpot.config import save_resource_config

    save_resource_config(None, "agents", agent_name)

    # Persist runtime choice to global strawpot.toml
    import tomli_w

    from strawpot.config import _read_toml

    global_toml = get_strawpot_home() / "strawpot.toml"
    data = _read_toml(global_toml)
    data["runtime"] = agent_name
    global_toml.parent.mkdir(parents=True, exist_ok=True)
    with open(global_toml, "wb") as f:
        tomli_w.dump(data, f)

    click.echo(f"Saved runtime = \"{agent_name}\" to {global_toml}\n")

    return agent_name


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------


def _get_agent_install_cmd(agent_dir: Path) -> str | None:
    """Read metadata.strawpot.install.<os> from AGENT.md frontmatter."""
    try:
        from strawpot.agents.registry import _current_os
        frontmatter, _ = parse_agent_md(agent_dir / "AGENT.md")
        meta = frontmatter.get("metadata") or {}
        sp = meta.get("strawpot") if isinstance(meta, dict) else {}
        install_map = (sp or {}).get("install", {})
        return install_map.get(_current_os())
    except (ValueError, OSError):
        return None


# Pattern: curl [flags] <URL> | sh [args]
_CURL_PIPE_SH_RE = re.compile(
    r"^curl\s+[^|]*?(https?://\S+)\s*\|\s*sh\b.*$"
)


def _download_script(url: str, *, timeout: float = 30) -> bytes:
    """Download a script from *url* using Python's urllib.

    Returns the raw response bytes.

    Raises:
        RuntimeError: If the download fails for any reason.
    """
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "strawpot"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"Failed to download {url}: {exc}") from exc


def _run_install_for_agent(
    agent_dir: Path, name: str, *, loud: bool = True,
) -> bool:
    """Run the install script for an agent and return True on success.

    Tries, in order:
        1. ``metadata.strawpot.install.<os>`` from AGENT.md — if the command
           is a ``curl ... | sh`` pipeline, download the script with Python's
           stdlib urllib and pipe it to ``sh``, eliminating the ``curl``
           dependency.
        2. ``install.sh`` on disk.

    Returns False (and prints to stderr) if the install fails or no install
    method is found.  Also returns False when required system tools (e.g.
    ``node``, ``npm``) are missing — the caller should abort gracefully.

    When *loud* is False the prerequisite error banner is suppressed. Use
    this on code paths where a failed install is non-fatal.
    """
    # Pre-flight: check system prerequisites declared in AGENT.md
    missing = check_install_prerequisites(agent_dir)
    if missing:
        if loud:
            _print_missing_prerequisites(
                missing,
                footer=(
                    "Install the missing tools above, then run "
                    "`strawpot start` again.\n"
                    "Run `strawpot doctor` for a full system check."
                ),
            )
        return False

    env = {**os.environ, "INSTALL_DIR": str(agent_dir)}
    run_kw = dict(cwd=str(agent_dir), env=env, stdout=sys.stdout, stderr=sys.stderr)

    # 1. Try metadata.strawpot.install.<os>
    install_cmd = _get_agent_install_cmd(agent_dir)
    if install_cmd:
        # Prefer Python-native download over shelling out to curl
        match = _CURL_PIPE_SH_RE.match(install_cmd.strip())
        if match:
            url = match.group(1)
            click.echo(f"Downloading install script for '{name}'...")
            try:
                script_bytes = _download_script(url)
            except RuntimeError as exc:
                click.echo(str(exc), err=True)
                return False
            click.echo(f"Running install for '{name}'...")
            result = subprocess.run(["sh"], input=script_bytes, **run_kw)
        else:
            click.echo(f"Running install for '{name}'...")
            result = subprocess.run(
                ["sh", "-c", install_cmd], stdin=sys.stdin, **run_kw,
            )
        if result.returncode != 0:
            click.echo(f"Install failed for '{name}'.", err=True)
            return False
        return True

    # 2. Fallback to install.sh on disk
    install_script = agent_dir / "install.sh"
    if install_script.is_file():
        click.echo(f"Running install script for '{name}'...")
        result = subprocess.run(
            ["sh", str(install_script)], stdin=sys.stdin, **run_kw,
        )
        if result.returncode != 0:
            click.echo(f"Install script failed for '{name}'.", err=True)
            return False
        return True

    click.echo(f"Agent '{name}' binary is missing and no install command found.", err=True)
    return False


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
            if not _run_install_for_agent(agent_dir, name):
                sys.exit(1)
            return

    if not auto_setup:
        if not click.confirm(
            f"Agent '{name}' is not installed. Install from StrawHub?", default=True
        ):
            return

    cmd = _strawhub_cmd()
    if cmd is None:
        click.echo("Error: strawhub CLI not found.", err=True)
        click.echo("Install it with: pip install strawhub", err=True)
        return

    strawhub_install_cmd = [*cmd, "install", "agent", name, "--global"]
    if auto_setup:
        strawhub_install_cmd.append("--yes")
    result = subprocess.run(
        strawhub_install_cmd,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        click.echo(f"Failed to install agent '{name}'.", err=True)
        return

    # Run install command from AGENT.md or fallback to install.sh.
    # Failure here is not fatal — strawhub may have already installed the
    # binary.  The subsequent resolve_agent() in start() will catch real
    # errors.
    global_agent_dir = get_strawpot_home() / "agents" / name
    _run_install_for_agent(global_agent_dir, name, loud=False)


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

    logger.warning(
        "Skill '%s' not found locally (checked %s), installing from StrawHub",
        name,
        [str(c) for c in candidates],
    )

    cmd = _strawhub_cmd()
    if cmd is None:
        click.echo("Error: strawhub CLI not found.", err=True)
        click.echo("Install it with: pip install strawhub", err=True)
        return

    install_cmd = [*cmd, "install", "skill", name, "--global"]
    if auto_setup:
        install_cmd.append("--yes")
    result = subprocess.run(
        install_cmd,
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

    cmd = _strawhub_cmd()
    if cmd is None:
        click.echo("Error: strawhub CLI not found.", err=True)
        click.echo("Install it with: pip install strawhub", err=True)
        return

    install_cmd = [*cmd, "install", "memory", name, "--global"]
    if auto_setup:
        install_cmd.append("--yes")
    result = subprocess.run(
        install_cmd,
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

    logger.warning(
        "Role '%s' not found locally (checked %s), installing from StrawHub",
        name,
        [str(c) for c in candidates],
    )

    cmd = _strawhub_cmd()
    if cmd is None:
        click.echo("Error: strawhub CLI not found.", err=True)
        click.echo("Install it with: pip install strawhub", err=True)
        return

    install_cmd = [*cmd, "install", "role", name, "--global"]
    if auto_setup:
        install_cmd.append("--yes")
    result = subprocess.run(
        install_cmd,
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
@click.option("--memory-task", "memory_task", default=None, help="Original task string for memory scoring (defaults to --task if not set).")
@click.option("--group-id", "group_id", default=None, help="Group ID for memory scoping (e.g. conversation ID from the GUI).")
@click.option("--skip-update-check", "skip_update_check", is_flag=True, default=False, help="Skip the automatic update check on startup.")
@click.option("--keep-branch", "keep_branch", is_flag=True, default=False, help="Keep the session branch after teardown (overrides cleanup_branches config).")
def start(role, runtime, isolation, merge_strategy, pull, host, port, task, headless, run_id, system_prompt, no_cache_delegations, cache_max_entries, cache_ttl_seconds, memory_override, max_num_delegations, memory_task, group_id, skip_update_check, keep_branch):
    """Start an orchestration session.

    Runs in the foreground — creates an isolated environment (if configured),
    starts the denden server, spawns the orchestrator agent, and attaches you
    to it. On exit (Ctrl+C or agent quit), cleans up automatically.
    """
    config = load_config(Path.cwd())

    # Auto-update check (skipped for headless/task runs or explicit opt-out)
    _maybe_check_update(skip_update_check, config, headless=headless, task=task)
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

    # 0. First-run onboarding
    if needs_onboarding(config, working_dir):
        if task and not headless:
            click.echo(
                click.style("Note: ", fg="yellow", bold=True)
                + "No agent configured yet. Running first-time setup.\n"
                "Your task will be executed after setup completes.\n",
            )
        if headless:
            click.echo(
                "Error: StrawPot is not configured. Run 'strawpot start' "
                "interactively to complete first-run setup, or manually:\n"
                f"  1. Install an agent:  strawhub install agent {config.runtime} --global\n"
                f"  2. Set runtime:       Add 'runtime = \"{config.runtime}\"' to ~/.strawpot/strawpot.toml\n"
                "  3. Set required env:  Add API keys to [agents.<name>.env] in strawpot.toml",
                err=True,
            )
            sys.exit(1)
        agent_name = _onboarding_wizard(working_dir)
        if agent_name is None:
            sys.exit(1)
        # Reload config now that runtime has been saved
        config = load_config(Path(working_dir))
        runtime = agent_name

    # 0a. Recover stale sessions from previous crashes
    recovered = recover_stale_sessions(working_dir, config)
    for rid in recovered:
        click.echo(f"Recovered stale session: {rid}")

    # 0b. Pre-flight check for system tools (node, npm)
    missing_prereqs = _check_system_prerequisites()
    if missing_prereqs:
        _print_missing_prerequisites(
            missing_prereqs,
            footer="Install the missing tools above, then run "
            "'strawpot start' again.\n"
            "Run 'strawpot doctor' for a full system check.",
        )
        sys.exit(1)

    # 0c. Auto-install default dependencies if not found
    _ensure_agent_installed(config.runtime, working_dir, auto_setup=headless)
    _ensure_skill_installed("denden", working_dir, auto_setup=True)
    _ensure_skill_installed("strawpot-session-recap", working_dir, auto_setup=True)
    _ensure_role_installed(config.orchestrator_role, working_dir, auto_setup=True)
    _ensure_role_installed("ai-employee", working_dir, auto_setup=True)
    if config.memory:
        _ensure_memory_installed(config.memory, working_dir, auto_setup=True)

    # 1. Resolve agent spec
    try:
        spec = resolve_agent(
            config.runtime, working_dir, config.agents.get(config.runtime)
        )
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    except ValueError as exc:
        # The agent package is installed but its runtime binary is missing.
        # Common cause: the underlying CLI (e.g. claude) was never installed,
        # or node/npm is not available on PATH.
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + "Agent runtime binary not found.\n\n"
            + str(exc),
            err=True,
        )
        # Check for common missing prerequisites and give targeted advice
        missing = _check_system_prerequisites()
        if missing:
            click.echo(err=True)  # blank line before the list
            _print_missing_prerequisites(missing)
        click.echo(
            "\nRun 'strawpot doctor' to check all prerequisites.",
            err=True,
        )
        sys.exit(1)

    # 2. Validate agent dependencies — auto-install tools when possible
    validation = validate_agent(spec)
    if validation.missing_tools:
        unresolvable = []
        for tool, hint in validation.missing_tools:
            if hint:
                if headless:
                    click.echo(f"Installing {tool}: {hint}")
                    proceed = True
                else:
                    proceed = click.confirm(
                        f"Missing tool '{tool}'. Install via: {hint}?"
                    )
                if proceed:
                    result = subprocess.run(
                        hint, shell=True, capture_output=False
                    )
                    if result.returncode != 0:
                        click.echo(
                            f"Failed to install {tool} (exit {result.returncode})",
                            err=True,
                        )
                        unresolvable.append((tool, hint))
                else:
                    unresolvable.append((tool, hint))
            else:
                unresolvable.append((tool, None))
        if unresolvable:
            click.echo("Missing required tools:", err=True)
            for tool, hint in unresolvable:
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
        agent_env_values: dict[str, str] = {}
        for var in validation.missing_env:
            value = click.prompt(f"Enter value for {var}")
            os.environ[var] = value
            agent_env_values[var] = value
        if agent_env_values:
            from strawpot.config import save_resource_config

            save_resource_config(None, "agents", config.runtime, env_values=agent_env_values)
            click.echo(f"Saved env vars for {config.runtime} to global config.")

    # 2b. Validate skill env requirements for orchestrator role
    try:
        from strawhub.resolver import resolve as _resolve

        from strawpot.delegation import (
            _collect_saved_env,
            _get_default_agent,
            collect_skill_env,
            validate_skill_env,
        )

        resolved = _resolve(config.orchestrator_role, kind="role")
        skill_env = collect_skill_env(resolved)
        saved_env = _collect_saved_env(config, resolved)
        skill_validation = validate_skill_env(skill_env, saved_env=saved_env)

        if skill_validation.missing_env:
            if headless:
                click.echo(
                    f"Error: missing skill environment variables: "
                    f"{', '.join(skill_validation.missing_env)}",
                    err=True,
                )
                sys.exit(1)
            skill_env_to_save: dict[str, dict[str, str]] = {}  # slug -> {var: val}
            for var in skill_validation.missing_env:
                desc = skill_env[var].get("description", "")
                prompt_text = f"Enter value for {var}"
                if desc:
                    prompt_text += f" ({desc})"
                value = click.prompt(prompt_text)
                os.environ[var] = value
                source_skill = skill_env[var].get("_source_skill")
                if source_skill:
                    skill_env_to_save.setdefault(source_skill, {})[var] = value
            if skill_env_to_save:
                from strawpot.config import save_skill_env

                for slug, env_vals in skill_env_to_save.items():
                    save_skill_env(None, slug, env_vals)
                click.echo("Saved skill env vars to global config.")

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
        memory_task=memory_task or "",
        group_id=group_id,
        keep_branch=keep_branch,
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
@click.option("--skip-update-check", "skip_update_check", is_flag=True, default=False, help="Skip the automatic update check on startup.")
def gui(port, skip_update_check):
    """Launch the StrawPot web dashboard."""
    config = load_config(Path.cwd())
    working_dir = str(Path.cwd())

    # Auto-update check
    _maybe_check_update(skip_update_check, config)

    if needs_onboarding(config, working_dir):
        agent_name = _onboarding_wizard(working_dir)
        if agent_name is None:
            sys.exit(1)
        config = load_config(Path(working_dir))

    # Auto-install default dependencies if not found
    _ensure_agent_installed(config.runtime, working_dir, auto_setup=True)
    _ensure_skill_installed("denden", working_dir, auto_setup=True)
    _ensure_skill_installed("strawpot-session-recap", working_dir, auto_setup=True)
    _ensure_role_installed(config.orchestrator_role, working_dir, auto_setup=True)
    _ensure_role_installed("ai-employee", working_dir, auto_setup=True)
    if config.memory:
        _ensure_memory_installed(config.memory, working_dir, auto_setup=True)

    try:
        from strawpot_gui.server import DEFAULT_PORT, main as gui_main
    except ImportError:
        click.echo(
            "Error: strawpot-gui is not installed.\n"
            "Install it with:  pip install 'strawpot[gui]'",
            err=True,
        )
        sys.exit(1)

    gui_main(port=port or DEFAULT_PORT)


# ---------------------------------------------------------------------------
# Self-upgrade
# ---------------------------------------------------------------------------


def _detect_installer() -> str:
    """Detect how strawpot was installed: 'pipx', 'pip', or 'binary'."""
    # PyInstaller frozen binary
    if getattr(sys, "_MEIPASS", None):
        return "binary"
    # pipx detection: check whether the active virtualenv lives under a pipx-
    # managed directory.  PIPX_HOME alone is insufficient (it's a user config
    # variable that may be set even for pip-installed packages).
    venv = os.environ.get("VIRTUAL_ENV", "")
    pipx_home = os.environ.get("PIPX_HOME", "")
    if pipx_home and venv.startswith(pipx_home):
        return "pipx"
    if f"{os.sep}pipx{os.sep}" in venv:
        return "pipx"
    return "pip"


def _check_pypi_version(timeout: float = 5) -> str | None:
    """Fetch the latest strawpot version from PyPI. Returns None on failure."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/strawpot/json",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data["info"]["version"]
    except Exception:
        logger.debug("Failed to check PyPI for latest version", exc_info=True)
        return None


def _version_newer(latest: str, current: str) -> bool:
    """Return True if *latest* is strictly newer than *current*.

    Uses PEP 440 parsing via :mod:`packaging` when available, otherwise
    falls back to a simple tuple comparison of dot-separated integers.
    """
    try:
        from packaging.version import Version
        return Version(latest) > Version(current)
    except Exception:
        # ImportError if packaging is missing, InvalidVersion if the
        # version string is malformed — either way, fall through to
        # the tuple-based comparison.
        pass
    try:
        lat = tuple(int(x) for x in latest.split("."))
        cur = tuple(int(x) for x in current.split("."))
        return lat > cur
    except (ValueError, AttributeError):
        # Can't parse either version string as dotted integers.
        # Conservatively assume no update to avoid false upgrade prompts.
        return False


def _check_update_async(timeout: float = 3.0) -> str | None:
    """Check PyPI for a newer version.

    Returns the latest version string if an update is available,
    or None if the check fails, times out, or the current version
    is already up to date.
    """
    latest = _check_pypi_version(timeout=timeout)
    if latest and _version_newer(latest, __version__):
        return latest
    return None


def _should_skip_update_check() -> bool:
    """Return True if the STRAWPOT_SKIP_UPDATE_CHECK env var is set to a truthy value."""
    val = os.environ.get("STRAWPOT_SKIP_UPDATE_CHECK", "").lower()
    return val not in ("", "0", "false", "no")


def _maybe_check_update(
    skip_flag: bool,
    config: "StrawPotConfig",
    *,
    headless: bool = False,
    task: str | None = None,
) -> None:
    """Run the auto-update check unless suppressed by flag, config, env, or mode."""
    if skip_flag or config.skip_update_check or _should_skip_update_check():
        return
    if headless or task:
        return
    latest = _check_update_async()
    if latest:
        _prompt_update(latest)


def _prompt_update(latest: str) -> None:
    """Prompt the user to upgrade and run the upgrade if they accept."""
    click.echo()
    click.echo(
        click.style(
            f"A new version of strawpot is available: {__version__} → {latest}",
            fg="yellow",
        )
    )
    if click.confirm("Would you like to upgrade now?", default=False):
        installer = _detect_installer()

        if installer == "binary":
            click.echo(
                "Standalone binary detected. Download the latest release from:"
            )
            click.echo(
                "  https://github.com/strawpot/strawpot/releases/latest"
            )
            click.echo("Then restart this command.")
            return

        if installer == "pipx":
            cmd = ["pipx", "upgrade", "strawpot"]
        else:
            cmd = [
                sys.executable, "-m", "pip", "install", "--upgrade", "strawpot",
            ]

        click.echo(f"Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            click.echo(
                click.style("Upgrade complete! Please re-run your command.", fg="green")
            )
            # Exit because Python has already loaded the old module versions
            # into memory; the user must restart to pick up the new code.
            sys.exit(0)
        except FileNotFoundError:
            click.echo(
                click.style(
                    f"Upgrade failed: '{cmd[0]}' not found on PATH. "
                    "Continuing with current version.",
                    fg="red",
                ),
                err=True,
            )
        except subprocess.CalledProcessError as e:
            msg = "Upgrade failed. Continuing with current version."
            if e.stderr:
                msg += f"\n{e.stderr.strip()}"
            click.echo(click.style(msg, fg="red"), err=True)
    else:
        click.echo(
            f"You can upgrade later with: {click.style('strawpot upgrade', bold=True)}"
        )
    click.echo()


@cli.command()
@click.option("--check", is_flag=True, help="Only check for updates, don't install.")
def upgrade(check):
    """Upgrade strawpot and all its dependencies to the latest version."""
    current = __version__
    latest = _check_pypi_version()

    if latest and latest == current:
        click.echo(f"strawpot {current} is already up to date.")
        if check:
            return
    elif latest:
        click.echo(f"strawpot {current} → {latest}")
        if check:
            return
    else:
        if check:
            click.echo("Could not check PyPI for latest version.", err=True)
            sys.exit(1)
        click.echo("Could not check PyPI — upgrading anyway.")

    installer = _detect_installer()

    if installer == "binary":
        click.echo("Standalone binary detected. Download the latest release from:", err=True)
        click.echo("  https://github.com/strawpot/strawpot/releases/latest", err=True)
        sys.exit(1)

    if installer == "pipx":
        cmd = ["pipx", "upgrade", "strawpot"]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "strawpot"]

    click.echo(f"Running: {' '.join(cmd)}")
    # exec replaces this process so pip/pipx can freely overwrite our files
    os.execvp(cmd[0], cmd)


# ---------------------------------------------------------------------------
# Doctor — prerequisite checker
# ---------------------------------------------------------------------------


@cli.command()
def doctor():
    """Check system prerequisites and configuration.

    Verifies that required tools are installed (with version checks),
    the configured agent is available, and environment variables are set.
    Displays a checklist with version info and install hints.
    """
    from strawpot.doctor import check_env_vars, check_prerequisites, format_report

    config = load_config(Path.cwd())
    working_dir = str(Path.cwd())

    click.echo(click.style("StrawPot Doctor", bold=True))
    click.echo(f"Version: {__version__}\n")

    # 1. System tools + environment (checklist format)
    report = check_prerequisites()
    env_results = check_env_vars()
    click.echo(format_report(report, env_results))

    all_ok = report.ok

    # 2. Agent resolution
    click.echo(f"\n{click.style('Agent:', bold=True)} {config.runtime}")
    try:
        spec = resolve_agent(
            config.runtime, working_dir, config.agents.get(config.runtime)
        )
        click.echo(f"  [✓] Agent resolved ({spec.version})")

        # 3. Agent dependencies
        validation = validate_agent(spec)
        if validation.missing_tools:
            all_ok = False
            for tool, hint in validation.missing_tools:
                msg = f"  [✗] Tool: {tool}"
                if hint:
                    msg += f" — install: {hint}"
                click.echo(msg)
        if validation.missing_env:
            all_ok = False
            for var in validation.missing_env:
                click.echo(f"  [✗] Env: {var}")
    except FileNotFoundError:
        all_ok = False
        click.echo(
            "  [✗] Agent not installed. Run 'strawpot start' to set up."
        )
    except ValueError as exc:
        all_ok = False
        click.echo(f"  [✗] {exc}")

    # 4. Summary
    click.echo()
    if all_ok:
        click.echo(click.style("All checks passed!", fg="green", bold=True))
    else:
        click.echo(
            click.style(
                "Some checks failed. Fix the issues above and run "
                "'strawpot doctor' again.",
                fg="red",
            )
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Strawhub passthrough
# ---------------------------------------------------------------------------


def _strawhub(*args: str) -> None:
    """Run a strawhub CLI command, passing through stdout/stderr."""
    cmd = _strawhub_cmd()
    if cmd is None:
        click.echo("Error: strawhub CLI not found.", err=True)
        click.echo("Install it with: pip install strawhub", err=True)
        sys.exit(1)
    result = subprocess.run(
        [*cmd, *args],
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
