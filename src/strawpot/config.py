"""Configuration loading — TOML files merged from global and project scopes."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def get_strawpot_home() -> Path:
    """Return the global strawpot directory.

    Uses STRAWPOT_HOME env var if set, otherwise ~/.strawpot/.
    """
    env = os.environ.get("STRAWPOT_HOME")
    if env:
        return Path(env)
    return Path.home() / ".strawpot"


@dataclass
class StrawpotConfig:
    runtime: str = "claude_code"
    isolation: str = "none"
    denden_addr: str = "127.0.0.1:9700"
    orchestrator_role: str = "orchestrator"
    allowed_roles: list[str] | None = None
    max_depth: int = 3
    agents: dict[str, dict] = field(default_factory=dict)


def _read_toml(path: Path) -> dict:
    """Read a TOML file, returning empty dict if it doesn't exist."""
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _apply(config: StrawpotConfig, data: dict) -> None:
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

    policy = data.get("policy", {})
    if "allowed_roles" in policy:
        config.allowed_roles = policy["allowed_roles"]
    if "max_depth" in policy:
        config.max_depth = policy["max_depth"]

    agents = data.get("agents", {})
    for name, agent_data in agents.items():
        config.agents.setdefault(name, {}).update(agent_data)


def load_config(project_dir: Path | None = None) -> StrawpotConfig:
    """Load config merging: defaults < global < project-level.

    Global: $STRAWPOT_HOME/config.toml (default ~/.strawpot/config.toml)
    Project: <project_dir>/.strawpot/config.toml
    """
    config = StrawpotConfig()

    # Global config
    global_path = get_strawpot_home() / "config.toml"
    _apply(config, _read_toml(global_path))

    # Project config
    if project_dir:
        project_path = project_dir / ".strawpot" / "config.toml"
        _apply(config, _read_toml(project_path))

    return config
