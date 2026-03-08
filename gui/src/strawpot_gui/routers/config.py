"""Configuration read/write endpoints — global and per-project."""

from dataclasses import asdict
from pathlib import Path

import tomli_w
from fastapi import APIRouter, Body, Depends, HTTPException

from strawpot.config import StrawPotConfig, _read_toml, get_strawpot_home, load_config

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
    """Read the raw global strawpot.toml."""
    path = get_strawpot_home() / "strawpot.toml"
    return _read_toml(path)


@router.put("/config/global")
def put_global_config(data: dict = Body(...)):
    """Write the global strawpot.toml (full replacement)."""
    path = get_strawpot_home() / "strawpot.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)
    return data


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
    return {
        "merged": asdict(merged),
        "project": raw_project,
        "global": raw_global,
    }


@router.put("/projects/{project_id}/config")
def put_project_config(
    project_id: int, data: dict = Body(...), conn=Depends(get_db_conn)
):
    """Write the project strawpot.toml (full replacement)."""
    working_dir = _get_working_dir(project_id, conn)
    path = Path(working_dir) / "strawpot.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)
    return data
