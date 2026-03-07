"""Session list endpoint."""

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
