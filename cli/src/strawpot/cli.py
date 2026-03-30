"""StrawPot CLI — agent orchestration commands + strawhub passthrough."""

import json
import logging
import os
import re
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click

logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------
# Grouped help -- shows "Getting Started" commands first in --help
# ---------------------------------------------------------------------------

_COMMAND_GROUPS: list[tuple[str, list[str]]] = [
    ("Getting Started", ["start", "quickstart", "doctor", "gui"]),
    ("Memory", ["remember", "recall", "forget", "memory", "mcp"]),
    ("Scheduling", ["schedule"]),
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
from strawpot.isolation.protocol import NoneIsolator
from strawpot.session import Session, recover_stale_sessions


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



@click.group(cls=GroupedGroup, epilog=HELP_EPILOG, invoke_without_command=True)
@click.version_option(version=__version__)
@click.pass_context
def cli(ctx):
    """StrawPot orchestrates AI agents with roles, skills, and delegation.

    Define roles (what an agent does), attach skills (what it knows),
    and let agents delegate to each other in sessions. Works with
    Claude Code, Codex, Gemini, and more.

    Run 'strawpot start' to begin.
    """
    _show_first_run_banner()
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())

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


def _run_strawhub_install(install_cmd: list[str], *, resource_type: str, name: str) -> None:
    """Run a strawhub install command, handling OSError and non-zero exit."""
    try:
        result = subprocess.run(
            install_cmd,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    except OSError as exc:
        click.echo(f"Failed to run strawhub CLI: {exc}", err=True)
        return
    if result.returncode != 0:
        click.echo(f"Failed to install {resource_type} '{name}'.", err=True)


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
    _run_strawhub_install(install_cmd, resource_type="skill", name=name)


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
    _run_strawhub_install(install_cmd, resource_type="memory provider", name=name)


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
    _run_strawhub_install(install_cmd, resource_type="role", name=name)


def _ensure_integration_installed(name: str, working_dir: str, *, auto_setup: bool = False) -> None:
    """Prompt to install an integration from StrawHub if it is not found locally."""
    candidates = [
        Path(working_dir) / ".strawpot" / "integrations" / name,
        get_strawpot_home() / "integrations" / name,
    ]
    for candidate in candidates:
        if (candidate / "INTEGRATION.md").is_file():
            return  # already installed

    if not auto_setup:
        if not click.confirm(
            f"Integration '{name}' is not installed. Install from StrawHub?", default=True
        ):
            return

    logger.warning(
        "Integration '%s' not found locally (checked %s), installing from StrawHub",
        name,
        [str(c) for c in candidates],
    )

    cmd = _strawhub_cmd()
    if cmd is None:
        click.echo("Error: strawhub CLI not found.", err=True)
        click.echo("Install it with: pip install strawhub", err=True)
        return

    install_cmd = [*cmd, "install", "integration", name, "--global"]
    if auto_setup:
        install_cmd.append("--yes")
    _run_strawhub_install(install_cmd, resource_type="integration", name=name)


# ---------------------------------------------------------------------------
# Default resources — installed automatically on first run.
# These are NOT protected (can be uninstalled); they simply ship pre-installed.
# ---------------------------------------------------------------------------

_DEFAULT_SKILLS = ["denden", "strawpot-session-recap", "notify-telegram", "notify-slack", "notify-discord"]
_DEFAULT_ROLES = ["ai-employee", "gstack-ceo", "skill-creator", "skill-evaluator", "role-creator", "role-evaluator"]
_DEFAULT_INTEGRATIONS = ["telegram", "discord", "slack"]


def _bootstrap_default_resources(config, working_dir: str) -> None:
    """Install default skills, roles, integrations, and memory if missing.

    Each default install is wrapped in try/except so one failure does not
    block the rest.  The orchestrator role is installed before other defaults
    because downstream roles may depend on it.
    """
    bootstrap_steps = [
        ("skill", _DEFAULT_SKILLS, _ensure_skill_installed),
        ("role", _DEFAULT_ROLES, _ensure_role_installed),
        ("integration", _DEFAULT_INTEGRATIONS, _ensure_integration_installed),
    ]
    for resource_type, defaults, install_fn in bootstrap_steps:
        # The orchestrator role must be installed before other default roles.
        if resource_type == "role":
            try:
                _ensure_role_installed(config.orchestrator_role, working_dir, auto_setup=True)
            except Exception:
                click.echo(
                    f"Warning: failed to install orchestrator role '{config.orchestrator_role}', skipping.",
                    err=True,
                )
                logger.warning(
                    "Failed to bootstrap orchestrator role '%s'",
                    config.orchestrator_role,
                    exc_info=True,
                )
        for name in defaults:
            try:
                install_fn(name, working_dir, auto_setup=True)
            except Exception:
                click.echo(f"Warning: failed to install default {resource_type} '{name}', skipping.", err=True)
                logger.warning("Failed to bootstrap %s '%s'", resource_type, name, exc_info=True)
    if config.memory:
        try:
            _ensure_memory_installed(config.memory, working_dir, auto_setup=True)
        except Exception:
            click.echo(
                f"Warning: failed to install memory provider '{config.memory}', skipping.",
                err=True,
            )
            logger.warning("Failed to bootstrap memory provider '%s'", config.memory, exc_info=True)


def _resolve_progress_renderer(progress_mode: str, task: str | None):
    """Select the progress event callback based on ``--progress`` mode.

    Returns a callable for ``Session.on_event``, or ``None`` to disable.
    """
    if progress_mode == "off":
        return None
    try:
        if progress_mode == "json":
            from strawpot.progress import JsonProgressRenderer
            return JsonProgressRenderer().handle_event
        if task:  # auto mode + task mode = terminal renderer
            from strawpot.progress import TerminalProgressRenderer
            return TerminalProgressRenderer().handle_event
    except Exception:
        logger.warning("Failed to initialize progress renderer", exc_info=True)
    # auto mode + interactive mode = no renderer (user sees agent output)
    return None


@cli.command()
@click.option("--role", default=None, help="Orchestrator role slug from strawhub.")
@click.option("--runtime", default=None, help="Agent runtime (any registry-resolvable name).")
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
@click.option("--yes", "-y", "yes_flag", is_flag=True, default=False, help="Auto-accept all install prompts (tools, agents, etc.).")
@click.option("--no-tools", "no_tools", is_flag=True, default=False, help="Skip tool dependency installation entirely.")
@click.option(
    "--progress",
    "progress_mode",
    type=click.Choice(["auto", "json", "off"], case_sensitive=False),
    default="auto",
    help="Progress output mode (auto=terminal for --task, json=JSONL, off=disabled).",
)
def start(role, runtime, pull, host, port, task, headless, run_id, system_prompt, no_cache_delegations, cache_max_entries, cache_ttl_seconds, memory_override, max_num_delegations, memory_task, group_id, skip_update_check, yes_flag, no_tools, progress_mode):
    """Start an orchestration session.

    Runs in the foreground — starts the denden server, spawns the
    orchestrator agent, and attaches you to it. On exit (Ctrl+C or
    agent quit), cleans up automatically.
    """
    # Derive whether prompts should be auto-accepted (--yes / --headless).
    auto_accept = yes_flag or headless
    # Detect non-interactive terminal (no TTY on stdin) — prompts would hang.
    non_interactive = not sys.stdin.isatty() and not auto_accept

    config = load_config(Path.cwd())

    # Auto-update check (skipped for headless/task runs or explicit opt-out)
    _maybe_check_update(skip_update_check, config, headless=headless, task=task)
    if role:
        config.orchestrator_role = role
    if runtime:
        config.runtime = runtime
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
        if task or headless:
            click.echo(
                "Error: No agent configured. Run 'strawpot start' "
                "interactively to complete first-run setup, then re-run "
                "with --task.\n\n"
                "Alternatively, configure manually:\n"
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
    _ensure_agent_installed(config.runtime, working_dir, auto_setup=auto_accept)
    _bootstrap_default_resources(config, working_dir)

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
        if no_tools or non_interactive:
            label = "--no-tools" if no_tools else "non-interactive shell"
            click.echo(f"Missing required tools (skipped — {label}):", err=True)
            for tool, hint in validation.missing_tools:
                msg = f"  - {tool}"
                if hint:
                    msg += f"  (install: {hint})"
                click.echo(msg, err=True)
            sys.exit(1)
        unresolvable = []
        for tool, hint in validation.missing_tools:
            if hint:
                if auto_accept:
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
    isolator = NoneIsolator()

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

    # 6. Determine progress renderer
    on_event = _resolve_progress_renderer(progress_mode, task)

    # 7. Create and run session
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
        on_event=on_event,
    )
    session.start(working_dir)


@cli.command(name="config")
def show_config():
    """Show merged configuration."""
    config = load_config(Path.cwd())
    click.echo(f"runtime:              {config.runtime}")
    click.echo(f"denden_addr:          {config.denden_addr}")
    click.echo(f"orchestrator_role:    {config.orchestrator_role}")
    click.echo(f"permission_mode:      {config.permission_mode}")
    click.echo(f"max_depth:            {config.max_depth}")
    click.echo(f"agent_timeout:        {config.agent_timeout}")
    click.echo(f"pull_before_session:  {config.pull_before_session}")
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


def _latest_running_session() -> str | None:
    """Return the run_id of the most recent running session, or None."""
    sessions_path = _sessions_dir()
    running_path = sessions_path.parent / "running"
    if not running_path.is_dir():
        return None

    best_id: str | None = None
    best_time: str = ""
    for entry in running_path.iterdir():
        if not entry.name.startswith("run_"):
            continue
        session_file = sessions_path / entry.name / "session.json"
        data = _load_session(session_file)
        if data is None:
            continue
        pid = data.get("pid")
        if not (pid and is_pid_alive(pid)):
            continue
        started_at = data.get("started_at", "")
        if started_at > best_time:
            best_time = started_at
            best_id = data.get("run_id", entry.name)
    return best_id


def _collect_sessions(status_filter: set[str] | None = None) -> list[dict]:
    """Collect session data from running and archive directories."""
    sessions_path = _sessions_dir()
    results: list[dict] = []

    # Scan running sessions
    running_path = sessions_path.parent / "running"
    if running_path.is_dir():
        for entry in sorted(running_path.iterdir()):
            if not entry.name.startswith("run_"):
                continue
            data = _load_session(sessions_path / entry.name / "session.json")
            if data is None:
                continue
            pid = data.get("pid")
            alive = is_pid_alive(pid) if pid else False
            status = "running" if alive else "stale"
            if status_filter and status not in status_filter:
                continue
            results.append({
                "run_id": data.get("run_id", entry.name),
                "status": status,
                "runtime": data.get("runtime", "?"),
                "denden_addr": data.get("denden_addr", "?"),
                "started_at": data.get("started_at", ""),
                "uptime": _format_uptime(data.get("started_at", "")) if alive else "-",
            })

    # Scan archived sessions
    if status_filter is None or "archived" in status_filter:
        archive_path = sessions_path.parent / "archive"
        if archive_path.is_dir():
            for entry in sorted(archive_path.iterdir()):
                if not entry.name.startswith("run_"):
                    continue
                data = _load_session(sessions_path / entry.name / "session.json")
                if data is None:
                    continue
                results.append({
                    "run_id": data.get("run_id", entry.name),
                    "status": "archived",
                    "runtime": data.get("runtime", "?"),
                    "denden_addr": data.get("denden_addr", "?"),
                    "started_at": data.get("started_at", ""),
                    "uptime": "-",
                })

    return results


@cli.command()
@click.option("--status", "status_csv", default=None,
              help="Comma-separated status filter: running, stale, archived.")
@click.option("--all", "show_all", is_flag=True, default=False,
              help="Show all sessions (running + stale + archived).")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Output as JSON array.")
def sessions(status_csv, show_all, as_json):
    """List sessions on this machine."""
    if show_all:
        status_filter = None  # No filter — show everything
    elif status_csv:
        status_filter = {s.strip() for s in status_csv.split(",")}
    else:
        status_filter = {"running"}  # Default: running only

    results = _collect_sessions(status_filter)

    if as_json:
        click.echo(json.dumps(results, indent=2))
        return

    if not results:
        click.echo("No sessions found.")
        return

    click.echo(f"{'RUN ID':<20} {'STATUS':<8} {'RUNTIME':<14} {'DENDEN':<20} {'UPTIME':<10}")
    click.echo("-" * 72)
    for r in results:
        click.echo(
            f"{r['run_id']:<20} {r['status']:<8} "
            f"{r['runtime']:<14} {r['denden_addr']:<20} {r['uptime']:<10}"
        )


def _resolve_agent_status(info: dict) -> str:
    """Get agent status from state field with PID fallback for old sessions."""
    status = info.get("state")
    if status:
        return status
    pid = info.get("pid")
    alive = is_pid_alive(pid) if pid else False
    return "running" if alive else "exited"


def _agent_depth_from_info(agent_id: str, agents_map: dict) -> int:
    """Calculate delegation depth by traversing the parent chain."""
    depth = 0
    current = agent_id
    for _ in range(100):
        info = agents_map.get(current, {})
        parent = info.get("parent")
        if parent:
            depth += 1
            current = parent
        else:
            break
    return depth


@cli.command()
@click.argument("session_id", required=False, default=None)
@click.option("--session", "session_opt", default=None,
              help="Session run_id (alternative to positional arg).")
@click.option("--status", "status_csv", default=None,
              help="Comma-separated status filter (e.g. running,cancelling).")
@click.option("--role", "role_filter", default=None,
              help="Filter by role name.")
@click.option("--parent", "parent_filter", default=None,
              help="Show only children of this agent.")
@click.option("--tree", "as_tree", is_flag=True, default=False,
              help="Display as indented tree.")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Output as JSON array.")
def agents(session_id, session_opt, status_csv, role_filter, parent_filter, as_tree, as_json):
    """List agents in a session.

    SESSION_ID is optional — defaults to the latest running session.
    """
    # Resolve session ID: positional arg > --session > auto-detect
    sid = session_id or session_opt or _latest_running_session()
    if not sid:
        click.echo("No running session found. Specify a session ID.")
        sys.exit(1)

    sessions_path = _sessions_dir()
    session_file = sessions_path / sid / "session.json"
    if not session_file.is_file():
        click.echo(f"Session not found: {sid}")
        sys.exit(1)

    data = _load_session(session_file)
    if data is None:
        click.echo(f"Failed to read session: {sid}")
        sys.exit(1)

    agents_map = data.get("agents", {})
    if not agents_map:
        click.echo("No agents recorded for this session.")
        return

    # Parse status filter
    status_set = {s.strip() for s in status_csv.split(",")} if status_csv else None

    # Build filtered agent list
    filtered: list[dict] = []
    for agent_id, info in agents_map.items():
        status = _resolve_agent_status(info)
        role = info.get("role", "?")
        parent = info.get("parent")

        if status_set and status not in status_set:
            continue
        if role_filter and role != role_filter:
            continue
        if parent_filter and parent != parent_filter:
            continue

        filtered.append({
            "agent_id": agent_id,
            "role": role,
            "runtime": info.get("runtime", "?"),
            "parent": parent or "-",
            "status": status,
            "started_at": info.get("started_at", ""),
            "pid": info.get("pid"),
            "cancel_reason": info.get("cancel_reason"),
        })

    if as_json:
        click.echo(json.dumps(filtered, indent=2))
        return

    if not filtered:
        click.echo("No agents match the specified filters.")
        return

    if as_tree:
        # Tree view: indent based on depth
        for agent in filtered:
            depth = _agent_depth_from_info(agent["agent_id"], agents_map)
            indent = "  " * depth
            click.echo(f"{indent}{agent['agent_id']:<16} {agent['role']:<16} [{agent['status']}]")
    else:
        # Table view
        click.echo(f"{'AGENT ID':<20} {'ROLE':<16} {'RUNTIME':<14} {'PARENT':<20} {'STATUS':<10}")
        click.echo("-" * 80)
        for agent in filtered:
            click.echo(
                f"{agent['agent_id']:<20} {agent['role']:<16} "
                f"{agent['runtime']:<14} {agent['parent']:<20} {agent['status']:<10}"
            )


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


@cli.group()
def cancel():
    """Cancel running agents or sessions."""
    pass


def _wait_for_cancel(session_file: Path, agent_ids: set[str], timeout: float = 30.0) -> bool:
    """Poll session.json until all specified agents are in a terminal state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = _load_session(session_file)
        if data is None:
            return False
        agents_map = data.get("agents", {})
        all_done = True
        for aid in agent_ids:
            info = agents_map.get(aid, {})
            state = info.get("state", "")
            if state not in ("cancelled", "completed", "failed"):
                all_done = False
                break
        if all_done:
            return True
        time.sleep(0.5)
    return False


@cancel.command("agent")
@click.argument("agent_id")
@click.option("--run", "run_id", required=True, help="Session run ID.")
@click.option("--force", is_flag=True, help="Force-kill without graceful shutdown.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def cancel_agent_cmd(agent_id, run_id, force, yes):
    """Cancel a specific agent and its descendants."""
    from strawpot.cancel import get_descendants, write_cancel_signal

    sessions_path = _sessions_dir()
    session_dir = sessions_path / run_id
    session_file = session_dir / "session.json"

    if not session_file.is_file():
        click.echo(f"Session not found: {run_id}")
        sys.exit(1)

    data = _load_session(session_file)
    if data is None:
        click.echo(f"Failed to read session: {run_id}")
        sys.exit(1)

    # Verify session is alive
    pid = data.get("pid")
    if not (pid and is_pid_alive(pid)):
        click.echo(f"Session {run_id} is not running (stale).")
        sys.exit(1)

    agents_map = data.get("agents", {})
    if agent_id not in agents_map:
        click.echo(f"Agent not found: {agent_id}")
        sys.exit(1)

    # Show affected agents
    descendants = get_descendants(agent_id, agents_map)
    affected = [agent_id] + descendants
    force_label = " (force)" if force else ""

    if not yes:
        click.echo(f"Will cancel {len(affected)} agent(s){force_label}:")
        for aid in affected:
            info = agents_map.get(aid, {})
            role = info.get("role", "?")
            state = info.get("state", "?")
            click.echo(f"  {aid} ({role}) — {state}")
        if not click.confirm("Proceed?", default=False):
            click.echo("Cancelled.")
            return

    write_cancel_signal(str(session_dir), agent_id, force=force)

    # Send SIGUSR1 to wake watcher immediately
    try:
        os.kill(pid, signal.SIGUSR1)
    except (ProcessLookupError, PermissionError, OSError):
        pass

    click.echo(f"Cancel signal sent for {agent_id}. Waiting...")
    if _wait_for_cancel(session_file, set(affected)):
        click.echo(f"Cancelled {len(affected)} agent(s).")
    else:
        click.echo("Cancel timed out — check session status.", err=True)
        sys.exit(1)


@cancel.command("run")
@click.argument("run_id")
@click.option("--force", is_flag=True, help="Force-kill without graceful shutdown.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def cancel_run_cmd(run_id, force, yes):
    """Cancel all agents in a session."""
    from strawpot.cancel import write_cancel_signal

    sessions_path = _sessions_dir()
    session_dir = sessions_path / run_id
    session_file = session_dir / "session.json"

    if not session_file.is_file():
        click.echo(f"Session not found: {run_id}")
        sys.exit(1)

    data = _load_session(session_file)
    if data is None:
        click.echo(f"Failed to read session: {run_id}")
        sys.exit(1)

    pid = data.get("pid")
    if not (pid and is_pid_alive(pid)):
        click.echo(f"Session {run_id} is not running (stale).")
        sys.exit(1)

    agents_map = data.get("agents", {})
    force_label = " (force)" if force else ""

    if not yes:
        click.echo(f"Will cancel {len(agents_map)} agent(s) in session {run_id}{force_label}:")
        for aid, info in agents_map.items():
            role = info.get("role", "?")
            state = info.get("state", "?")
            click.echo(f"  {aid} ({role}) — {state}")
        if not click.confirm("Proceed?", default=False):
            click.echo("Cancelled.")
            return

    write_cancel_signal(str(session_dir), None, force=force)

    # Send SIGUSR1 to wake watcher
    try:
        os.kill(pid, signal.SIGUSR1)
    except (ProcessLookupError, PermissionError, OSError):
        pass

    click.echo(f"Cancel signal sent for session {run_id}. Waiting...")
    if _wait_for_cancel(session_file, set(agents_map.keys())):
        click.echo(f"Cancelled {len(agents_map)} agent(s).")
    else:
        click.echo("Cancel timed out — check session status.", err=True)
        sys.exit(1)


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
    _bootstrap_default_resources(config, working_dir)

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
# MCP commands
# ---------------------------------------------------------------------------


@cli.group()
def mcp():
    """MCP server for Claude Code memory integration."""
    pass


@mcp.command(name="serve")
def mcp_serve():
    """Start the MCP memory server (stdio transport)."""
    try:
        from strawpot.mcp.server import main as serve_main
    except ImportError:
        raise click.ClickException(
            "MCP server requires the 'mcp' package. "
            "Install it with: pip install strawpot[mcp]"
        )
    serve_main()


@mcp.command(name="setup")
@click.option("--project", is_flag=True, help="Configure per-project instead of global.")
def mcp_setup(project):
    """Auto-configure Claude Code to use StrawPot memory."""
    from strawpot.mcp.setup import configure_mcp

    configure_mcp(project=project)


# ---------------------------------------------------------------------------
# Schedule commands
# ---------------------------------------------------------------------------


@cli.group()
def schedule():
    """Create and manage scheduled workflows."""
    pass


@schedule.command(name="create")
@click.argument("task", required=False, default="")
@click.option("--name", default="", help="Schedule name (defaults to task text).")
@click.option("--cron", default="", help="Cron expression (e.g. '0 8 * * *').")
@click.option("--role", default="", help="Role to execute as.")
@click.option("--description", default="", help="Optional description.")
@click.option("--template", "-t", default="", help="Use a pre-built workflow template.")
def schedule_create(task, name, cron, role, description, template):
    """Create a new scheduled workflow (or install from --template)."""
    from strawpot.scheduler.store import ScheduleStore

    if template:
        from strawpot.scheduler.templates import (
            load_template,
            validate_prerequisites,
        )

        tpl = load_template(template)
        if tpl is None:
            raise click.ClickException(
                f"Template '{template}' not found. "
                "Run 'strawpot schedule templates' to see available templates."
            )
        issues = validate_prerequisites(tpl)
        if issues:
            click.echo(click.style("⚠️  Prerequisites:", fg="yellow"))
            for issue in issues:
                click.echo(f"   - {issue}")
            click.echo()

        task = task or tpl.task
        cron = cron or tpl.default_cron
        role = role or tpl.role
        name = name or tpl.name
        description = description or tpl.description

    if not task:
        raise click.ClickException("Task is required. Provide a task argument or use --template.")
    if not cron:
        raise click.ClickException("--cron is required. Provide a cron expression or use --template.")

    store = ScheduleStore()
    try:
        sched = store.create(
            name=name or task[:50],
            task=task,
            cron=cron,
            role=role,
            description=description,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc))

    click.echo(click.style("✅ Schedule created!", fg="green"))
    click.echo(f"   ID: {sched.schedule_id}")
    click.echo(f"   Task: {sched.task[:80]}")
    click.echo(f"   Cron: {sched.cron}")
    click.echo(f"   Next run: {sched.next_run()}")
    if role:
        click.echo(f"   Role: {role}")
    click.echo()
    click.echo(
        click.style("💡 Tip: ", fg="cyan")
        + "Run "
        + click.style("strawpot schedule list", bold=True)
        + " to see all schedules."
    )


@schedule.command(name="templates")
def schedule_templates():
    """List available pre-built workflow templates."""
    from strawpot.scheduler.templates import list_templates

    templates = list_templates()
    if not templates:
        click.echo("No templates available.")
        return

    click.echo(click.style("📋 Available workflow templates:", fg="cyan"))
    click.echo()
    for tpl in templates:
        click.echo(
            "  "
            + click.style(tpl.slug, bold=True)
            + click.style(f" — {tpl.description}", dim=True)
        )
        click.echo(f"     Cron: {tpl.default_cron}")
        if tpl.role:
            click.echo(f"     Role: {tpl.role}")
        click.echo()
    click.echo(
        "Use: "
        + click.style("strawpot schedule create --template <name>", bold=True)
        + " to install."
    )


@schedule.command(name="list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def schedule_list(as_json):
    """List all active schedules."""
    from strawpot.scheduler.store import ScheduleStore

    store = ScheduleStore()
    schedules = store.list_schedules()

    if as_json:
        entries = [
            {
                "schedule_id": s.schedule_id,
                "name": s.name,
                "cron": s.cron,
                "task": s.task,
                "role": s.role,
                "next_run": s.next_run(),
                "last_status": s.last_status,
            }
            for s in schedules
        ]
        click.echo(json.dumps(entries, indent=2))
        return

    if not schedules:
        click.echo("No schedules configured yet.")
        click.echo(
            "Run "
            + click.style('strawpot schedule create "task" --cron "0 8 * * *"', bold=True)
            + " to create one."
        )
        return

    click.echo(click.style("📅 ", fg="cyan") + f"{len(schedules)} schedule(s):")
    click.echo()
    for s in schedules:
        click.echo(
            "  "
            + click.style(f"[{s.schedule_id}]", fg="bright_black")
            + f" {s.name}"
        )
        click.echo(f"     Cron: {s.cron} | Next: {s.next_run()}")
        if s.last_status:
            click.echo(f"     Last: {s.last_status}")
        click.echo()


@schedule.command(name="delete")
@click.argument("schedule_id")
def schedule_delete(schedule_id):
    """Remove a schedule by ID."""
    from strawpot.scheduler.store import ScheduleStore

    store = ScheduleStore()
    if store.delete(schedule_id):
        click.echo(f"🗑️  Deleted schedule {schedule_id}")
    else:
        click.echo(click.style(f"❌ Schedule {schedule_id} not found", fg="red"), err=True)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Strawhub passthrough
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Memory commands
# ---------------------------------------------------------------------------


def _pluralize_memory(count: int) -> str:
    """Return 'memory' or 'memories' based on *count*."""
    return "memory" if count == 1 else "memories"


@cli.command()
@click.argument("fact")
@click.option("--scope", "-s", default="project", type=click.Choice(["project", "global", "role"]),
              help="Storage scope.")
@click.option("--keywords", "-k", default="", help="Comma-separated keywords for retrieval matching.")
def remember(fact, scope, keywords):
    """Store a fact in memory for AI agents to recall later."""
    from strawpot.memory.standalone import (
        CLI_AGENT_ID,
        CLI_ROLE,
        CLI_SESSION_ID,
        get_standalone_provider,
    )

    provider = get_standalone_provider()
    kw = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else None
    result = provider.remember(
        session_id=CLI_SESSION_ID,
        agent_id=CLI_AGENT_ID,
        role=CLI_ROLE,
        content=fact,
        keywords=kw,
        scope=scope,
    )
    if result.status == "duplicate":
        click.echo(click.style("⚠️  Already remembered", fg="yellow") + " (near-duplicate detected)")
    else:
        click.echo(click.style("✅ Remembered: ", fg="green") + f'"{fact}"')
        click.echo(f"   ID: {result.entry_id}")
        click.echo(f"   Scope: {scope}")

    from strawpot.mcp.status import check_mcp_status
    from strawpot.memory.breadcrumbs import remember_breadcrumb

    mcp_configured, _ = check_mcp_status()
    remember_breadcrumb(mcp_configured)


@cli.command()
@click.argument("query")
@click.option("--scope", "-s", default="", help="Filter to specific scope (project, global, role).")
@click.option("--max", "-n", "max_results", default=10, help="Max results to return.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def recall(query, scope, max_results, as_json):
    """Search stored memories matching a query."""
    from strawpot.memory.standalone import (
        CLI_AGENT_ID,
        CLI_ROLE,
        CLI_SESSION_ID,
        get_standalone_provider,
    )

    provider = get_standalone_provider()
    result = provider.recall(
        session_id=CLI_SESSION_ID,
        agent_id=CLI_AGENT_ID,
        role=CLI_ROLE,
        query=query,
        scope=scope,
        max_results=max_results,
    )

    if as_json:
        entries = [
            {
                "entry_id": e.entry_id,
                "content": e.content,
                "keywords": e.keywords,
                "scope": e.scope,
                "score": round(e.score, 2),
            }
            for e in result.entries
        ]
        click.echo(json.dumps(entries, indent=2))
        return

    if not result.entries:
        click.echo(f'No memories found matching "{query}".')
        click.echo(
            "Try "
            + click.style("strawpot remember", bold=True)
            + " to add some."
        )
        return

    click.echo(
        click.style("🔍 ", fg="cyan")
        + f'Found {len(result.entries)} {_pluralize_memory(len(result.entries))} matching "{query}":'
    )
    click.echo()
    for i, entry in enumerate(result.entries, 1):
        click.echo(
            f"  {i}. "
            + click.style(f"[{entry.entry_id}]", fg="bright_black")
            + f" (score: {entry.score:.2f}, scope: {entry.scope})"
        )
        click.echo(f"     {entry.content}")
        if i < len(result.entries):
            click.echo()

    from strawpot.memory.breadcrumbs import recall_breadcrumb

    recall_breadcrumb()


@cli.command()
@click.argument("entry_id")
def forget(entry_id):
    """Delete a specific memory by ID."""
    from strawpot.memory.standalone import get_standalone_provider

    provider = get_standalone_provider()
    result = provider.forget(entry_id=entry_id)
    if result.status == "deleted":
        click.echo(f"🗑️  Deleted memory {entry_id}")

        from strawpot.memory.breadcrumbs import forget_breadcrumb

        forget_breadcrumb()
    else:
        click.echo(click.style(f"❌ Memory {entry_id} not found", fg="red"), err=True)
        raise SystemExit(1)


@cli.group()
def memory():
    """Manage stored memories."""
    pass


@memory.command(name="list")
@click.option("--scope", "-s", default="", help="Filter by scope (project, global, role).")
@click.option("--all", "show_all", is_flag=True, help="Show all entries (default: first 20).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def memory_list(scope, show_all, as_json):
    """List all stored memories."""
    from strawpot.memory.standalone import get_standalone_provider

    provider = get_standalone_provider()
    limit = 10000 if show_all else 20
    result = provider.list_entries(scope=scope, limit=limit)

    if as_json:
        entries = [
            {
                "entry_id": e.entry_id,
                "content": e.content,
                "keywords": e.keywords,
                "scope": e.scope,
                "ts": e.ts,
            }
            for e in result.entries
        ]
        click.echo(json.dumps(entries, indent=2))
        return

    if not result.entries:
        click.echo("No memories stored yet.")
        click.echo(
            "Run "
            + click.style('strawpot remember "fact"', bold=True)
            + " to add your first."
        )
        return

    click.echo(
        click.style("📝 ", fg="cyan")
        + f"{result.total_count} {_pluralize_memory(result.total_count)} stored:"
    )
    click.echo()

    for entry in result.entries:
        date_str = entry.ts[:10] if entry.ts else ""
        content_display = (entry.content[:100] + "…") if len(entry.content) > 100 else entry.content

        click.echo(
            "  "
            + click.style(f"[{entry.entry_id}]", fg="bright_black")
            + f" ({entry.scope}, {date_str})"
        )
        click.echo(f"     {content_display}")
        if entry.keywords:
            click.echo(
                "     Keywords: "
                + click.style(", ".join(entry.keywords), fg="cyan")
            )
        click.echo()

    if len(result.entries) < result.total_count:
        remaining = result.total_count - len(result.entries)
        msg = f"  ...showing {len(result.entries)} of {result.total_count} ({remaining} more)."
        if not show_all:
            msg += " Use --all to see all."
        click.echo(msg)

    from strawpot.memory.breadcrumbs import list_breadcrumb

    list_breadcrumb()


@memory.command(name="consolidate")
@click.option("--scope", "-s", default="", type=click.Choice(["", "project", "global"]),
              help="Limit consolidation to a specific scope.")
@click.option("--dry-run", is_flag=True, help="Show what would be consolidated without making changes.")
@click.option("--json", "as_json", is_flag=True, help="Output report as JSON.")
def memory_consolidate(scope, dry_run, as_json):
    """Consolidate memories: remove duplicates and archive stale entries."""
    from strawpot.memory.consolidation import consolidate
    from strawpot.memory.standalone import (
        detect_project_dir,
        get_standalone_provider,
    )

    try:
        project_dir = detect_project_dir()
    except Exception:
        project_dir = None

    provider = get_standalone_provider(project_dir=project_dir)
    report = consolidate(
        provider,
        scope=scope,
        project_dir=project_dir,
        dry_run=dry_run,
    )

    if as_json:
        click.echo(json.dumps({
            "dry_run": dry_run,
            "total_entries_scanned": report.total_entries_scanned,
            "groups_found": report.groups_found,
            "duplicates_removed": report.duplicates_removed,
            "entries_archived": report.entries_archived,
            "actions": [
                {
                    "action": a.action,
                    "entry_id": a.entry_id,
                    "reason": a.reason,
                }
                for a in report.actions
            ],
        }, indent=2))
        return

    prefix = "Would consolidate" if dry_run else "Consolidated"

    if not report.actions:
        click.echo(
            click.style("✅ ", fg="green")
            + f"No consolidation needed ({report.total_entries_scanned} "
            + f"{_pluralize_memory(report.total_entries_scanned)} scanned)."
        )
        return

    click.echo(
        click.style("🔧 " if not dry_run else "🔍 ", fg="cyan")
        + f"{prefix} {report.total_entries_scanned} "
        + f"{_pluralize_memory(report.total_entries_scanned)}:"
    )
    click.echo()

    if report.duplicates_removed:
        click.echo(
            f"  Duplicates {'to remove' if dry_run else 'removed'}: "
            + click.style(str(report.duplicates_removed), fg="yellow")
        )
    if report.entries_archived:
        click.echo(
            f"  Stale entries {'to archive' if dry_run else 'archived'}: "
            + click.style(str(report.entries_archived), fg="yellow")
        )

    click.echo()
    for action in report.actions:
        icon = "🗑️" if action.action == "delete_duplicate" else "📦"
        click.echo(
            f"  {icon} "
            + click.style(f"[{action.entry_id}]", fg="bright_black")
            + f" {action.reason}"
        )


@memory.command(name="rebuild-embeddings")
@click.option("--scope", "-s", default="", type=click.Choice(["", "project", "global"]),
              help="Limit to a specific scope.")
def memory_rebuild_embeddings(scope):
    """Recompute embeddings for all existing memories."""
    from strawpot.memory.embeddings import is_available, rebuild_all
    from strawpot.memory.standalone import (
        detect_project_dir,
        get_standalone_provider,
    )

    if not is_available():
        click.echo(
            click.style("❌ ", fg="red")
            + "No embedding model available. Install sentence-transformers:\n"
            + click.style("  pip install sentence-transformers", bold=True)
        )
        raise SystemExit(1)

    try:
        project_dir = detect_project_dir()
    except Exception:
        project_dir = None

    provider = get_standalone_provider(project_dir=project_dir)

    click.echo(
        click.style("🔄 ", fg="cyan")
        + "Rebuilding embeddings..."
    )
    count = rebuild_all(provider, scope=scope, project_dir=project_dir)
    click.echo(
        click.style("✅ ", fg="green")
        + f"Rebuilt embeddings for {count} {_pluralize_memory(count)}."
    )


@memory.command(name="graph")
@click.argument("entry_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def memory_graph(entry_id, as_json):
    """Show the memory relationship graph."""
    from strawpot.memory.graph import format_graph, load_graph
    from strawpot.memory.standalone import detect_project_dir

    try:
        project_dir = detect_project_dir()
    except Exception:
        project_dir = None

    if as_json:
        graph = load_graph(project_dir)
        raw = {
            source: [
                {"type": r.relation_type, "target": r.target, "created_at": r.created_at}
                for r in rels
            ]
            for source, rels in graph.edges.items()
        }
        if entry_id:
            # Filter to only relations involving the entry
            filtered = {}
            for source, rels in raw.items():
                if source == entry_id:
                    filtered[source] = rels
                else:
                    relevant = [r for r in rels if r["target"] == entry_id]
                    if relevant:
                        filtered[source] = relevant
            raw = filtered
        click.echo(json.dumps(raw, indent=2))
        return

    output = format_graph(entry_id, project_dir)
    click.echo(output)


@memory.command(name="add-relation")
@click.argument("source")
@click.argument("relation_type")
@click.argument("target")
def memory_add_relation(source, relation_type, target):
    """Add a relation between two memory entries.

    RELATION_TYPE must be one of: follows_from, caused_by, supersedes, related_to
    """
    from strawpot.memory.graph import RELATION_TYPES, add_relation
    from strawpot.memory.standalone import detect_project_dir

    if relation_type not in RELATION_TYPES:
        click.echo(
            click.style("❌ ", fg="red")
            + f"Invalid relation type: {relation_type}\n"
            + f"Must be one of: {', '.join(sorted(RELATION_TYPES))}"
        )
        raise SystemExit(1)

    try:
        project_dir = detect_project_dir()
    except Exception:
        project_dir = None

    added = add_relation(source, relation_type, target, project_dir)
    if added:
        click.echo(
            click.style("✅ ", fg="green")
            + f"{source} --{relation_type}--> {target}"
        )
    else:
        click.echo(
            click.style("⚠️ ", fg="yellow")
            + "Relation already exists or is invalid."
        )


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
