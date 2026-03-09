"""SSE and REST endpoints for agent log streaming."""

import asyncio
import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

from strawpot_gui.sse import (
    format_sse,
    format_sse_typed,
    resolve_session_dir,
    sse_retry,
    watch_dir,
)

router = APIRouter(prefix="/api", tags=["logs"])

_TERMINAL_STATUSES = ("completed", "failed", "stopped")
_MAX_SNAPSHOT_LINES = 500


def _read_log_tail(path: str, max_lines: int = _MAX_SNAPSHOT_LINES) -> tuple[list[str], int]:
    """Read the last *max_lines* lines from a log file.

    Returns (lines, byte_offset) where offset is the end-of-file position.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            offset = f.tell()
        # Strip trailing newlines from each line
        lines = [ln.rstrip("\n") for ln in all_lines[-max_lines:]]
        return lines, offset
    except OSError:
        return [], 0


def _read_log_delta(path: str, offset: int) -> tuple[list[str], int]:
    """Read new content from a log file starting at *offset*.

    Returns (new_lines, new_offset).
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            raw = f.read()
            new_offset = f.tell()
        if not raw:
            return [], offset
        lines = [ln.rstrip("\n") for ln in raw.splitlines()]
        return lines, new_offset
    except OSError:
        return [], offset


def _validate_agent(session_dir: str, agent_id: str) -> bool:
    """Check that agent_id exists in session.json agents dict."""
    path = os.path.join(session_dir, "session.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return agent_id in data.get("agents", {})
    except (OSError, json.JSONDecodeError):
        # If session.json doesn't exist yet, check agent dir on disk
        return os.path.isdir(os.path.join(session_dir, "agents", agent_id))


# ---------------------------------------------------------------------------
# SSE: Agent log streaming
# ---------------------------------------------------------------------------


@router.get("/sessions/{run_id}/logs/{agent_id}")
async def agent_log_sse(run_id: str, agent_id: str, request: Request):
    """SSE endpoint for streaming an agent's log output.

    Protocol:
    - ``event: snapshot`` — initial batch (last 500 lines + byte offset)
    - ``event: append``   — new lines since last send
    - ``event: done``     — session reached terminal state, stream closes
    """
    db_path = request.app.state.db_path
    session_dir, status = resolve_session_dir(db_path, run_id)

    if session_dir is None:
        async def not_found():
            yield format_sse(1, {"error": "Session not found"})

        return StreamingResponse(
            not_found(),
            media_type="text/event-stream",
            status_code=404,
        )

    if not _validate_agent(session_dir, agent_id):
        async def agent_not_found():
            yield format_sse(1, {"error": f"Agent {agent_id} not found"})

        return StreamingResponse(
            agent_not_found(),
            media_type="text/event-stream",
            status_code=404,
        )

    log_path = os.path.join(session_dir, "agents", agent_id, ".log")

    async def event_stream():
        event_id = 0

        yield sse_retry(3000)

        # Snapshot: send last N lines
        lines, offset = _read_log_tail(log_path)
        event_id += 1
        yield format_sse_typed(event_id, "snapshot", {
            "lines": lines,
            "offset": offset,
        })

        # Terminal sessions: send done immediately
        if status in _TERMINAL_STATUSES:
            event_id += 1
            yield format_sse_typed(event_id, "done", {})
            return

        # Watch agent directory for log changes
        agent_dir = os.path.join(session_dir, "agents", agent_id)
        stop = asyncio.Event()

        try:
            async for changed_files in watch_dir(agent_dir, stop):
                if await request.is_disconnected():
                    return

                if not changed_files:
                    # Timeout — check DB status
                    _, current_status = resolve_session_dir(db_path, run_id)
                    if current_status in _TERMINAL_STATUSES:
                        # Final read
                        new_lines, offset = _read_log_delta(log_path, offset)
                        if new_lines:
                            event_id += 1
                            yield format_sse_typed(event_id, "append", {
                                "lines": new_lines,
                                "offset": offset,
                            })
                        event_id += 1
                        yield format_sse_typed(event_id, "done", {})
                        return
                    continue

                if any(f.endswith(".log") for f in changed_files):
                    new_lines, offset = _read_log_delta(log_path, offset)
                    if new_lines:
                        event_id += 1
                        yield format_sse_typed(event_id, "append", {
                            "lines": new_lines,
                            "offset": offset,
                        })
        finally:
            stop.set()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# REST: Full log download
# ---------------------------------------------------------------------------


@router.get("/sessions/{run_id}/logs/{agent_id}/full")
async def agent_log_full(run_id: str, agent_id: str, request: Request):
    """Return the complete log file as plain text."""
    db_path = request.app.state.db_path
    session_dir, _ = resolve_session_dir(db_path, run_id)

    if session_dir is None:
        return PlainTextResponse("Session not found", status_code=404)

    if not _validate_agent(session_dir, agent_id):
        return PlainTextResponse(f"Agent {agent_id} not found", status_code=404)

    log_path = os.path.join(session_dir, "agents", agent_id, ".log")
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return PlainTextResponse(content)
    except OSError:
        return PlainTextResponse("", status_code=200)
