"""Scheduled tasks CRUD endpoints."""

import sqlite3
from datetime import datetime, timezone

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query
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
    skip_if_running: bool = True
    conversation_id: int | None = None

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


class OneTimeScheduleCreate(BaseModel):
    name: str
    project_id: int
    task: str
    run_at: str
    role: str | None = None
    system_prompt: str | None = None
    conversation_id: int | None = None

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

    @field_validator("run_at")
    @classmethod
    def run_at_valid(cls, v: str) -> str:
        v = v.strip()
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            raise ValueError(f"Invalid ISO datetime: {v}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt <= datetime.now(timezone.utc):
            raise ValueError("run_at must be in the future")
        return dt.isoformat()


class ScheduleUpdate(BaseModel):
    name: str | None = None
    task: str | None = None
    cron_expr: str | None = None
    run_at: str | None = None
    role: str | None = None
    system_prompt: str | None = None
    skip_if_running: bool | None = None
    conversation_id: int | None = None

    @field_validator("cron_expr")
    @classmethod
    def cron_valid(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not croniter.is_valid(v):
                raise ValueError(f"Invalid cron expression: {v}")
        return v

    @field_validator("run_at")
    @classmethod
    def run_at_valid(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            try:
                dt = datetime.fromisoformat(v)
            except ValueError:
                raise ValueError(f"Invalid ISO datetime: {v}")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt <= datetime.now(timezone.utc):
                raise ValueError("run_at must be in the future")
            return dt.isoformat()
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["enabled"] = bool(d.get("enabled", 0))
    d["skip_if_running"] = bool(d.get("skip_if_running", 1))
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
def list_schedules(
    type: str | None = None, conn=Depends(get_db_conn),
):
    """List scheduled tasks with project names, optionally filtered by type."""
    if type and type not in ("recurring", "one_time"):
        raise HTTPException(422, "type must be 'recurring' or 'one_time'")

    query = (
        "SELECT s.*, p.display_name AS project_name "
        "FROM scheduled_tasks s "
        "LEFT JOIN projects p ON s.project_id = p.id "
    )
    params: list = []
    if type:
        query += "WHERE s.schedule_type = ? "
        params.append(type)
    query += "ORDER BY s.created_at DESC"

    rows = conn.execute(query, params).fetchall()
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
               (name, project_id, role, task, cron_expr, system_prompt,
                skip_if_running, next_run_at, conversation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.name, body.project_id, body.role, body.task,
             body.cron_expr, body.system_prompt,
             int(body.skip_if_running), next_run, body.conversation_id),
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


@router.post("/schedules/one-time", status_code=201)
def create_one_time_schedule(
    body: OneTimeScheduleCreate, conn=Depends(get_db_conn),
):
    """Create a one-time scheduled task."""
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (body.project_id,)
    ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    try:
        cursor = conn.execute(
            """INSERT INTO scheduled_tasks
               (name, project_id, role, task, cron_expr, schedule_type,
                run_at, system_prompt, skip_if_running, next_run_at,
                conversation_id)
               VALUES (?, ?, ?, ?, NULL, 'one_time', ?, ?, 0, ?, ?)""",
            (body.name, body.project_id, body.role, body.task,
             body.run_at, body.system_prompt, body.run_at,
             body.conversation_id),
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


@router.get("/schedules/runs")
def schedule_runs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    conn=Depends(get_db_conn),
):
    """List all sessions triggered by schedules, with schedule metadata."""
    total = conn.execute(
        "SELECT count(*) FROM sessions se"
        "  JOIN scheduled_tasks st ON se.schedule_id = st.id",
    ).fetchone()[0]

    offset = (page - 1) * per_page
    rows = conn.execute(
        "SELECT se.run_id, se.project_id, se.role, se.status,"
        "       se.started_at, se.ended_at, se.duration_ms, se.exit_code,"
        "       se.task, se.schedule_id,"
        "       st.name AS schedule_name, st.schedule_type,"
        "       p.display_name AS project_name"
        "  FROM sessions se"
        "  JOIN scheduled_tasks st ON se.schedule_id = st.id"
        "  LEFT JOIN projects p ON se.project_id = p.id"
        "  ORDER BY se.started_at DESC"
        "  LIMIT ? OFFSET ?",
        (per_page, offset),
    ).fetchall()
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


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
    if body.run_at is not None:
        updates.append("run_at = ?")
        params.append(body.run_at)
        if existing["enabled"]:
            updates.append("next_run_at = ?")
            params.append(body.run_at)
    if body.skip_if_running is not None:
        updates.append("skip_if_running = ?")
        params.append(int(body.skip_if_running))
    if "conversation_id" in body.model_fields_set:
        updates.append("conversation_id = ?")
        params.append(body.conversation_id)

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

    if row["schedule_type"] == "one_time":
        run_at = row["run_at"]
        if not run_at:
            raise HTTPException(422, "One-time schedule has no run_at value")
        try:
            dt = datetime.fromisoformat(run_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(422, "Invalid run_at value")
        if dt <= datetime.now(timezone.utc):
            raise HTTPException(422, "Cannot re-enable: scheduled time has passed")
        next_run = run_at
    else:
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
        "       started_at, ended_at, duration_ms, exit_code, task"
        "  FROM sessions WHERE schedule_id = ? ORDER BY started_at DESC"
        "  LIMIT 50",
        (schedule_id,),
    ).fetchall()
    return [dict(r) for r in rows]
