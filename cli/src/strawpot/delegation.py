"""Delegate handler — policy check, resolve, build prompt, spawn, wait."""

import json
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from strawpot.agents.protocol import AgentHandle, AgentResult, AgentRuntime
from strawpot.agents.registry import resolve_agent
from strawpot.agents.wrapper import WrapperRuntime
from strawpot.config import StrawPotConfig, get_strawpot_home
from strawpot.context import (
    build_prompt,
    parse_frontmatter,
    read_role_description,
    read_skill_description,
    validate_frontmatter_slug,
)
from strawpot.memory.protocol import GetResult, MemoryProvider

logger = logging.getLogger(__name__)


class DelegationError(Exception):
    """Base exception for delegation failures."""


class PolicyDenied(DelegationError):
    """Raised when delegation is denied by policy."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass
class DelegateRequest:
    """Incoming delegation request from a parent agent."""

    role_slug: str
    task_text: str
    parent_agent_id: str
    parent_role: str
    run_id: str
    depth: int
    return_format: str = "TEXT"


@dataclass
class DelegateResult:
    """Outcome of a completed delegation."""

    summary: str
    output: str = ""
    exit_code: int = 0


def _check_policy(
    request: DelegateRequest,
    config: StrawPotConfig,
) -> None:
    """Raise PolicyDenied if the request violates policy."""
    if (
        config.allowed_roles is not None
        and request.role_slug not in config.allowed_roles
    ):
        raise PolicyDenied("DENY_ROLE_NOT_ALLOWED")
    if request.depth + 1 > config.max_depth:
        raise PolicyDenied("DENY_DEPTH_LIMIT")


def _validate_output(output: str, return_format: str) -> str | None:
    """Validate agent output against the requested format.

    Returns None if valid, or an error message string if not.
    """
    if return_format.strip().upper() != "JSON":
        return None
    stripped = output.strip()
    if not stripped:
        return "Output is empty; expected valid JSON."
    try:
        json.loads(stripped)
    except json.JSONDecodeError as exc:
        return f"Output is not valid JSON: {exc}"
    return None


def _symlink(src: str, dst: str) -> None:
    """Create a symlink from *dst* pointing to *src*."""
    os.symlink(src, dst)


# ---------------------------------------------------------------------------
# Frontmatter dependency parsing
# ---------------------------------------------------------------------------


def _parse_role_deps(role_path: str) -> tuple[list[str], list[str], bool]:
    """Parse ROLE.md frontmatter to extract direct skill and role dep slugs.

    Returns:
        (skill_slugs, role_slugs, wildcard_roles) — slug strings with version
        specifiers stripped. ``wildcard_roles`` is True if ``"*"`` appears in
        the role dependencies, meaning "depend on all available roles."
    """
    role_md = Path(role_path) / "ROLE.md"
    if not role_md.exists():
        return [], [], False
    text = role_md.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    fm = parsed.get("frontmatter", {})
    deps = (
        fm.get("metadata", {}).get("strawpot", {}).get("dependencies", {})
    )
    if not isinstance(deps, dict):
        return [], [], False

    skill_specs = deps.get("skills", [])
    role_specs = deps.get("roles", [])
    skill_slugs = [spec.split()[0] for spec in skill_specs]
    role_slugs = [spec.split()[0] for spec in role_specs if spec.split()[0] != "*"]
    wildcard_roles = any(spec.strip() == "*" for spec in role_specs)
    return skill_slugs, role_slugs, wildcard_roles


def _parse_skill_deps(skill_path: str) -> list[str]:
    """Parse SKILL.md frontmatter to extract direct skill dep slugs.

    In SKILL.md, ``metadata.strawpot.dependencies`` is a flat list of skill slugs.
    """
    skill_md = Path(skill_path) / "SKILL.md"
    if not skill_md.exists():
        return []
    text = skill_md.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    fm = parsed.get("frontmatter", {})
    deps = (
        fm.get("metadata", {}).get("strawpot", {}).get("dependencies", [])
    )
    if not isinstance(deps, list):
        return []
    return [spec.split()[0] for spec in deps]


def _parse_skill_env(skill_path: str) -> dict[str, dict]:
    """Parse SKILL.md frontmatter to extract env schema.

    Returns:
        Dict mapping var name to metadata
        (e.g. ``{"GITHUB_TOKEN": {"required": True, "description": "..."}}``)
        or empty dict if no env field.
    """
    skill_md = Path(skill_path) / "SKILL.md"
    if not skill_md.exists():
        return {}
    text = skill_md.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    fm = parsed.get("frontmatter", {})
    env = fm.get("metadata", {}).get("strawpot", {}).get("env", {})
    if not isinstance(env, dict):
        return {}
    return env


# ---------------------------------------------------------------------------
# Global skill discovery
# ---------------------------------------------------------------------------


def _check_inherit_global_skills(role_path: str) -> bool:
    """Check if a role inherits global skills.

    Reads ``metadata.strawpot.inherit_global_skills`` from ROLE.md frontmatter.
    Defaults to ``True`` if the field is not present.
    """
    role_md = Path(role_path) / "ROLE.md"
    if not role_md.exists():
        return True
    text = role_md.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    fm = parsed.get("frontmatter", {})
    return fm.get("metadata", {}).get("strawpot", {}).get(
        "inherit_global_skills", True
    )


def _get_default_agent(role_path: str) -> str | None:
    """Extract ``default_agent`` from ROLE.md frontmatter.

    Returns the agent name string if present, or ``None`` if the field
    is missing or the ROLE.md file does not exist.
    """
    role_md = Path(role_path) / "ROLE.md"
    if not role_md.exists():
        return None
    text = role_md.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    fm = parsed.get("frontmatter", {})
    return fm.get("metadata", {}).get("strawpot", {}).get("default_agent")


def discover_global_skills(
    resolved: dict,
) -> list[tuple[str, str, str]]:
    """Discover globally installed skills not already in resolved dependencies.

    Scans ``~/.strawpot/skills/`` for installed skill directories.
    Skips skills whose slug already appears in the resolved dependency list.
    Respects the ``inherit_global_skills`` flag in ROLE.md.

    Args:
        resolved: Resolved role dict from strawhub.resolver.resolve().

    Returns:
        List of (slug, description, path) tuples for global skills.
        Empty list if the role opts out or no global skills are found.
    """
    if not _check_inherit_global_skills(resolved["path"]):
        return []

    skills_dir = get_strawpot_home() / "skills"
    if not skills_dir.is_dir():
        return []

    from strawhub.version_spec import parse_dir_name

    resolved_slugs = {
        dep["slug"]
        for dep in resolved.get("dependencies", [])
        if dep["kind"] == "skill"
    }

    global_skills: list[tuple[str, str, str]] = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        parsed = parse_dir_name(entry.name)
        if parsed is None:
            continue
        slug, _version = parsed
        if slug in resolved_slugs:
            continue
        validate_frontmatter_slug(str(entry), slug, "skill")
        desc = read_skill_description(str(entry))
        global_skills.append((slug, desc, str(entry)))

    return global_skills


def _discover_all_roles() -> list[tuple[str, str]]:
    """Discover all globally installed roles.

    Scans ``~/.strawpot/roles/`` for installed role directories.

    Returns:
        List of (slug, path) tuples for each installed role.
    """
    from strawhub.version_spec import parse_dir_name

    roles_dir = get_strawpot_home() / "roles"
    if not roles_dir.is_dir():
        return []

    roles: list[tuple[str, str]] = []
    for entry in sorted(roles_dir.iterdir()):
        if not entry.is_dir():
            continue
        parsed = parse_dir_name(entry.name)
        if parsed is None:
            continue
        slug, _version = parsed
        roles.append((slug, str(entry)))
    return roles


# ---------------------------------------------------------------------------
# Skill env collection and validation
# ---------------------------------------------------------------------------


def _merge_env_entry(target: dict[str, dict], var: str, meta: dict) -> None:
    """Merge a single env entry into *target*, preferring ``required=True``."""
    if var not in target:
        target[var] = dict(meta)
    elif meta.get("required") and not target[var].get("required"):
        target[var] = dict(meta)


def collect_skill_env(
    resolved: dict,
    global_skills: list[tuple[str, str, str]] | None = None,
) -> dict[str, dict]:
    """Collect env requirements from all skills in a role's dependency tree.

    Walks the full dependency graph:

    1. The role's own transitive skill dependencies (skill → skill chain).
    2. Each delegatable role's transitive skill dependencies (recursive).
    3. Global skills (if ``inherit_global_skills`` is true).

    If the same var appears in multiple skills, ``required: True`` wins.

    Args:
        resolved: Resolved role dict from ``strawhub.resolver.resolve()``.
        global_skills: Optional list of ``(slug, description, path)`` tuples.

    Returns:
        Merged dict mapping var name to metadata.
    """
    merged: dict[str, dict] = {}
    all_deps = resolved.get("dependencies", [])

    # Build lookups
    role_lookup: dict[str, dict] = {}
    for dep in all_deps:
        if dep["kind"] == "role":
            role_lookup[dep["slug"]] = dep

    visited_roles: set[str] = set()

    def _collect_from_role(role_path: str, role_slug: str) -> None:
        if role_slug in visited_roles:
            return
        visited_roles.add(role_slug)

        skill_slugs, child_role_slugs, _ = _parse_role_deps(role_path)
        skill_deps = _collect_transitive_skills(skill_slugs, all_deps)
        for dep in skill_deps:
            for var, meta in _parse_skill_env(dep["path"]).items():
                _merge_env_entry(merged, var, meta)

        # Recurse into delegatable roles
        for child_slug in child_role_slugs:
            child = role_lookup.get(child_slug)
            if child is not None:
                _collect_from_role(child["path"], child_slug)

    # Start from the resolved role itself
    _collect_from_role(resolved["path"], resolved["slug"])

    if global_skills:
        for _slug, _desc, gpath in global_skills:
            for var, meta in _parse_skill_env(gpath).items():
                _merge_env_entry(merged, var, meta)

    return merged


def validate_skill_env(
    env_schema: dict[str, dict],
    saved_env: dict[str, str] | None = None,
) -> "ValidationResult":
    """Validate that required skill env vars are set.

    Resolution order per variable:

    1. ``os.environ`` — an explicit shell variable always wins.
    2. *saved_env* — values persisted in ``strawpot.toml``.  If found
       here the value is injected into ``os.environ`` so sub-agents
       inherit it.
    3. If neither source provides a value and the variable is required,
       it is reported as missing.

    Args:
        env_schema: Merged env schema from :func:`collect_skill_env`.
        saved_env: Optional flat dict of saved env values from config.

    Returns:
        :class:`~strawpot.agents.registry.ValidationResult` with any
        missing required env vars.
    """
    from strawpot.agents.registry import ValidationResult

    result = ValidationResult()
    for var_name, var_meta in env_schema.items():
        if var_name in os.environ:
            continue
        if saved_env and var_name in saved_env:
            os.environ[var_name] = saved_env[var_name]
            continue
        if var_meta.get("required"):
            result.missing_env.append(var_name)
    return result


def _collect_saved_env(
    config: StrawPotConfig,
    resolved: dict,
    global_skills: list[tuple[str, str, str]] | None = None,
) -> dict[str, str]:
    """Collect saved env values from config for all skills in a role's tree.

    Walks the dependency list and global skills, returning a flat dict of
    saved env key-value pairs from ``config.skills``.
    """
    saved: dict[str, str] = {}
    for dep in resolved.get("dependencies", []):
        if dep["kind"] == "skill":
            saved.update(config.skills.get(dep["slug"], {}))
    if global_skills:
        for slug, _desc, _path in global_skills:
            saved.update(config.skills.get(slug, {}))
    return saved


# ---------------------------------------------------------------------------
# Session-level role staging
# ---------------------------------------------------------------------------


def _collect_transitive_skills(
    direct_skill_slugs: list[str],
    all_deps: list[dict],
) -> list[dict]:
    """Collect transitive skill dependencies for a role's own skills.

    DFS through SKILL.md frontmatters starting from *direct_skill_slugs*.
    Uses *all_deps* as a path lookup.  Only skills reachable through the
    skill dependency chain are included — skills from dependent roles are
    excluded.

    Returns:
        List of dep dicts in topological order (leaves first).
    """
    skill_lookup: dict[str, dict] = {}
    for dep in all_deps:
        if dep["kind"] == "skill":
            skill_lookup[dep["slug"]] = dep

    collected: dict[str, dict] = {}
    visited: set[str] = set()

    def _dfs(slug: str) -> None:
        if slug in visited:
            return
        visited.add(slug)
        dep = skill_lookup.get(slug)
        if dep is None:
            return
        child_slugs = _parse_skill_deps(dep["path"])
        for child in child_slugs:
            _dfs(child)
        collected[slug] = dep

    for slug in direct_skill_slugs:
        _dfs(slug)

    return list(collected.values())


def _read_staged_paths(
    role_stage_dir: str,
) -> tuple[str, str]:
    """Return the skills and roles parent directories from an already-staged role dir."""
    skills_dir = os.path.join(role_stage_dir, "skills")
    roles_dir = os.path.join(role_stage_dir, "roles")
    return skills_dir, roles_dir


def stage_role(
    session_dir: str,
    resolved: dict,
    global_skills: list[tuple[str, str, str]] | None = None,
) -> tuple[str, str]:
    """Stage a resolved role into the session directory.

    Creates::

        session_dir/roles/<slug>/
            ROLE.md                  — copied from installed path
            skills/<dep_slug>/       — symlinked (transitive skill deps only)
            skills/<global_slug>/    — symlinked (global skills, if not already present)
            roles/<dep_slug>/        — symlinked (direct role deps only)

    Idempotent: if the directory already exists, returns paths from the
    existing staging without re-creating.

    Args:
        session_dir: Session directory path.
        resolved: Resolved role dict from strawhub.resolver.resolve().
        global_skills: Optional list of (slug, description, path) tuples
            for globally installed skills to stage alongside deps.

    Returns:
        (skills_dir, roles_dir) — parent directories containing staged
        skill and role subdirectories.
    """
    slug = resolved["slug"]
    role_stage_dir = os.path.join(session_dir, "roles", slug)

    if os.path.isdir(role_stage_dir):
        return _read_staged_paths(role_stage_dir)

    os.makedirs(role_stage_dir, exist_ok=True)

    # Validate frontmatter name matches slug for the role and all deps
    validate_frontmatter_slug(resolved["path"], slug, "role")
    all_deps = resolved.get("dependencies", [])
    for dep in all_deps:
        validate_frontmatter_slug(dep["path"], dep["slug"], dep["kind"])

    # Copy ROLE.md from installed path
    src_role_md = os.path.join(resolved["path"], "ROLE.md")
    dst_role_md = os.path.join(role_stage_dir, "ROLE.md")
    shutil.copy2(src_role_md, dst_role_md)

    # Parse direct dependencies from frontmatter
    direct_skill_slugs, direct_role_slugs, wildcard_roles = _parse_role_deps(
        resolved["path"]
    )

    # Stage transitive skill deps (for this role's own skills only)
    skill_deps = _collect_transitive_skills(direct_skill_slugs, all_deps)
    skills_dir = os.path.join(role_stage_dir, "skills")
    os.makedirs(skills_dir, exist_ok=True)
    for dep in skill_deps:
        dest = os.path.join(skills_dir, dep["slug"])
        _symlink(dep["path"], dest)

    # Stage global skills (skip if slug already present from deps)
    if global_skills:
        for gslug, _desc, gpath in global_skills:
            validate_frontmatter_slug(gpath, gslug, "skill")
            dest = os.path.join(skills_dir, gslug)
            if not os.path.exists(dest):
                _symlink(gpath, dest)

    # Stage role deps
    roles_dir = os.path.join(role_stage_dir, "roles")
    os.makedirs(roles_dir, exist_ok=True)

    if wildcard_roles:
        # "*" — stage all globally installed roles
        for role_slug, role_path in _discover_all_roles():
            if role_slug == slug:  # skip self
                continue
            dest = os.path.join(roles_dir, role_slug)
            if not os.path.exists(dest):
                _symlink(role_path, dest)
    else:
        # Stage direct role deps only (symlink to installed paths)
        role_lookup = {d["slug"]: d for d in all_deps if d["kind"] == "role"}
        for role_slug in direct_role_slugs:
            dep = role_lookup.get(role_slug)
            if dep is None:
                continue
            dest = os.path.join(roles_dir, role_slug)
            _symlink(dep["path"], dest)

    return skills_dir, roles_dir


def create_agent_workspace(session_dir: str, agent_id: str) -> str:
    """Create a per-agent workspace under the session directory.

    Returns:
        Path to the agent workspace directory.
    """
    workspace = os.path.join(session_dir, "agents", agent_id)
    os.makedirs(workspace, exist_ok=True)
    return workspace


# ---------------------------------------------------------------------------
# Delegatable roles
# ---------------------------------------------------------------------------


def _build_delegatable_roles(
    config: StrawPotConfig,
    current_role: str,
    resolve_role_dirs: Callable[[str], str | None],
    requester_role: str | None = None,
) -> list[tuple[str, str]]:
    """Build list of (slug, description) for roles the sub-agent can delegate to.

    Excludes the current role and the requester role. Only includes roles
    in allowed_roles (if set) that have resolvable directories.
    """
    if config.allowed_roles is None:
        return []

    skip = {current_role}
    if requester_role:
        skip.add(requester_role)

    roles: list[tuple[str, str]] = []
    for slug in config.allowed_roles:
        if slug in skip:
            continue
        role_dir = resolve_role_dirs(slug)
        if role_dir is None:
            continue
        desc = read_role_description(role_dir)
        roles.append((slug, desc))
    return roles


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------


def _format_memory_prompt(get_result: GetResult) -> str:
    """Format context cards from a memory.get result into prompt text."""
    parts = []
    for card in get_result.context_cards:
        parts.append(f"[{card.kind.value}] {card.content}")
    return "\n\n".join(parts)


def _agent_status(result: AgentResult, *, timed_out: bool = False) -> str:
    """Map an agent result to a status string for memory.dump."""
    if timed_out:
        return "timeout"
    return "success" if result.exit_code == 0 else "failure"


# ---------------------------------------------------------------------------
# Delegate handler
# ---------------------------------------------------------------------------


def handle_delegate(
    *,
    request: DelegateRequest,
    config: StrawPotConfig,
    runtime: AgentRuntime,
    working_dir: str,
    session_dir: str,
    resolve_role: Callable[..., dict],
    resolve_role_dirs: Callable[[str], str | None],
    denden_addr: str | None = None,
    memory_provider: MemoryProvider | None = None,
) -> DelegateResult:
    """Handle a delegation request end-to-end.

    Steps:
      1. Policy check (allowed_roles, max_depth)
      2. Resolve role + skills via resolver
      3. Build delegatable roles list for sub-agent
      4. Build system prompt
      5. Stage role (session-level, idempotent)
      6. Create agent workspace
      7. Spawn sub-agent
      8. Wait for completion
      9. Return result

    Args:
        request: The delegation request.
        config: Merged StrawPot configuration.
        runtime: Agent runtime (WrapperRuntime) for spawning.
        working_dir: Session worktree path (shared by all agents).
        session_dir: Session directory for staging and workspaces.
        resolve_role: Callable to resolve a role slug to a resolved dict.
            Signature: (slug, kind="role") -> dict.
        resolve_role_dirs: Callable that maps a role slug to its directory
            path (or None if not resolvable). Used to build delegatable roles.
        denden_addr: Actual bound denden address. If provided, takes
            precedence over ``config.denden_addr``.
        memory_provider: Optional memory provider. When set, ``get()``
            is called before spawn and ``dump()`` after wait.

    Returns:
        DelegateResult with summary and output from the sub-agent.

    Raises:
        PolicyDenied: If the delegation violates policy constraints.
    """
    # 1. Policy check
    _check_policy(request, config)

    # 2. Resolve role + skills
    resolved = resolve_role(request.role_slug, kind="role")

    # 2b. Discover global skills
    global_skills = discover_global_skills(resolved)

    # 2c. Validate skill env requirements (non-interactive)
    skill_env = collect_skill_env(resolved, global_skills=global_skills or None)
    saved_env = _collect_saved_env(config, resolved, global_skills=global_skills or None)
    skill_validation = validate_skill_env(skill_env, saved_env=saved_env)
    if not skill_validation.ok:
        missing = ", ".join(skill_validation.missing_env)
        raise DelegationError(
            f"Missing required environment variables for role "
            f"'{request.role_slug}': {missing}. "
            f"Set these variables before starting the session."
        )

    # 2d. Resolve per-role default agent (config override > frontmatter)
    role_override = config.roles.get(request.role_slug, {})
    default_agent_name = role_override.get(
        "default_agent", _get_default_agent(resolved["path"])
    )
    if default_agent_name and default_agent_name != runtime.name:
        try:
            agent_spec = resolve_agent(
                default_agent_name,
                working_dir,
                config.agents.get(default_agent_name),
            )
            runtime = WrapperRuntime(agent_spec, session_dir=session_dir)
            logger.info(
                "Using default_agent %r for role %r",
                default_agent_name,
                request.role_slug,
            )
        except FileNotFoundError:
            logger.warning(
                "default_agent %r not found for role %r; "
                "falling back to session default %r",
                default_agent_name,
                request.role_slug,
                runtime.name,
            )

    # 3. Build delegatable roles for the sub-agent
    delegatable = _build_delegatable_roles(
        config, request.role_slug, resolve_role_dirs,
        requester_role=request.parent_role,
    )

    # 4. Build prompt
    role_prompt = build_prompt(
        resolved,
        delegatable_roles=delegatable or None,
        requester_role=request.parent_role,
        global_skills=[(s, d) for s, d, _ in global_skills] or None,
    )

    # 5. Stage role (session-level, idempotent)
    skills_dir, roles_dir = stage_role(
        session_dir, resolved, global_skills=global_skills or None
    )

    # 6-9. Spawn/wait loop with retry on format validation failure
    max_attempts = 1 + config.max_delegate_retries
    task_text = request.task_text
    result: AgentResult | None = None

    for attempt in range(max_attempts):
        # 6. Create agent workspace (fresh per attempt)
        agent_id = f"agent_{uuid.uuid4().hex[:12]}"
        workspace = create_agent_workspace(session_dir, agent_id)

        # 6b. Link requester role into session-level per-agent dir
        roles_dirs = [roles_dir]
        requester_role_dir = resolve_role_dirs(request.parent_role)
        if requester_role_dir is not None:
            req_roles_dir = os.path.join(
                session_dir, "requester_roles", agent_id
            )
            req_dest = os.path.join(req_roles_dir, request.parent_role)
            if not os.path.exists(req_dest):
                os.makedirs(req_roles_dir, exist_ok=True)
                _symlink(requester_role_dir, req_dest)
            roles_dirs.append(req_roles_dir)

        # 7a. Memory get — retrieve context before spawn
        memory_prompt = ""
        if memory_provider is not None:
            get_result = memory_provider.get(
                session_id=request.run_id,
                agent_id=agent_id,
                role=request.role_slug,
                behavior_ref=role_prompt,
                task=task_text,
                parent_agent_id=request.parent_agent_id,
            )
            if get_result.context_cards:
                memory_prompt = _format_memory_prompt(get_result)

        # 7b. Spawn
        env = {
            "DENDEN_ADDR": denden_addr or config.denden_addr,
            "DENDEN_AGENT_ID": agent_id,
            "DENDEN_PARENT_AGENT_ID": request.parent_agent_id,
            "DENDEN_RUN_ID": request.run_id,
            "PERMISSION_MODE": "auto",
        }

        handle: AgentHandle = runtime.spawn(
            agent_id=agent_id,
            working_dir=working_dir,
            agent_workspace_dir=workspace,
            role_prompt=role_prompt,
            memory_prompt=memory_prompt,
            skills_dir=skills_dir,
            roles_dirs=roles_dirs,
            task=task_text,
            env=env,
        )

        # 8. Wait
        result = runtime.wait(handle, timeout=config.agent_timeout)

        # 8a. Memory dump — record result after wait
        timed_out = (
            config.agent_timeout is not None and runtime.is_alive(handle)
        )
        if memory_provider is not None:
            memory_provider.dump(
                session_id=request.run_id,
                agent_id=agent_id,
                role=request.role_slug,
                behavior_ref=role_prompt,
                task=task_text,
                status=_agent_status(result, timed_out=timed_out),
                output=result.output,
                parent_agent_id=request.parent_agent_id,
            )

        # 8b. Handle timeout — no retry on timeout
        if timed_out:
            runtime.kill(handle)
            return DelegateResult(
                summary=f"Agent timed out after {config.agent_timeout}s",
                output=result.output,
                exit_code=1,
            )

        # 8c. No retry on non-zero exit
        if result.exit_code != 0:
            return DelegateResult(
                summary=result.summary,
                output=result.output,
                exit_code=result.exit_code,
            )

        # 8d. Validate output format
        validation_error = _validate_output(
            result.output, request.return_format
        )
        if validation_error is None:
            return DelegateResult(
                summary=result.summary,
                output=result.output,
                exit_code=result.exit_code,
            )

        # 8e. Validation failed — retry or give up
        if attempt == max_attempts - 1:
            logger.warning(
                "Delegation to %s failed format validation after %d "
                "attempt(s): %s",
                request.role_slug,
                max_attempts,
                validation_error,
            )
            return DelegateResult(
                summary=result.summary,
                output=result.output,
                exit_code=result.exit_code,
            )

        logger.info(
            "Retrying delegation to %s (attempt %d/%d): %s",
            request.role_slug,
            attempt + 2,
            max_attempts,
            validation_error,
        )
        task_text = (
            f"{request.task_text}\n\n"
            f"[RETRY: Your previous output was not valid JSON. "
            f"{validation_error} "
            f"Please output valid JSON only.]"
        )

    # Defensive: should never reach here
    assert result is not None
    return DelegateResult(
        summary=result.summary,
        output=result.output,
        exit_code=result.exit_code,
    )
