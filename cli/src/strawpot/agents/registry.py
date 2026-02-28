"""Agent registry — discover AGENT.md manifests and resolve to AgentSpec."""

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from strawpot.config import get_strawpot_home


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


def _resolve_wrapper_cmd(agent_dir: Path, strawpot_meta: dict) -> list[str]:
    """Build the wrapper command from metadata.strawpot.wrapper.

    Args:
        agent_dir: Directory containing the AGENT.md.
        strawpot_meta: The ``metadata.strawpot`` dict from frontmatter.

    Returns:
        Command list, e.g. ``[sys.executable, "/path/to/wrapper.py"]``.

    Raises:
        ValueError: If wrapper config is missing or command not found on PATH.
    """
    wrapper = strawpot_meta.get("wrapper", {})
    script = wrapper.get("script")
    command = wrapper.get("command")

    if script:
        return [sys.executable, str(agent_dir / script)]

    if command:
        resolved = shutil.which(command)
        if resolved is None:
            raise ValueError(
                f"Wrapper command not found on PATH: {command}"
            )
        return [resolved]

    raise ValueError(
        f"AGENT.md must define metadata.strawpot.wrapper.script or .command"
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
        3. Built-in ``_builtin_agents/<name>/AGENT.md`` (ships with strawpot)

    Args:
        name: Agent name (e.g. ``"claude_code"``).
        project_dir: Project root directory.
        user_config: Per-agent config from ``[agents.<name>]`` in config.toml.

    Returns:
        Resolved AgentSpec.

    Raises:
        FileNotFoundError: If no AGENT.md found in any search path.
    """
    candidates = [
        Path(project_dir) / ".strawpot" / "agents" / name,
        get_strawpot_home() / "agents" / name,
        Path(__file__).parent.parent / "_builtin_agents" / name,
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
