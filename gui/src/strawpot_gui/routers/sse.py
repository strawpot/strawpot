"""SSE streaming endpoints for real-time session monitoring."""

import asyncio
import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from strawpot_gui.db import get_db
from strawpot_gui.sse import TreeState, format_sse, sse_retry

router = APIRouter(prefix="/api", tags=["sse"])

_POLL_INTERVAL = 1.5  # seconds


def _resolve_session_dir(db_path: str, run_id: str) -> tuple[str | None, str | None]:
    """Look up session_dir and status from the database."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT session_dir, status FROM sessions WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if not row:
        return None, None
    return row["session_dir"], row["status"]


def _read_session_json(session_dir: str) -> dict | None:
    """Read and parse session.json, returning None on failure."""
    path = os.path.join(session_dir, "session.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _read_trace_lines(trace_path: str, offset: int) -> tuple[list[dict], int]:
    """Read new lines from trace.jsonl starting at byte offset."""
    events: list[dict] = []
    try:
        with open(trace_path, "r", encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            new_offset = f.tell()
    except OSError:
        return [], offset
    return events, new_offset


def _safe_mtime(path: str) -> float:
    """Return file mtime or 0.0 if the file doesn't exist."""
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def _build_full_state(session_dir: str) -> tuple[TreeState, int]:
    """Build complete TreeState from disk."""
    state = TreeState()

    session_data = _read_session_json(session_dir)
    if session_data:
        state.load_session_json(session_data)

    trace_path = os.path.join(session_dir, "trace.jsonl")
    events, offset = _read_trace_lines(trace_path, 0)
    for event in events:
        state.process_event(event)

    return state, offset


@router.get("/sessions/{run_id}/tree")
async def session_tree_sse(run_id: str, request: Request):
    """SSE endpoint for real-time agent tree updates."""
    db_path = request.app.state.db_path
    session_dir, status = _resolve_session_dir(db_path, run_id)

    if session_dir is None:
        async def not_found():
            yield format_sse(1, {"error": "Session not found"})

        return StreamingResponse(
            not_found(),
            media_type="text/event-stream",
            status_code=404,
        )

    last_event_id = request.headers.get("last-event-id")
    start_id = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def event_stream():
        event_id = start_id

        yield sse_retry(3000)

        state, trace_offset = _build_full_state(session_dir)

        event_id += 1
        yield format_sse(event_id, state.to_dict())

        # Terminal sessions: send final state and close
        if status in ("completed", "failed", "stopped"):
            return

        # Active sessions: poll for changes
        session_json_path = os.path.join(session_dir, "session.json")
        trace_path = os.path.join(session_dir, "trace.jsonl")
        prev_sj_mtime = _safe_mtime(session_json_path)
        prev_trace_mtime = _safe_mtime(trace_path)

        while True:
            await asyncio.sleep(_POLL_INTERVAL)

            if await request.is_disconnected():
                return

            changed = False

            sj_mtime = _safe_mtime(session_json_path)
            if sj_mtime != prev_sj_mtime:
                prev_sj_mtime = sj_mtime
                session_data = _read_session_json(session_dir)
                if session_data:
                    state.load_session_json(session_data)
                    changed = True

            trace_mtime = _safe_mtime(trace_path)
            if trace_mtime != prev_trace_mtime:
                prev_trace_mtime = trace_mtime
                new_events, trace_offset = _read_trace_lines(
                    trace_path, trace_offset
                )
                for ev in new_events:
                    state.process_event(ev)
                if new_events:
                    changed = True

            if changed:
                event_id += 1
                yield format_sse(event_id, state.to_dict())

            if state.is_terminal:
                return

            # Check DB status for user-initiated stops
            _, current_status = _resolve_session_dir(db_path, run_id)
            if current_status in ("completed", "failed", "stopped"):
                new_events, trace_offset = _read_trace_lines(
                    trace_path, trace_offset
                )
                for ev in new_events:
                    state.process_event(ev)
                if new_events:
                    event_id += 1
                    yield format_sse(event_id, state.to_dict())
                return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
