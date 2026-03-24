"""Configuration read/write endpoints — global and per-project."""

from dataclasses import asdict
from pathlib import Path

import tomli_w
from fastapi import APIRouter, Body, Depends, HTTPException

from strawpot.config import StrawPotConfig, _read_toml, get_strawpot_home, load_config


def _config_to_nested(config: StrawPotConfig) -> dict:
    """Convert a StrawPotConfig to nested TOML-shaped dict.

    This is the reverse of ``_apply()`` — maps flat dataclass fields back
    to the nested structure that TOML files and ConfigForm expect.
    Includes all fields so it can serve as placeholders.
    """
    result: dict = {
        "runtime": config.runtime,
        "isolation": config.isolation,
        "memory": config.memory,
        "orchestrator": {
            "role": config.orchestrator_role,
            "permission_mode": config.permission_mode,
        },
        "policy": {
            "max_depth": config.max_depth,
            "agent_timeout": config.agent_timeout,
            "max_delegate_retries": config.max_delegate_retries,
            "cache_delegations": config.cache_delegations,
            "cache_max_entries": config.cache_max_entries,
            "cache_ttl_seconds": config.cache_ttl_seconds,
            "max_num_delegations": config.max_num_delegations,
        },
        "session": {
            "pull_before_session": config.pull_before_session,
        },
        "trace": {"enabled": config.trace},
    }
    return result

# Sections managed by the resource detail sheet, not the config form.
# These must be preserved when the config form saves.
_RESOURCE_SECTIONS = {"skills", "roles", "agents", "memories", "memory_config"}


def _merge_config_form(existing: dict, form_data: dict) -> dict:
    """Merge config form data into an existing toml dict.

    Overwrites form-managed keys (runtime, policy, session, etc.) while
    preserving resource sections (skills, roles, agents, memories,
    memory_config) that are managed separately by the resource detail sheet.
    """
    merged = dict(form_data)
    for key in _RESOURCE_SECTIONS:
        if key in existing:
            merged.setdefault(key, existing[key])
    return merged


from strawpot_gui.db import get_db_conn

router = APIRouter(prefix="/api", tags=["config"])


# ---------------------------------------------------------------------------
# Installed roles
# ---------------------------------------------------------------------------


@router.get("/roles")
def list_roles():
    """List installed role slugs from ~/.strawpot/roles/."""
    roles_dir = get_strawpot_home() / "roles"
    if not roles_dir.is_dir():
        return []
    slugs: list[str] = []
    for entry in sorted(roles_dir.iterdir()):
        if not entry.is_dir():
            continue
        # Skip hidden dirs
        if entry.name.startswith("."):
            continue
        slugs.append(entry.name)
    return slugs


# ---------------------------------------------------------------------------
# Global config
# ---------------------------------------------------------------------------


@router.get("/config/global")
def get_global_config():
    """Read raw global strawpot.toml with code defaults as placeholders."""
    path = get_strawpot_home() / "strawpot.toml"
    return {
        "values": _read_toml(path),
        "defaults": _config_to_nested(StrawPotConfig()),
    }


@router.put("/config/global")
def put_global_config(data: dict = Body(...)):
    """Merge config form fields into the global strawpot.toml.

    Preserves sections not managed by the config form (skills, roles,
    agents, memories, memory_config) so saving settings doesn't wipe
    env values or version constraints.
    """
    path = get_strawpot_home() / "strawpot.toml"
    existing = _read_toml(path)
    merged = _merge_config_form(existing, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(merged, f)
    return merged


# ---------------------------------------------------------------------------
# Project config
# ---------------------------------------------------------------------------


def _get_working_dir(project_id: int, conn) -> str:
    """Look up project working_dir or raise 404."""
    row = conn.execute(
        "SELECT working_dir FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return row["working_dir"]


@router.get("/projects/{project_id}/config")
def get_project_config(project_id: int, conn=Depends(get_db_conn)):
    """Read merged config with source breakdown (merged, project, global)."""
    working_dir = _get_working_dir(project_id, conn)
    merged = load_config(Path(working_dir))
    raw_project = _read_toml(Path(working_dir) / "strawpot.toml")
    raw_global = _read_toml(get_strawpot_home() / "strawpot.toml")
    # merged: flat asdict for LaunchDialog defaults
    # merged_nested: TOML-shaped for ConfigForm placeholders (global+defaults, without project)
    global_merged = load_config(None)
    return {
        "merged": asdict(merged),
        "merged_nested": _config_to_nested(global_merged),
        "project": raw_project,
        "global": raw_global,
    }


@router.put("/projects/{project_id}/config")
def put_project_config(
    project_id: int, data: dict = Body(...), conn=Depends(get_db_conn)
):
    """Merge config form fields into the project strawpot.toml.

    Preserves sections not managed by the config form (skills, roles,
    agents, memories, memory_config).
    """
    working_dir = _get_working_dir(project_id, conn)
    path = Path(working_dir) / "strawpot.toml"
    existing = _read_toml(path)
    merged = _merge_config_form(existing, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(merged, f)
    return merged
