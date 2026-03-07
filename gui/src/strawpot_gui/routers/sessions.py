"""Session endpoints."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from strawpot_gui.db import get_db_conn

router = APIRouter(prefix="/api", tags=["sessions"])


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
