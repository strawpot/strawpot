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


@dataclass
class StrawPotConfig:
    runtime: str = "strawpot-claude-code"
    denden_addr: str = "127.0.0.1:9700"
    orchestrator_role: str = "ai-ceo"
    max_depth: int = 3
    permission_mode: str = "default"
    agent_timeout: int | None = None
    max_delegate_retries: int = 0
    cache_delegations: bool = True
    cache_max_entries: int = 0  # 0 = unlimited
    cache_ttl_seconds: int = 0  # 0 = unlimited
    max_num_delegations: int = 0  # 0 = unlimited
    agents: dict[str, dict] = field(default_factory=dict)
    skills: dict[str, dict[str, str]] = field(default_factory=dict)
    roles: dict[str, dict] = field(default_factory=dict)
    memory: str = "dial"
    memory_config: dict[str, str] = field(default_factory=dict)
    semantic_search: bool = False
    memory_graph: bool = True
    pull_before_session: str = "prompt"
    trace: bool = True
    skip_update_check: bool = False


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

    denden = data.get("denden", {})
    if "addr" in denden:
        config.denden_addr = denden["addr"]

    orch = data.get("orchestrator", {})
    if "role" in orch:
        config.orchestrator_role = orch["role"]
    if "permission_mode" in orch:
        config.permission_mode = orch["permission_mode"]

    policy = data.get("policy", {})
    if "max_depth" in policy:
        config.max_depth = policy["max_depth"]
    if "agent_timeout" in policy:
        config.agent_timeout = policy["agent_timeout"]
    if "max_delegate_retries" in policy:
        config.max_delegate_retries = policy["max_delegate_retries"]
    if "cache_delegations" in policy:
        config.cache_delegations = policy["cache_delegations"]
    if "cache_max_entries" in policy:
        config.cache_max_entries = policy["cache_max_entries"]
    if "cache_ttl_seconds" in policy:
        config.cache_ttl_seconds = policy["cache_ttl_seconds"]
    if "max_num_delegations" in policy:
        config.max_num_delegations = policy["max_num_delegations"]

    agents = data.get("agents", {})
    for name, agent_data in agents.items():
        config.agents.setdefault(name, {}).update(agent_data)

    skills_section = data.get("skills", {})
    for slug, skill_data in skills_section.items():
        if not isinstance(skill_data, dict):
            continue
        env_data = skill_data.get("env", {})
        if env_data:
            config.skills.setdefault(slug, {}).update(env_data)

    roles_section = data.get("roles", {})
    for slug, role_data in roles_section.items():
        if not isinstance(role_data, dict):
            continue
        config.roles.setdefault(slug, {}).update(role_data)

    if "memory" in data:
        config.memory = data["memory"]
    memory_cfg = data.get("memory_config", {})
    for key, value in memory_cfg.items():
        config.memory_config[key] = value

    memory_section = data.get("memory_settings", {})
    if "semantic_search" in memory_section:
        config.semantic_search = bool(memory_section["semantic_search"])
    if "graph" in memory_section:
        config.memory_graph = bool(memory_section["graph"])

    session = data.get("session", {})
    if "pull_before_session" in session:
        config.pull_before_session = session["pull_before_session"]

    trace_section = data.get("trace", {})
    if "enabled" in trace_section:
        config.trace = trace_section["enabled"]

    if "skip_update_check" in data:
        config.skip_update_check = data["skip_update_check"]


def has_explicit_runtime(project_dir: Path | None = None) -> bool:
    """Return True if a ``runtime`` key is explicitly set in any config file.

    Checks the global config and, if *project_dir* is given, the project-level
    config.  Returns False when the runtime is only the dataclass default.
    """
    global_data = _read_toml(get_strawpot_home() / "strawpot.toml")
    if "runtime" in global_data:
        return True
    if project_dir:
        project_data = _read_toml(project_dir / "strawpot.toml")
        if "runtime" in project_data:
            return True
    return False


