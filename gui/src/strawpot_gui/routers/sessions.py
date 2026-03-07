"""Session endpoints."""

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from strawpot.config import load_config
from strawpot_gui.db import get_db_conn

router = APIRouter(prefix="/api", tags=["sessions"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SessionOverrides(BaseModel):
    runtime: str | None = None
    isolation: str | None = None
    merge_strategy: str | None = None


class SessionLaunch(BaseModel):
    project_id: int
    task: str
    role: str | None = None
    overrides: SessionOverrides | None = None

    @field_validator("task")
    @classmethod
    def task_must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task must be non-empty")
        return v.strip()


@router.post("/sessions", status_code=201)
def launch_session(body: SessionLaunch, conn=Depends(get_db_conn)):
    """Launch a new headless session as a detached subprocess."""
    project = conn.execute(
        "SELECT id, working_dir FROM projects WHERE id = ?",
        (body.project_id,),
    ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    working_dir = project["working_dir"]
    if not Path(working_dir).is_dir():
        raise HTTPException(
            422, "Project working directory does not exist"
        )

    # Load project config for defaults
    config = load_config(Path(working_dir))
    role = body.role or config.orchestrator_role
    runtime = config.runtime
    isolation = config.isolation

    if body.overrides:
        if body.overrides.runtime:
            runtime = body.overrides.runtime
        if body.overrides.isolation:
            isolation = body.overrides.isolation

    # Pre-generate run_id
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    session_dir = str(Path(working_dir) / ".strawpot" / "sessions" / run_id)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """INSERT INTO sessions
           (run_id, project_id, role, runtime, isolation, status,
            started_at, session_dir, task)
           VALUES (?, ?, ?, ?, ?, 'starting', ?, ?, ?)""",
        (run_id, body.project_id, role, runtime, isolation, now,
         session_dir, body.task),
    )

    # Build CLI command
    strawpot_cmd = shutil.which("strawpot")
    if strawpot_cmd is None:
        raise HTTPException(500, "strawpot CLI not found on PATH")

    cmd = [
        strawpot_cmd, "start",
        "--headless",
        "--task", body.task,
        "--run-id", run_id,
    ]
    if body.role:
        cmd.extend(["--role", body.role])
    if body.overrides:
        if body.overrides.runtime:
            cmd.extend(["--runtime", body.overrides.runtime])
        if body.overrides.isolation:
            cmd.extend(["--isolation", body.overrides.isolation])
        if body.overrides.merge_strategy:
            cmd.extend(["--merge-strategy", body.overrides.merge_strategy])

    try:
        subprocess.Popen(
            cmd,
            cwd=working_dir,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        conn.execute("DELETE FROM sessions WHERE run_id = ?", (run_id,))
        raise HTTPException(500, "Failed to start session subprocess")

    return {"run_id": run_id, "status": "starting"}


@router.get("/projects/{project_id}/sessions")
def list_sessions(project_id: int, conn=Depends(get_db_conn)):
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    rows = conn.execute(
        "SELECT run_id, project_id, role, runtime, isolation, status,"
        "       started_at, ended_at, duration_ms, exit_code, task, summary"
        "  FROM sessions WHERE project_id = ? ORDER BY started_at DESC",
        (project_id,),
    ).fetchall()
    return [dict(row) for row in rows]


@router.get("/projects/{project_id}/sessions/{run_id}")
def get_session(project_id: int, run_id: str, conn=Depends(get_db_conn)):
    row = conn.execute(
        "SELECT run_id, project_id, role, runtime, isolation, status,"
        "       started_at, ended_at, duration_ms, exit_code, task, summary,"
        "       session_dir"
        "  FROM sessions WHERE project_id = ? AND run_id = ?",
        (project_id, run_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")

    result = {
        k: row[k]
        for k in row.keys()
        if k != "session_dir"
    }

    session_dir = Path(row["session_dir"])

    # Load agents from session.json
    agents = {}
    session_json = session_dir / "session.json"
    try:
        data = json.loads(session_json.read_text(encoding="utf-8"))
        agents = data.get("agents", {})
    except (OSError, json.JSONDecodeError):
        pass
    result["agents"] = agents

    # Load trace events from trace.jsonl
    events = []
    trace_path = session_dir / "trace.jsonl"
    try:
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        pass
    result["events"] = events

    return result
