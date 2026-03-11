"""Conversation endpoints — chat-mode sessions with sequential task submission."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from strawpot_gui.db import get_db_conn
from strawpot_gui.routers.sessions import _refresh_session_status, launch_session_subprocess

router = APIRouter(prefix="/api", tags=["conversations"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ConversationCreate(BaseModel):
    project_id: int
    title: str | None = None


class ConversationTask(BaseModel):
    task: str
    role: str | None = None
    context_files: list[str] | None = None
    interactive: bool = False
    system_prompt: str | None = None
    runtime: str | None = None
    memory: str | None = None
    max_num_delegations: int | None = None
    cache_delegations: bool | None = None
    cache_max_entries: int | None = None
    cache_ttl_seconds: int | None = None


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


def _build_conversation_context(conn, conversation_id: int) -> str:
    """Build a prior-turns summary to prepend to the next session's task."""
    rows = conn.execute(
        "SELECT task, summary, exit_code, status FROM sessions "
        "WHERE conversation_id = ? ORDER BY started_at",
        (conversation_id,),
    ).fetchall()
    if not rows:
        return ""

    def _condense(text: str | None, max_chars: int = 200) -> str:
        """Trim text to ~1-2 lines, breaking at a sentence boundary if possible."""
        if not text:
            return "(none)"
        text = text.strip()
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        last_period = truncated.rfind(". ")
        if last_period > 50:
            return truncated[: last_period + 1]
        return truncated.rstrip() + "…"

    parts = [
        "## Prior Conversation",
        "",
        "**Before Responding:** This is a continuation of a multi-turn conversation. "
        "Read the history below before answering. "
        'If the user\'s message is a short follow-up (e.g. "yes", "go ahead", "do it"), '
        "refer to **Pending Follow-up** to understand what was previously offered.",
        "",
        "**History:**",
    ]

    for i, row in enumerate(rows, 1):
        task_line = _condense(row["task"], 150)
        if row["summary"]:
            result_line = _condense(row["summary"])
        elif row["status"] in ("completed", "failed"):
            result_line = f"(exit code {row['exit_code']})"
        else:
            result_line = f"(status: {row['status']})"
        parts.append(f"- Turn {i}: asked: {task_line} → did: {result_line}")

    # Pending Follow-up: last session's full summary for short follow-up turns
    last = rows[-1]
    parts.append("")
    parts.append("**Pending Follow-up:**")
    if last["summary"]:
        parts.append(last["summary"].strip())
    else:
        parts.append("(none)")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/conversations/recent")