def ensure_global_config() -> Path:
    """Create the global strawpot.toml with recommended defaults if missing.

    Returns the path to the global config file.
    """
    import tomli_w

    path = get_strawpot_home() / "strawpot.toml"
    if path.is_file():
        return path

    defaults = {
        "memory": "dial",
        "policy": {
            "cache_delegations": True,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(defaults, f)
    return path


def load_config(project_dir: Path | None = None) -> StrawPotConfig:
    """Load config merging: defaults < global < project-level.

    Global: $STRAWPOT_HOME/strawpot.toml (default ~/.strawpot/strawpot.toml)
    Project: <project_dir>/strawpot.toml
    """
    config = StrawPotConfig()

    # Global config
    global_path = get_strawpot_home() / "strawpot.toml"
    _apply(config, _read_toml(global_path))

    # Project config
    if project_dir:
        project_path = project_dir / "strawpot.toml"
        _apply(config, _read_toml(project_path))

    return config


def save_skill_env(
    project_dir: Path | None,
    slug: str,
    env_values: dict[str, str],
) -> None:
    """Persist skill env values to strawpot.toml.

    Writes to the project-local file when *project_dir* is given,
    otherwise to the global config.  Creates the file if it doesn't
    exist and merges into existing content.
    """
    import tomli_w

    if project_dir:
        toml_path = project_dir / "strawpot.toml"
    else:
        toml_path = get_strawpot_home() / "strawpot.toml"

    existing = _read_toml(toml_path)
    existing.setdefault("skills", {}).setdefault(slug, {}).setdefault(
        "env", {}
    ).update(env_values)

    toml_path.parent.mkdir(parents=True, exist_ok=True)
    with open(toml_path, "wb") as f:
        tomli_w.dump(existing, f)


def save_resource_config(
    project_dir: Path | None,
    resource_type: str,
    name: str,
    env_values: dict[str, str] | None = None,
    param_values: dict | None = None,
) -> None:
    """Persist resource env/param values to strawpot.toml.

    Writes to the project-local file when *project_dir* is given,
    otherwise to the global config.  Creates the file if it doesn't
    exist and merges into existing content.

    TOML paths by resource type:
        skills:   [skills.<name>.env]
        agents:   [agents.<name>.env] + [agents.<name>].<param>
        memories: [memories.<name>.env] + [memory_config].<param>
        roles:    [roles.<name>].<param>  (e.g. default_agent)
    """
    import tomli_w

    if project_dir:
        toml_path = project_dir / "strawpot.toml"
    else:
        toml_path = get_strawpot_home() / "strawpot.toml"

    existing = _read_toml(toml_path)

    def _ensure_dict(section: dict, key: str) -> dict:
        """Ensure section[key] is a dict, replacing string values like '*'."""
        val = section.get(key)
        if not isinstance(val, dict):
            section[key] = {}
        return section[key]

    if resource_type == "roles":
        if param_values:
            roles = existing.setdefault("roles", {})
            role_section = _ensure_dict(roles, name)
            role_section.update(param_values)

    elif resource_type == "skills":
        if env_values:
            skills = existing.setdefault("skills", {})
            skill_section = _ensure_dict(skills, name)
            skill_section.setdefault("env", {}).update(env_values)

    elif resource_type == "agents":
        agents = existing.setdefault("agents", {})
        agent_section = _ensure_dict(agents, name)
        if env_values:
            agent_section.setdefault("env", {}).update(env_values)
        if param_values:
            for k, v in param_values.items():
                if k != "env":
                    agent_section[k] = v

    elif resource_type == "memories":
        if env_values:
            existing.setdefault("memories", {}).setdefault(name, {}).setdefault(
                "env", {}
            ).update(env_values)
        if param_values:
            existing.setdefault("memory_config", {}).update(param_values)

    toml_path.parent.mkdir(parents=True, exist_ok=True)
    with open(toml_path, "wb") as f:
        tomli_w.dump(existing, f)
