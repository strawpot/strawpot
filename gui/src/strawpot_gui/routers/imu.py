"""Bot Imu conversation endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

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
        """SELECT c.id, c.title, c.created_at, c.updated_at, c.source, c.source_meta,
                  COUNT(s.run_id) AS session_count,
                  COUNT(CASE WHEN s.status IN ('running', 'starting') THEN 1 END) AS active_session_count,
                  (SELECT COUNT(*) FROM conversations c2
                   WHERE c2.parent_conversation_id = c.id) AS spawned_count
           FROM conversations c
           LEFT JOIN sessions s ON s.conversation_id = c.id
           WHERE c.project_id = ?
           GROUP BY c.id
           ORDER BY COALESCE(c.updated_at, c.created_at) DESC
           LIMIT ?""",
        (_IMU_PROJECT_ID, limit),
    ).fetchall()
    return [dict(r) for r in rows]


class ImuConversationCreate(BaseModel):
    source: str | None = None
    source_meta: str | None = None


@router.post("/conversations", status_code=201)
def create_imu_conversation(body: ImuConversationCreate | None = None, conn=Depends(get_db_conn)):
    """Create a new Bot Imu conversation."""
    now = datetime.now(timezone.utc).isoformat()
    source = body.source if body else None
    source_meta = body.source_meta if body else None
    cur = conn.execute(
        "INSERT INTO conversations (project_id, source, source_meta, created_at) VALUES (?, ?, ?, ?)",
        (_IMU_PROJECT_ID, source, source_meta, now),
    )
    conv_id = cur.lastrowid
    row = conn.execute(
        "SELECT id, title, created_at, updated_at, source, source_meta FROM conversations WHERE id = ?",
        (conv_id,),
    ).fetchone()
    return dict(row)