def list_recent_conversations(
    limit: int = Query(10, ge=1, le=50),
    conn=Depends(get_db_conn),
):
    """List recent conversations across all projects, ordered by last activity."""
    rows = conn.execute(
        """SELECT c.id, c.project_id, c.title, c.created_at, c.updated_at,
                  p.display_name AS project_name,
                  COUNT(s.run_id) AS session_count,
                  MAX(s.started_at) AS last_activity
           FROM conversations c
           JOIN projects p ON p.id = c.project_id
           LEFT JOIN sessions s ON s.conversation_id = c.id
           GROUP BY c.id
           ORDER BY COALESCE(MAX(s.started_at), c.created_at) DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/conversations", status_code=201)
def create_conversation(body: ConversationCreate, conn=Depends(get_db_conn)):
    """Create a new conversation for a project."""
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (body.project_id,)
    ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO conversations (project_id, title, created_at) VALUES (?, ?, ?)",
        (body.project_id, body.title, now),
    )
    conv_id = cur.lastrowid
    row = conn.execute(
        "SELECT id, project_id, title, created_at, updated_at FROM conversations WHERE id = ?",
        (conv_id,),
    ).fetchone()
    return dict(row)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    before_id: str | None = Query(default=None),
    conn=Depends(get_db_conn),
):
    """Get a conversation with its paginated sessions (newest page first)."""
    row = conn.execute(
        "SELECT id, project_id, title, created_at, updated_at FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found")

    # Refresh status/summary for any active sessions before returning
    active = conn.execute(
        "SELECT run_id FROM sessions WHERE conversation_id = ? AND status IN ('starting', 'running')",
        (conversation_id,),
    ).fetchall()
    for s in active:
        _refresh_session_status(conn, s["run_id"])

    # Cursor pagination: fetch limit+1 rows descending, detect has_more, reverse to ascending
    if before_id:
        cursor_row = conn.execute(
            "SELECT started_at FROM sessions WHERE run_id = ?", (before_id,)
        ).fetchone()
        if not cursor_row:
            raise HTTPException(400, "Invalid before_id")
        rows = conn.execute(
            "SELECT run_id, task, user_task, summary, status, exit_code, started_at, ended_at, duration_ms, role "
            "FROM sessions WHERE conversation_id = ? AND started_at < ? "
            "ORDER BY started_at DESC LIMIT ?",
            (conversation_id, cursor_row["started_at"], limit + 1),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT run_id, task, user_task, summary, status, exit_code, started_at, ended_at, duration_ms, role "
            "FROM sessions WHERE conversation_id = ? "
            "ORDER BY started_at DESC LIMIT ?",
            (conversation_id, limit + 1),
        ).fetchall()

    has_more = len(rows) > limit
    sessions = list(reversed(rows[:limit]))  # ascending for display

    result = dict(row)
    result["sessions"] = [dict(s) for s in sessions]
    result["has_more"] = has_more
    return result


@router.get("/projects/{project_id}/conversations")
def list_project_conversations(
    project_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    conn=Depends(get_db_conn),
):
    """List conversations for a project, most recent first."""
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    total = conn.execute(
        "SELECT COUNT(*) FROM conversations WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]

    offset = (page - 1) * per_page
    rows = conn.execute(
        """SELECT c.id, c.project_id, c.title, c.created_at, c.updated_at,
                  COUNT(s.run_id) AS session_count,
                  MAX(s.started_at) AS last_activity
           FROM conversations c
           LEFT JOIN sessions s ON s.conversation_id = c.id
           WHERE c.project_id = ?
           GROUP BY c.id
           ORDER BY c.created_at DESC
           LIMIT ? OFFSET ?""",
        (project_id, per_page, offset),
    ).fetchall()

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/conversations/{conversation_id}/tasks", status_code=201)
def submit_task(
    conversation_id: int,
    body: ConversationTask,
    conn=Depends(get_db_conn),
):
    """Submit a new task in a conversation.

    Builds context from prior sessions and launches a new session with
    the conversation history prepended to the task.
    """
    conv = conn.execute(
        "SELECT id, project_id, title FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    project_id = conv["project_id"]

    # Build prior conversation context and prepend to task for the agent
    context = _build_conversation_context(conn, conversation_id)
    full_task = f"{context}\n\n---\n\n{body.task}" if context else body.task

    try:
        run_id = launch_session_subprocess(
            conn,
            project_id,
            full_task,
            user_task=body.task,
            memory_task=body.task if context else None,
            role=body.role,
            system_prompt=body.system_prompt or None,
            context_files=body.context_files,
            interactive=body.interactive,
            conversation_id=conversation_id,
            runtime_override=body.runtime,
            memory_override=body.memory,
            max_num_delegations=body.max_num_delegations,
            cache_delegations=body.cache_delegations,
            cache_max_entries=body.cache_max_entries,
            cache_ttl_seconds=body.cache_ttl_seconds,
        )
    except RuntimeError as e:
        _ERROR_STATUS = {
            "Project not found": 404,
            "Project working directory does not exist": 422,
        }
        status = _ERROR_STATUS.get(str(e), 500)
        raise HTTPException(status, str(e))

    # Auto-set title from first message if conversation has no title yet
    now = datetime.now(timezone.utc).isoformat()
    if not context and not conv["title"]:
        auto_title = body.task.strip().splitlines()[0][:80].rstrip()
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (auto_title, now, conversation_id),
        )
    else:
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )

    return {"run_id": run_id, "conversation_id": conversation_id}


class ConversationUpdate(BaseModel):
    title: str | None = None


@router.patch("/conversations/{conversation_id}")
def update_conversation(
    conversation_id: int, body: ConversationUpdate, conn=Depends(get_db_conn)
):
    """Update conversation metadata (e.g. title)."""
    row = conn.execute(
        "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found")

    conn.execute(
        "UPDATE conversations SET title = ? WHERE id = ?",
        (body.title, conversation_id),
    )
    updated = conn.execute(
        "SELECT id, project_id, title, created_at, updated_at FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    return dict(updated)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, conn=Depends(get_db_conn)):
    """Delete a conversation. Sessions are kept but lose their conversation link."""
    row = conn.execute(
        "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found")

    conn.execute(
        "UPDATE sessions SET conversation_id = NULL WHERE conversation_id = ?",
        (conversation_id,),
    )
    conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
