"""Conversation endpoints — chat-mode sessions with sequential task submission."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from strawpot_gui.db import _extract_recap, _strip_recap, get_db_conn
from strawpot_gui.routers.sessions import _refresh_session_status, launch_session_subprocess
from strawpot_gui.routers.ws import _read_chat_messages

router = APIRouter(prefix="/api", tags=["conversations"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ConversationCreate(BaseModel):
    project_id: int
    title: str | None = None
    parent_conversation_id: int | None = None
    source: str | None = None
    source_meta: str | None = None


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
    source: str = "user"
    source_id: str | None = None


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


def _strip_prior_context(task: str) -> str:
    """Strip a '## Prior Conversation' prefix from a task string.

    Used when falling back to the ``task`` column (which may contain nested
    context from earlier turns) because ``user_task`` is NULL.
    """
    sep = "\n\n---\n\n"
    if "## Prior Conversation" in task and sep in task:
        return task.split(sep, 1)[1]
    return task


logger = logging.getLogger(__name__)

_MAX_TURNS = 10
_HISTORY_FULL_OUTPUT_TURNS = 5


def _build_conversation_context(conn, conversation_id: int, *, history_path: str | None = None) -> str:
    """Build a prior-turns summary to prepend to the next session's task."""
    rows = conn.execute(
        "SELECT task, user_task, summary, exit_code, status, "
        "files_changed, duration_ms "
        "FROM sessions "
        "WHERE conversation_id = ? AND status IN ('completed', 'failed') "
        "ORDER BY started_at",
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

    # Cap at most recent turns
    dropped = max(0, len(rows) - _MAX_TURNS)
    rows = rows[-_MAX_TURNS:]

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

    if dropped:
        parts.append(f"(… {dropped} earlier turns omitted)")

    total = len(rows)
    for i, row in enumerate(rows, 1):
        remaining = total - i  # 0 = last turn
        if remaining >= 3:
            task_limit, summary_limit = 100, 120
        elif remaining >= 1:
            task_limit, summary_limit = 200, 300
        else:
            task_limit, summary_limit = 200, 200

        # Turn header: status, duration, files
        meta = [row["status"]]
        duration_ms = row["duration_ms"]
        if duration_ms is not None:
            if duration_ms < 60_000:
                meta.append(f"{duration_ms // 1000}s")
            else:
                meta.append(f"{duration_ms // 60_000}m{(duration_ms % 60_000) // 1000}s")
        header = f"**Turn {i}** [{', '.join(meta)}]"
        # File paths for recent turns (last 3)
        if remaining < 3 and row["files_changed"]:
            try:
                files = json.loads(row["files_changed"])
                if files:
                    file_list = ", ".join(files[:10])
                    if len(files) > 10:
                        file_list += f" (+{len(files) - 10} more)"
                    header += f" | files: {file_list}"
            except (json.JSONDecodeError, TypeError):
                pass

        task_text = row["user_task"] or _strip_prior_context(row["task"])
        task_line = _condense(task_text, task_limit)
        summary = _extract_recap(row["summary"]) if row["summary"] else None
        if summary:
            result_line = _condense(summary, summary_limit)
        elif row["status"] == "failed":
            result_line = f"(failed, exit code {row['exit_code']})"
        else:
            result_line = f"(exit code {row['exit_code']})"

        parts.append(header)
        parts.append(f"- Asked: {task_line}")
        parts.append(f"- Result: {result_line}")

    # Pending Follow-up: last session's recap + raw output tail
    last = rows[-1]
    parts.append("")
    parts.append("**Pending Follow-up:**")
    if last["summary"]:
        last_recap = _extract_recap(last["summary"])
        # Only show separate recap/output sections if a recap was actually found
        if last_recap != last["summary"]:
            parts.append("")
            parts.append("**Recap:**")
            parts.append(_condense(last_recap, 1500))
            raw_output = _strip_recap(last["summary"])
            if raw_output.strip():
                parts.append("")
                parts.append("**Recent output:**")
                tail = raw_output.strip()[-1500:]
                parts.append(tail)
        else:
            # No recap section — show tail of full output
            parts.append(_condense(last["summary"], 2000))
    else:
        parts.append("(none)")

    # History file hint (if written)
    if history_path:
        parts.append("")
        parts.append(
            f"> Full session outputs available at `{history_path}` — "
            "read it if you need more detail than the summaries above."
        )

    return "\n".join(parts)


def _write_conversation_history(conn, conversation_id: int, working_dir: str) -> str | None:
    """Write full conversation history to .strawpot/conversation_history.md.

    Returns the absolute path to the file, or None if nothing was written.
    Last 5 turns get full output; turns 6-10 get recap only; older turns omitted.
    """
    rows = conn.execute(
        "SELECT task, user_task, summary, exit_code, status, "
        "files_changed, duration_ms, started_at "
        "FROM sessions "
        "WHERE conversation_id = ? AND status IN ('completed', 'failed') "
        "ORDER BY started_at",
        (conversation_id,),
    ).fetchall()
    if not rows:
        return None

    # Cap at 10 turns
    dropped = max(0, len(rows) - _MAX_TURNS)
    rows = rows[-_MAX_TURNS:]

    parts = ["# Conversation History", ""]
    if dropped:
        parts.append(f"(… {dropped} earlier turns omitted)")
        parts.append("")

    total = len(rows)
    for i, row in enumerate(rows, 1):
        remaining = total - i

        # Turn header
        meta = [row["status"]]
        duration_ms = row["duration_ms"]
        if duration_ms is not None:
            if duration_ms < 60_000:
                meta.append(f"{duration_ms // 1000}s")
            else:
                meta.append(f"{duration_ms // 60_000}m{(duration_ms % 60_000) // 1000}s")
        parts.append(f"## Turn {i} — {row['started_at']} [{', '.join(meta)}]")

        task_text = row["user_task"] or _strip_prior_context(row["task"])
        parts.append(f"**Task:** {task_text}")

        if row["files_changed"]:
            try:
                files = json.loads(row["files_changed"])
                if files:
                    parts.append(f"**Files changed:** {', '.join(files)}")
            except (json.JSONDecodeError, TypeError):
                pass

        parts.append("")
        parts.append("### Output")

        if remaining < _HISTORY_FULL_OUTPUT_TURNS:
            # Recent turns: full output
            parts.append(row["summary"] or "(no output)")
        else:
            # Older turns: recap only
            if row["summary"]:
                recap = _extract_recap(row["summary"])
                parts.append(recap)
            else:
                parts.append("(no output)")

        parts.append("")
        parts.append("---")
        parts.append("")

    history_dir = Path(working_dir) / ".strawpot"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / "conversation_history.md"
    try:
        history_path.write_text("\n".join(parts), encoding="utf-8")
        return str(history_path)
    except OSError:
        logger.warning("Failed to write conversation history to %s", history_path)
        return None


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
                  c.source, c.source_meta,
                  p.display_name AS project_name,
                  COUNT(s.run_id) AS session_count,
                  MAX(s.started_at) AS last_activity
           FROM conversations c
           JOIN projects p ON p.id = c.project_id
           LEFT JOIN sessions s ON s.conversation_id = c.id
           WHERE p.id != 0
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

    if body.parent_conversation_id is not None:
        parent = conn.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (body.parent_conversation_id,),
        ).fetchone()
        if not parent:
            raise HTTPException(422, "Parent conversation not found")

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO conversations (project_id, title, parent_conversation_id, source, source_meta, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (body.project_id, body.title, body.parent_conversation_id, body.source, body.source_meta, now),
    )
    conv_id = cur.lastrowid
    row = conn.execute(
        "SELECT id, project_id, title, parent_conversation_id, created_at, updated_at, source, source_meta "
        "FROM conversations WHERE id = ?",
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
        "SELECT id, project_id, title, parent_conversation_id, created_at, updated_at, pending_task, source, source_meta "
        "FROM conversations WHERE id = ?",
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
            "SELECT run_id, task, user_task, summary, status, exit_code, started_at, ended_at, duration_ms, role, interactive, session_dir "
            "FROM sessions WHERE conversation_id = ? AND started_at < ? "
            "ORDER BY started_at DESC LIMIT ?",
            (conversation_id, cursor_row["started_at"], limit + 1),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT run_id, task, user_task, summary, status, exit_code, started_at, ended_at, duration_ms, role, interactive, session_dir "
            "FROM sessions WHERE conversation_id = ? "
            "ORDER BY started_at DESC LIMIT ?",
            (conversation_id, limit + 1),
        ).fetchall()

    has_more = len(rows) > limit
    sessions = list(reversed(rows[:limit]))  # ascending for display

    result = dict(row)
    result["sessions"] = []
    for s in sessions:
        d = {k: s[k] for k in s.keys() if k != "session_dir"}
        d["summary"] = _strip_recap(d["summary"]) if d["summary"] else d["summary"]
        d["interactive"] = bool(d.get("interactive"))
        if d["interactive"] and s["session_dir"]:
            d["chat_messages"] = _read_chat_messages(s["session_dir"])
        result["sessions"].append(d)
    result["has_more"] = has_more

    # Queued tasks from the task queue table
    queued_rows = conn.execute(
        "SELECT id, task, source, source_id, created_at "
        "FROM conversation_task_queue WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    ).fetchall()
    result["queued_tasks"] = [dict(q) for q in queued_rows]
    # Backward compat: synthesize pending_task string from queue
    result["pending_task"] = (
        "\n\n".join(q["task"] for q in queued_rows) or None
    )

    # Parent conversation info
    if row["parent_conversation_id"]:
        parent = conn.execute(
            "SELECT c.id, c.project_id, c.title, p.display_name AS project_name "
            "FROM conversations c JOIN projects p ON p.id = c.project_id "
            "WHERE c.id = ?",
            (row["parent_conversation_id"],),
        ).fetchone()
        if parent:
            result["parent"] = dict(parent)
        else:
            result["parent"] = None
    else:
        result["parent"] = None

    # Child conversations spawned from this one
    children = conn.execute(
        "SELECT c.id, c.project_id, c.title, p.display_name AS project_name "
        "FROM conversations c JOIN projects p ON p.id = c.project_id "
        "WHERE c.parent_conversation_id = ? "
        "ORDER BY c.created_at",
        (conversation_id,),
    ).fetchall()
    result["children"] = [dict(c) for c in children]

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
        """SELECT c.id, c.project_id, c.title, c.parent_conversation_id,
                  c.created_at, c.updated_at, c.source, c.source_meta,
                  COUNT(s.run_id) AS session_count,
                  MAX(s.started_at) AS last_activity
           FROM conversations c
           LEFT JOIN sessions s ON s.conversation_id = c.id
           WHERE c.project_id = ?
           GROUP BY c.id
           ORDER BY COALESCE(c.updated_at, c.created_at) DESC
           LIMIT ? OFFSET ?""",
        (project_id, per_page, offset),
    ).fetchall()

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/conversations/{conversation_id}/tasks")
def submit_task(
    conversation_id: int,
    body: ConversationTask,
    conn=Depends(get_db_conn),
    response: "Response | None" = None,
):
    """Submit a new task in a conversation.

    If no session is active, builds context from prior sessions and launches a
    new session (201).  If a session is already running, the task is appended to
    ``pending_task`` on the conversation and will be auto-submitted when the
    current session completes (202).
    """
    from starlette.responses import JSONResponse

    conv = conn.execute(
        "SELECT id, project_id, title, pending_task FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    project_id = conv["project_id"]

    # Check for an active session in this conversation
    active = conn.execute(
        "SELECT run_id FROM sessions "
        "WHERE conversation_id = ? AND status IN ('starting', 'running')",
        (conversation_id,),
    ).fetchone()

    if active:
        # Queue the task as a separate row in conversation_task_queue
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO conversation_task_queue
               (conversation_id, task, source, source_id, role, context_files,
                interactive, system_prompt, runtime, memory,
                max_num_delegations, cache_delegations, cache_max_entries,
                cache_ttl_seconds)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                conversation_id, body.task, body.source, body.source_id,
                body.role,
                json.dumps(body.context_files) if body.context_files else None,
                1 if body.interactive else 0,
                body.system_prompt, body.runtime, body.memory,
                body.max_num_delegations,
                1 if body.cache_delegations else None,
                body.cache_max_entries, body.cache_ttl_seconds,
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        return JSONResponse(
            status_code=202,
            content={"queued": True, "conversation_id": conversation_id},
        )

    return _launch_conversation_task(conn, conv, body)


def _launch_conversation_task(conn, conv, body: ConversationTask):
    """Build context and launch a session for the conversation task."""
    from starlette.responses import JSONResponse

    conversation_id = conv["id"]
    project_id = conv["project_id"]

    # Write conversation history file for on-demand retrieval by the agent
    hist_path = None
    project_row = conn.execute(
        "SELECT working_dir FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project_row and project_row["working_dir"]:
        hist_path = _write_conversation_history(
            conn, conversation_id, project_row["working_dir"]
        )

    # Build prior conversation context and prepend to task for the agent
    context = _build_conversation_context(conn, conversation_id, history_path=hist_path)
    full_task = f"{context}\n\n---\n\n{body.task}" if context else body.task

    try:
        run_id = launch_session_subprocess(
            conn,
            project_id,
            full_task,
            user_task=body.task,
            memory_task=body.task if context else None,
            role=body.role or ("imu" if project_id == 0 else None),
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

    return JSONResponse(
        status_code=201,
        content={"run_id": run_id, "conversation_id": conversation_id},
    )


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


@router.delete("/conversations/{conversation_id}/pending_task", status_code=204)
def cancel_pending_task(conversation_id: int, conn=Depends(get_db_conn)):
    """Cancel all queued tasks for a conversation."""
    row = conn.execute(
        "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found")
    conn.execute(
        "DELETE FROM conversation_task_queue WHERE conversation_id = ?",
        (conversation_id,),
    )


@router.delete("/conversations/{conversation_id}/queued_tasks/{task_id}", status_code=204)
def cancel_queued_task(conversation_id: int, task_id: int, conn=Depends(get_db_conn)):
    """Cancel a single queued task."""
    deleted = conn.execute(
        "DELETE FROM conversation_task_queue WHERE id = ? AND conversation_id = ?",
        (task_id, conversation_id),
    ).rowcount
    if not deleted:
        raise HTTPException(404, "Queued task not found")
