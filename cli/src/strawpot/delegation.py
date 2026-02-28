"""Delegate handler — policy check, resolve, build prompt, spawn, wait."""

import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from strawpot.agents.protocol import AgentHandle, AgentResult, AgentRuntime
from strawpot.config import StrawPotConfig
from strawpot.context import build_prompt, read_role_description


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


def create_workspace(
    runtime_dir: str,
    agent_id: str,
    resolved: dict,
) -> tuple[str, list[str], list[str]]:
    """Create agent workspace and stage resolved skills/roles.

    Returns:
        (workspace_dir, skills_dirs, roles_dirs)
    """
    workspace = os.path.join(runtime_dir, "agents", agent_id)
    os.makedirs(workspace, exist_ok=True)

    skills_dir = os.path.join(workspace, "skills")
    roles_dir = os.path.join(workspace, "roles")
    os.makedirs(skills_dir, exist_ok=True)
    os.makedirs(roles_dir, exist_ok=True)

    skills_dirs: list[str] = []
    roles_dirs: list[str] = []

    for dep in resolved.get("dependencies", []):
        slug = dep["slug"]
        if dep["kind"] == "skill":
            dest = os.path.join(skills_dir, slug)
            _link_or_copy(dep["path"], dest)
            skills_dirs.append(dest)
        elif dep["kind"] == "role":
            dest = os.path.join(roles_dir, slug)
            _link_or_copy(dep["path"], dest)
            roles_dirs.append(dest)

    return workspace, skills_dirs, roles_dirs


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


def handle_delegate(
    *,
    request: DelegateRequest,
    config: StrawPotConfig,
    runtime: AgentRuntime,
    working_dir: str,
    runtime_dir: str,
    resolve_role: Callable[..., dict],
    resolve_role_dirs: Callable[[str], str | None],
) -> DelegateResult:
    """Handle a delegation request end-to-end.

    Steps (DESIGN.md §Delegate Request):
      1. Policy check (allowed_roles, max_depth)
      2. Resolve role + skills via resolver
      3. Build delegatable roles list for sub-agent
      4. Build system prompt
      5. Create agent workspace, stage skills
      6. Spawn sub-agent
      7. Wait for completion
      8. Return result

    Args:
        request: The delegation request.
        config: Merged StrawPot configuration.
        runtime: Agent runtime (WrapperRuntime) for spawning.
        working_dir: Session worktree path (shared by all agents).
        runtime_dir: Base directory for agent workspaces and runtime files.
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

    # 5. Create workspace and stage skills
    agent_id = f"agent_{uuid.uuid4().hex[:12]}"
    workspace, skills_dirs, roles_dirs = create_workspace(
        runtime_dir, agent_id, resolved
    )

    # 5b. Also resolve requester's role path into roles_dirs
    requester_role_dir = resolve_role_dirs(request.parent_role)
    if requester_role_dir is not None:
        dest = os.path.join(workspace, "roles", request.parent_role)
        if not os.path.exists(dest):
            _link_or_copy(requester_role_dir, dest)
            roles_dirs.append(dest)

    # 6. Spawn
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

    # 7. Wait
    result: AgentResult = runtime.wait(
        handle, timeout=config.agent_timeout
    )

    # 7b. Handle timeout — kill agent if still alive
    if config.agent_timeout is not None and runtime.is_alive(handle):
        runtime.kill(handle)
        return DelegateResult(
            summary=f"Agent timed out after {config.agent_timeout}s",
            output=result.output,
            exit_code=1,
        )

    # 8. Return
    return DelegateResult(
        summary=result.summary,
        output=result.output,
        exit_code=result.exit_code,
    )
