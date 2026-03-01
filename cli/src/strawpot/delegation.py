"""Delegate handler — policy check, resolve, build prompt, spawn, wait."""

import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from strawpot.agents.protocol import AgentHandle, AgentResult, AgentRuntime
from strawpot.config import StrawPotConfig
from strawpot.context import build_prompt, parse_frontmatter, read_role_description


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


def _link_or_copy(src: str, dst: str) -> None:
    """Symlink src to dst, falling back to copy on Windows or permission errors."""
    try:
        os.symlink(src, dst, target_is_directory=True)
    except OSError:
        shutil.copytree(src, dst)


# ---------------------------------------------------------------------------
# Frontmatter dependency parsing
# ---------------------------------------------------------------------------


def _parse_role_deps(role_path: str) -> tuple[list[str], list[str]]:
    """Parse ROLE.md frontmatter to extract direct skill and role dep slugs.

    Returns:
        (skill_slugs, role_slugs) — slug strings with version specifiers stripped.
    """
    role_md = Path(role_path) / "ROLE.md"
    if not role_md.exists():
        return [], []
    text = role_md.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    fm = parsed.get("frontmatter", {})
    deps = (
        fm.get("metadata", {}).get("strawpot", {}).get("dependencies", {})
    )
    if not isinstance(deps, dict):
        return [], []

    skill_specs = deps.get("skills", [])
    role_specs = deps.get("roles", [])
    skill_slugs = [spec.split()[0] for spec in skill_specs]
    role_slugs = [spec.split()[0] for spec in role_specs]
    return skill_slugs, role_slugs


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
) -> tuple[list[str], list[str]]:
    """Reconstruct skills_dirs and roles_dirs from an already-staged role dir."""
    skills_dirs: list[str] = []
    roles_dirs: list[str] = []

    skills_dir = os.path.join(role_stage_dir, "skills")
    if os.path.isdir(skills_dir):
        for name in sorted(os.listdir(skills_dir)):
            path = os.path.join(skills_dir, name)
            if os.path.isdir(path):
                skills_dirs.append(path)

    roles_dir = os.path.join(role_stage_dir, "roles")
    if os.path.isdir(roles_dir):
        for name in sorted(os.listdir(roles_dir)):
            path = os.path.join(roles_dir, name)
            if os.path.isdir(path):
                roles_dirs.append(path)

    return skills_dirs, roles_dirs


def stage_role(
    session_dir: str,
    resolved: dict,
) -> tuple[list[str], list[str]]:
    """Stage a resolved role into the session directory.

    Creates::

        session_dir/roles/<slug>/
            ROLE.md                  — copied from installed path
            skills/<dep_slug>/       — symlinked (transitive skill deps only)
            roles/<dep_slug>/        — symlinked (direct role deps only)

    Idempotent: if the directory already exists, returns paths from the
    existing staging without re-creating.

    Returns:
        (skills_dirs, roles_dirs)
    """
    slug = resolved["slug"]
    role_stage_dir = os.path.join(session_dir, "roles", slug)

    if os.path.isdir(role_stage_dir):
        return _read_staged_paths(role_stage_dir)

    os.makedirs(role_stage_dir, exist_ok=True)

    # Copy ROLE.md from installed path
    src_role_md = os.path.join(resolved["path"], "ROLE.md")
    dst_role_md = os.path.join(role_stage_dir, "ROLE.md")
    shutil.copy2(src_role_md, dst_role_md)

    # Parse direct dependencies from frontmatter
    direct_skill_slugs, direct_role_slugs = _parse_role_deps(resolved["path"])
    all_deps = resolved.get("dependencies", [])

    # Stage transitive skill deps (for this role's own skills only)
    skill_deps = _collect_transitive_skills(direct_skill_slugs, all_deps)
    skills_dir = os.path.join(role_stage_dir, "skills")
    os.makedirs(skills_dir, exist_ok=True)
    skills_dirs: list[str] = []
    for dep in skill_deps:
        dest = os.path.join(skills_dir, dep["slug"])
        _link_or_copy(dep["path"], dest)
        skills_dirs.append(dest)

    # Stage direct role deps only (symlink to installed paths)
    role_lookup = {d["slug"]: d for d in all_deps if d["kind"] == "role"}
    roles_sub_dir = os.path.join(role_stage_dir, "roles")
    os.makedirs(roles_sub_dir, exist_ok=True)
    roles_dirs: list[str] = []
    for role_slug in direct_role_slugs:
        dep = role_lookup.get(role_slug)
        if dep is None:
            continue
        dest = os.path.join(roles_sub_dir, role_slug)
        _link_or_copy(dep["path"], dest)
        roles_dirs.append(dest)

    return skills_dirs, roles_dirs


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

    Returns:
        DelegateResult with summary and output from the sub-agent.

    Raises:
        PolicyDenied: If the delegation violates policy constraints.
    """
    # 1. Policy check
    _check_policy(request, config)

    # 2. Resolve role + skills
    resolved = resolve_role(request.role_slug, kind="role")

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
    )

    # 5. Stage role (session-level, idempotent)
    skills_dirs, roles_dirs = stage_role(session_dir, resolved)

    # 5b. Add requester role path to roles_dirs
    requester_role_dir = resolve_role_dirs(request.parent_role)
    if requester_role_dir is not None:
        already_present = any(
            os.path.basename(d) == request.parent_role for d in roles_dirs
        )
        if not already_present:
            roles_dirs = [*roles_dirs, requester_role_dir]

    # 6. Create agent workspace
    agent_id = f"agent_{uuid.uuid4().hex[:12]}"
    workspace = create_agent_workspace(session_dir, agent_id)

    # 7. Spawn
    env = {
        "DENDEN_ADDR": config.denden_addr,
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
        memory_prompt="",
        skills_dirs=skills_dirs,
        roles_dirs=roles_dirs,
        task=request.task_text,
        env=env,
    )

    # 8. Wait
    result: AgentResult = runtime.wait(
        handle, timeout=config.agent_timeout
    )

    # 8b. Handle timeout — kill agent if still alive
    if config.agent_timeout is not None and runtime.is_alive(handle):
        runtime.kill(handle)
        return DelegateResult(
            summary=f"Agent timed out after {config.agent_timeout}s",
            output=result.output,
            exit_code=1,
        )

    # 9. Return
    return DelegateResult(
        summary=result.summary,
        output=result.output,
        exit_code=result.exit_code,
    )
