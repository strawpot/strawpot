"""Bot Imu conversation endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from strawpot_gui.db import get_db_conn

router = APIRouter(prefix="/api/imu", tags=["imu"])

_IMU_PROJECT_ID = 0


@router.get("/conversations")
def list_imu_conversations(
    limit: int = Query(50, ge=1, le=100),
    conn=Depends(get_db_conn),
):
    """List Bot Imu conversations, newest first."""
    rows = conn.execute(
        """SELECT c.id, c.title, c.created_at, c.updated_at,
                  COUNT(s.run_id) AS session_count
           FROM conversations c
           LEFT JOIN sessions s ON s.conversation_id = c.id
           WHERE c.project_id = ?
           GROUP BY c.id
           ORDER BY c.created_at DESC
           LIMIT ?""",
        (_IMU_PROJECT_ID, limit),
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/conversations", status_code=201)
def create_imu_conversation(conn=Depends(get_db_conn)):
    """Create a new Bot Imu conversation."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO conversations (project_id, created_at) VALUES (?, ?)",
        (_IMU_PROJECT_ID, now),
    )
    conv_id = cur.lastrowid
    row = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
        (conv_id,),
    ).fetchone()
    return dict(row)
