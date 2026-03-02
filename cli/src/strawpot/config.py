"""Configuration loading — TOML files merged from global and project scopes."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def get_strawpot_home() -> Path:
    """Return the global strawpot directory.

    Uses ``STRAWPOT_HOME`` env var if set, otherwise ``~/.strawpot/``.
    """
    env = os.environ.get("STRAWPOT_HOME")
    if env:
        return Path(env)
    return Path.home() / ".strawpot"


_DEFAULT_PR_COMMAND = "gh pr create --base {base_branch} --head {session_branch}"


@dataclass
class StrawPotConfig:
    runtime: str = "claude_code"
    isolation: str = "none"
    denden_addr: str = "127.0.0.1:9700"
    orchestrator_role: str = "orchestrator"
    allowed_roles: list[str] | None = None
    max_depth: int = 3
    permission_mode: str = "default"
    agent_timeout: int | None = None
    max_delegate_retries: int = 0
    agents: dict[str, dict] = field(default_factory=dict)
    memory: str | None = None
    memory_config: dict[str, str] = field(default_factory=dict)
    merge_strategy: str = "auto"
    pull_before_session: str = "prompt"
    pr_command: str = _DEFAULT_PR_COMMAND


def _read_toml(path: Path) -> dict:
    """Read a TOML file, returning empty dict if it doesn't exist."""
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _apply(config: StrawPotConfig, data: dict) -> None:
    """Apply a parsed TOML dict onto a config, mutating in place."""
    if "runtime" in data:
        config.runtime = data["runtime"]
    if "isolation" in data:
        config.isolation = data["isolation"]

    denden = data.get("denden", {})
    if "addr" in denden:
        config.denden_addr = denden["addr"]

    orch = data.get("orchestrator", {})
    if "role" in orch:
        config.orchestrator_role = orch["role"]
    if "permission_mode" in orch:
        config.permission_mode = orch["permission_mode"]

    policy = data.get("policy", {})
    if "allowed_roles" in policy:
        config.allowed_roles = policy["allowed_roles"]
    if "max_depth" in policy:
        config.max_depth = policy["max_depth"]
    if "agent_timeout" in policy:
        config.agent_timeout = policy["agent_timeout"]
    if "max_delegate_retries" in policy:
        config.max_delegate_retries = policy["max_delegate_retries"]

    agents = data.get("agents", {})
    for name, agent_data in agents.items():
        config.agents.setdefault(name, {}).update(agent_data)

    if "memory" in data:
        config.memory = data["memory"]
    memory_cfg = data.get("memory_config", {})
    for key, value in memory_cfg.items():
        config.memory_config[key] = value

    session = data.get("session", {})
    if "merge_strategy" in session:
        config.merge_strategy = session["merge_strategy"]
    if "pull_before_session" in session:
        config.pull_before_session = session["pull_before_session"]
    if "pr_command" in session:
        config.pr_command = session["pr_command"]


def load_config(project_dir: Path | None = None) -> StrawPotConfig:
    """Load config merging: defaults < global < project-level.

    Global: $STRAWPOT_HOME/config.toml (default ~/.strawpot/config.toml)
    Project: <project_dir>/.strawpot/config.toml
    """
    config = StrawPotConfig()

    # Global config
    global_path = get_strawpot_home() / "config.toml"
    _apply(config, _read_toml(global_path))

    # Project config
    if project_dir:
        project_path = project_dir / ".strawpot" / "config.toml"
        _apply(config, _read_toml(project_path))

    return config
