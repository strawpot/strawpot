"""Project CRUD endpoints with stale directory detection."""

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from strawpot_gui.db import get_db_conn, sync_project_sessions

router = APIRouter(prefix="/api", tags=["projects"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    display_name: str
    working_dir: str


class ProjectUpdate(BaseModel):
    display_name: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a dict with dir_exists flag."""
    d = dict(row)
    d["dir_exists"] = Path(d["working_dir"]).is_dir()
    return d


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/projects")
def list_projects(conn=Depends(get_db_conn)):
    rows = conn.execute(
        "SELECT id, display_name, working_dir, created_at FROM projects WHERE id != 0 ORDER BY id"
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, conn=Depends(get_db_conn)):
    resolved = str(Path(body.working_dir).resolve())
    try:
        cursor = conn.execute(
            "INSERT INTO projects (display_name, working_dir) VALUES (?, ?)",
            (body.display_name, resolved),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A project with this working directory already exists")
    conn.commit()
    sync_project_sessions(conn, cursor.lastrowid, resolved)
    row = conn.execute(
        "SELECT id, display_name, working_dir, created_at FROM projects WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return _row_to_dict(row)


@router.get("/projects/{project_id}")
def get_project(project_id: int, conn=Depends(get_db_conn)):
    row = conn.execute(
        "SELECT id, display_name, working_dir, created_at FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return _row_to_dict(row)


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdate, conn=Depends(get_db_conn)):
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    conn.execute(
        "UPDATE projects SET display_name = ? WHERE id = ?",
        (body.display_name, project_id),
    )
    conn.commit()
    updated = conn.execute(
        "SELECT id, display_name, working_dir, created_at FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    return _row_to_dict(updated)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, conn=Depends(get_db_conn)):
    if project_id == 0:
        raise HTTPException(403, "Bot Imu project cannot be deleted")
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    return {"ok": True}
