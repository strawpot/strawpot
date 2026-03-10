"""Scheduled tasks CRUD endpoints."""

import sqlite3
from datetime import datetime, timezone

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from strawpot_gui.db import get_db_conn

router = APIRouter(prefix="/api", tags=["schedules"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ScheduleCreate(BaseModel):
    name: str
    project_id: int
    task: str
    cron_expr: str
    role: str | None = None
    system_prompt: str | None = None

    @field_validator("name")
    @classmethod
    def name_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must be non-empty")
        return v.strip()

    @field_validator("task")
    @classmethod
    def task_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task must be non-empty")
        return v.strip()

    @field_validator("cron_expr")
    @classmethod
    def cron_valid(cls, v: str) -> str:
        v = v.strip()
        if not croniter.is_valid(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v


class ScheduleUpdate(BaseModel):
    name: str | None = None
    task: str | None = None
    cron_expr: str | None = None
    role: str | None = None
    system_prompt: str | None = None

    @field_validator("cron_expr")
    @classmethod
    def cron_valid(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not croniter.is_valid(v):
                raise ValueError(f"Invalid cron expression: {v}")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["enabled"] = bool(d.get("enabled", 0))
    return d


def _compute_next_run(cron_expr: str) -> str | None:
    try:
        now = datetime.now(timezone.utc)
        return croniter(cron_expr, now).get_next(datetime).isoformat()
    except (ValueError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/schedules")
def list_schedules(conn=Depends(get_db_conn)):
    """List all scheduled tasks with project names."""
    rows = conn.execute(
        "SELECT s.*, p.display_name AS project_name "
        "FROM scheduled_tasks s "
        "LEFT JOIN projects p ON s.project_id = p.id "
        "ORDER BY s.created_at DESC"
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


@router.post("/schedules", status_code=201)
def create_schedule(body: ScheduleCreate, conn=Depends(get_db_conn)):
    """Create a new scheduled task."""
    # Verify project exists
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (body.project_id,)
    ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    next_run = _compute_next_run(body.cron_expr)

    try:
        cursor = conn.execute(
            """INSERT INTO scheduled_tasks
               (name, project_id, role, task, cron_expr, system_prompt, next_run_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (body.name, body.project_id, body.role, body.task,
             body.cron_expr, body.system_prompt, next_run),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A schedule with this name already exists")

    row = conn.execute(
        "SELECT s.*, p.display_name AS project_name "
        "FROM scheduled_tasks s "
        "LEFT JOIN projects p ON s.project_id = p.id "
        "WHERE s.id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return _row_to_dict(row)


@router.get("/schedules/{schedule_id}")
def get_schedule(schedule_id: int, conn=Depends(get_db_conn)):
    """Get a single scheduled task."""
    row = conn.execute(
        "SELECT s.*, p.display_name AS project_name "
        "FROM scheduled_tasks s "
        "LEFT JOIN projects p ON s.project_id = p.id "
        "WHERE s.id = ?",
        (schedule_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Schedule not found")
    return _row_to_dict(row)


@router.put("/schedules/{schedule_id}")
def update_schedule(
    schedule_id: int, body: ScheduleUpdate, conn=Depends(get_db_conn),
):
    """Update a scheduled task."""
    existing = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE id = ?", (schedule_id,)
    ).fetchone()
    if not existing:
        raise HTTPException(404, "Schedule not found")

    updates: list[str] = []
    params: list = []

    if body.name is not None:
        updates.append("name = ?")
        params.append(body.name.strip())
    if body.task is not None:
        updates.append("task = ?")
        params.append(body.task.strip())
    if body.role is not None:
        updates.append("role = ?")
        params.append(body.role.strip() or None)
    if body.system_prompt is not None:
        updates.append("system_prompt = ?")
        params.append(body.system_prompt.strip() or None)
    if body.cron_expr is not None:
        updates.append("cron_expr = ?")
        params.append(body.cron_expr)
        # Recompute next_run_at if cron changed and schedule is enabled
        if existing["enabled"]:
            next_run = _compute_next_run(body.cron_expr)
            updates.append("next_run_at = ?")
            params.append(next_run)

    if not updates:
        raise HTTPException(422, "No fields to update")

    params.append(schedule_id)
    try:
        conn.execute(
            f"UPDATE scheduled_tasks SET {', '.join(updates)} WHERE id = ?",
            params,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A schedule with this name already exists")

    row = conn.execute(
        "SELECT s.*, p.display_name AS project_name "
        "FROM scheduled_tasks s "
        "LEFT JOIN projects p ON s.project_id = p.id "
        "WHERE s.id = ?",
        (schedule_id,),
    ).fetchone()
    return _row_to_dict(row)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, conn=Depends(get_db_conn)):
    """Delete a scheduled task."""
    row = conn.execute(
        "SELECT id FROM scheduled_tasks WHERE id = ?", (schedule_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Schedule not found")
    conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (schedule_id,))
    return {"ok": True}


@router.post("/schedules/{schedule_id}/enable")
def enable_schedule(schedule_id: int, conn=Depends(get_db_conn)):
    """Enable a scheduled task."""
    row = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE id = ?", (schedule_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Schedule not found")

    next_run = _compute_next_run(row["cron_expr"])
    conn.execute(
        "UPDATE scheduled_tasks SET enabled = 1, next_run_at = ? WHERE id = ?",
        (next_run, schedule_id),
    )

    updated = conn.execute(
        "SELECT s.*, p.display_name AS project_name "
        "FROM scheduled_tasks s "
        "LEFT JOIN projects p ON s.project_id = p.id "
        "WHERE s.id = ?",
        (schedule_id,),
    ).fetchone()
    return _row_to_dict(updated)


@router.post("/schedules/{schedule_id}/disable")
def disable_schedule(schedule_id: int, conn=Depends(get_db_conn)):
    """Disable a scheduled task."""
    row = conn.execute(
        "SELECT id FROM scheduled_tasks WHERE id = ?", (schedule_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Schedule not found")

    conn.execute(
        "UPDATE scheduled_tasks SET enabled = 0, next_run_at = NULL WHERE id = ?",
        (schedule_id,),
    )

    updated = conn.execute(
        "SELECT s.*, p.display_name AS project_name "
        "FROM scheduled_tasks s "
        "LEFT JOIN projects p ON s.project_id = p.id "
        "WHERE s.id = ?",
        (schedule_id,),
    ).fetchone()
    return _row_to_dict(updated)


@router.get("/schedules/{schedule_id}/history")
def schedule_history(schedule_id: int, conn=Depends(get_db_conn)):
    """List sessions spawned by this schedule."""
    row = conn.execute(
        "SELECT id FROM scheduled_tasks WHERE id = ?", (schedule_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Schedule not found")

    rows = conn.execute(
        "SELECT run_id, project_id, role, runtime, isolation, status,"
        "       started_at, ended_at, duration_ms, exit_code, task, summary"
        "  FROM sessions WHERE schedule_id = ? ORDER BY started_at DESC"
        "  LIMIT 50",
        (schedule_id,),
    ).fetchall()
    return [dict(r) for r in rows]
