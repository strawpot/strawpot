"""Agent registry — discover AGENT.md manifests and resolve to AgentSpec."""

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from strawpot.config import get_strawpot_home


@dataclass
class ValidationResult:
    """Result of validating an AgentSpec's external dependencies.

    Attributes:
        missing_tools: Tool names that are not found on PATH,
            each paired with an optional install hint.
        missing_env: Required environment variable names that are not set.
    """

    missing_tools: list[tuple[str, str | None]] = field(default_factory=list)
    missing_env: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True if no issues were found."""
        return not self.missing_tools and not self.missing_env


@dataclass
class AgentSpec:
    """Resolved agent manifest ready for WrapperRuntime."""

    name: str
    version: str
    wrapper_cmd: list[str]
    config: dict = field(default_factory=dict)
    env_schema: dict = field(default_factory=dict)
    tools: dict = field(default_factory=dict)


def parse_agent_md(path: Path) -> tuple[dict, str]:
    """Parse an AGENT.md file into (frontmatter_dict, markdown_body).

    The file must start with ``---``, followed by YAML, then ``---``,
    then the markdown body.

    Raises:
        ValueError: If the file has no valid YAML frontmatter delimiters.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"AGENT.md missing frontmatter: {path}")
    # Split after the opening ---
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"AGENT.md missing closing frontmatter delimiter: {path}")
    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return frontmatter, body


def _current_os() -> str:
    """Return the OS key used in ``metadata.strawpot.bin`` and ``tools.install``."""
    import platform

    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    return "linux"


def _resolve_wrapper_cmd(agent_dir: Path, strawpot_meta: dict) -> list[str]:
    """Build the wrapper command from metadata.strawpot.

    Resolution order:
        1. ``bin.<os>`` — compiled binary relative to agent folder,
           keyed by OS (``macos``, ``linux``).
        2. ``wrapper.command`` — external CLI on PATH.

    Args:
        agent_dir: Directory containing the AGENT.md.
        strawpot_meta: The ``metadata.strawpot`` dict from frontmatter.

    Returns:
        Command list, e.g. ``["/path/to/binary"]``.

    Raises:
        ValueError: If wrapper config is missing or command not found on PATH.
    """
    # 1. Compiled binary (metadata.strawpot.bin.<os>)
    bin_map = strawpot_meta.get("bin")
    if bin_map and isinstance(bin_map, dict):
        os_key = _current_os()
        bin_name = bin_map.get(os_key)
        if bin_name is None:
            raise ValueError(
                f"No binary defined for OS {os_key!r} in metadata.strawpot.bin"
            )
        binary_path = agent_dir / bin_name
        if not binary_path.exists():
            # Extract install hint from the same metadata so callers can
            # display an actionable message.
            install_map = strawpot_meta.get("install", {})
            install_hint = install_map.get(_current_os())
            msg = (
                f"Agent binary not found: {binary_path}\n\n"
                "The agent package is installed but its runtime binary is "
                "missing.\nThis usually means the install script failed "
                "(e.g. 'curl' or 'npm' not available)."
            )
            if install_hint:
                msg += f"\n\nTo install the runtime manually, run:\n  {install_hint}"
            raise ValueError(msg)
        return [str(binary_path)]

    # 2. External CLI on PATH (metadata.strawpot.wrapper.command)
    wrapper = strawpot_meta.get("wrapper", {})
    command = wrapper.get("command")

    if command:
        resolved = shutil.which(command)
        if resolved is None:
            raise ValueError(
                f"Wrapper command not found on PATH: {command}\n\n"
                f"Make sure '{command}' is installed and available in your "
                "shell PATH."
            )
        return [resolved]

    raise ValueError(
        "AGENT.md must define metadata.strawpot.bin.<os> "
        "or metadata.strawpot.wrapper.command"
    )


def _merge_config(params: dict, user_config: dict) -> dict:
    """Merge AGENT.md param defaults with user-provided config.

    Extracts ``default`` values from each param definition, then overlays
    user_config on top. User values take precedence.
    """
    defaults = {}
    for key, schema in params.items():
        if "default" in schema:
            defaults[key] = schema["default"]
    return {**defaults, **user_config}


def resolve_agent(
    name: str, project_dir: str, user_config: dict | None = None
) -> AgentSpec:
    """Resolve an agent name to a fully loaded AgentSpec.

    Resolution order:
        1. ``<project_dir>/.strawpot/agents/<name>/AGENT.md`` (project-local)
        2. ``~/.strawpot/agents/<name>/AGENT.md`` (global install)

    Args:
        name: Agent name (e.g. ``"strawpot-claude-code"``).
        project_dir: Project root directory.
        user_config: Per-agent config from ``[agents.<name>]`` in strawpot.toml.

    Returns:
        Resolved AgentSpec.

    Raises:
        FileNotFoundError: If no AGENT.md found in any search path.
    """
    candidates = [
        Path(project_dir) / ".strawpot" / "agents" / name,
        get_strawpot_home() / "agents" / name,
    ]

    agent_dir: Path | None = None
    for candidate in candidates:
        if (candidate / "AGENT.md").is_file():
            agent_dir = candidate
            break

    if agent_dir is None:
        searched = [str(c / "AGENT.md") for c in candidates]
        raise FileNotFoundError(
            f"Agent not found: {name!r}. Searched:\n"
            + "\n".join(f"  - {p}" for p in searched)
        )

    frontmatter, _body = parse_agent_md(agent_dir / "AGENT.md")
    metadata = frontmatter.get("metadata", {})
    strawpot_meta = metadata.get("strawpot", {})

    wrapper_cmd = _resolve_wrapper_cmd(agent_dir, strawpot_meta)
    params = strawpot_meta.get("params", {})
    config = _merge_config(params, user_config or {})
    env_schema = strawpot_meta.get("env", {})
    tools = strawpot_meta.get("tools", {})
    version = metadata.get("version", "0.0.0")

    return AgentSpec(
        name=frontmatter.get("name", name),
        version=version,
        wrapper_cmd=wrapper_cmd,
        config=config,
        env_schema=env_schema,
        tools=tools,
    )


def check_install_prerequisites(agent_dir: Path) -> list[tuple[str, str]]:
    """Check if system prerequisites for an agent's install script are met.

    Examines the install command in AGENT.md frontmatter and identifies
    missing system tools (e.g. ``curl``, ``npm``, ``node``).

    Args:
        agent_dir: Directory containing AGENT.md.

    Returns:
        List of ``(tool_name, guidance)`` tuples for missing prerequisites.
        Empty list if all prerequisites are satisfied.
    """
    try:
        frontmatter, _ = parse_agent_md(agent_dir / "AGENT.md")
    except (ValueError, OSError):
        return []

    meta = frontmatter.get("metadata", {})
    strawpot_meta = meta.get("strawpot", {})
    missing: list[tuple[str, str]] = []

    # Check tools required by the install script itself
    install_map = strawpot_meta.get("install", {})
    install_cmd = install_map.get(_current_os(), "")
    if re.search(r"\bcurl\b", install_cmd) and shutil.which("curl") is None:
        missing.append((
            "curl",
            "Install with your package manager "
            "(e.g. 'apt install curl' or 'brew install curl')",
        ))

    # Check declared tool dependencies
    tools = strawpot_meta.get("tools", {})
    for tool_name, tool_meta in tools.items():
        if shutil.which(tool_name) is None:
            desc = tool_meta.get("description", "")
            install_hints = tool_meta.get("install", {})
            hint = install_hints.get(_current_os(), "")
            guidance = desc
            if hint:
                guidance += f"\n    Install: {hint}"
            missing.append((tool_name, guidance))

    return missing


def validate_agent(spec: AgentSpec) -> ValidationResult:
    """Validate that an agent's external dependencies are satisfied.

    Checks:
        - Each tool declared in ``spec.tools`` is found on PATH via
          ``shutil.which``.
        - Each env var marked ``required: true`` in ``spec.env_schema``
          is set in the current environment.

    Args:
        spec: A resolved AgentSpec.

    Returns:
        ValidationResult with any missing tools or env vars.
    """
    result = ValidationResult()

    for tool_name, tool_meta in spec.tools.items():
        if shutil.which(tool_name) is None:
            install_hint = (tool_meta.get("install", {}) or {}).get(
                _current_os()
            )
            result.missing_tools.append((tool_name, install_hint))

    for var_name, var_meta in spec.env_schema.items():
        if var_meta.get("required") and var_name not in os.environ:
            result.missing_env.append(var_name)

    return result
