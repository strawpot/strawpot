"""SSE streaming endpoints for real-time session monitoring."""

import asyncio
import json
import os
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from watchfiles import awatch

from strawpot_gui.db import get_db
from strawpot_gui.event_bus import EventBus, SessionEvent, event_bus
from strawpot_gui.sse import TreeState, format_sse, format_sse_typed, sse_retry

router = APIRouter(prefix="/api", tags=["sse"])

# Fallback timeout (ms) for watchfiles — ensures periodic DB status checks
# even when no file changes occur (e.g., user-initiated stop via API).
_WATCH_TIMEOUT_MS = 5000


async def _watch_session_dir(
    session_dir: str, stop_event: asyncio.Event
) -> AsyncIterator[set[str]]:
    """Yield sets of changed file paths whenever the session directory changes.

    Yields an empty set on timeout (no file changes detected within
    _WATCH_TIMEOUT_MS), allowing callers to perform periodic checks.
    """
    try:
        async for changes in awatch(
            session_dir,
            stop_event=stop_event,
            rust_timeout=_WATCH_TIMEOUT_MS,
            poll_delay_ms=50,
        ):
            yield {path for _, path in changes}
    except (RuntimeError, FileNotFoundError):
        # awatch raises FileNotFoundError if the directory doesn't exist,
        # and RuntimeError if it is removed mid-watch.
        return


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


def _publish_terminal(run_id: str, status: str) -> None:
    """Publish a lifecycle event when a session reaches terminal state."""
    kind = f"session_{status}" if status in ("completed", "failed", "stopped") else None
    if kind:
        event_bus.publish(SessionEvent(kind=kind, run_id=run_id))


# ---------------------------------------------------------------------------
# Per-session: Agent tree SSE
# ---------------------------------------------------------------------------


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

        # Trace already has session_end even though DB says running
        if state.is_terminal:
            return

        # Active sessions: watch for file changes
        trace_path = os.path.join(session_dir, "trace.jsonl")
        stop = asyncio.Event()

        try:
            async for changed_files in _watch_session_dir(session_dir, stop):
                if await request.is_disconnected():
                    return

                changed = False

                if not changed_files:
                    # Timeout — no file changes; check DB status only
                    _, current_status = _resolve_session_dir(db_path, run_id)
                    if current_status in ("completed", "failed", "stopped"):
                        # Final read before closing
                        new_events, trace_offset = _read_trace_lines(
                            trace_path, trace_offset
                        )
                        for ev in new_events:
                            state.process_event(ev)
                        if new_events:
                            event_id += 1
                            yield format_sse(event_id, state.to_dict())
                        _publish_terminal(run_id, current_status)
                        return
                    continue

                # Check which files changed
                if any(f.endswith("session.json") for f in changed_files):
                    session_data = _read_session_json(session_dir)
                    if session_data:
                        state.load_session_json(session_data)
                        changed = True

                if any(f.endswith("trace.jsonl") for f in changed_files):
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
                    _publish_terminal(run_id, "completed")
                    return
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
# Per-session: Trace events SSE (incremental snapshot + delta)
# ---------------------------------------------------------------------------


@router.get("/sessions/{run_id}/events")
async def session_events_sse(run_id: str, request: Request):
    """SSE endpoint for real-time trace event streaming.

    Uses a snapshot+delta protocol:
    - Initial connect: sends ``event: snapshot`` with all events
    - Subsequent updates: sends ``event: delta`` with only new events
    """
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

        trace_path = os.path.join(session_dir, "trace.jsonl")
        all_events, trace_offset = _read_trace_lines(trace_path, 0)

        if all_events:
            event_id += 1
            yield format_sse_typed(event_id, "snapshot", {"events": all_events})

        # Terminal sessions: send all events and close
        if status in ("completed", "failed", "stopped"):
            return

        # Check if trace already contains session_end
        if any(e.get("event") == "session_end" for e in all_events):
            return

        # Active sessions: watch for new trace events
        stop = asyncio.Event()

        try:
            async for changed_files in _watch_session_dir(session_dir, stop):
                if await request.is_disconnected():
                    return

                if not changed_files:
                    # Timeout — check DB status
                    _, current_status = _resolve_session_dir(db_path, run_id)
                    if current_status in ("completed", "failed", "stopped"):
                        new_events, trace_offset = _read_trace_lines(
                            trace_path, trace_offset
                        )
                        if new_events:
                            event_id += 1
                            yield format_sse_typed(
                                event_id, "delta", {"events": new_events}
                            )
                        return
                    continue

                if any(f.endswith("trace.jsonl") for f in changed_files):
                    new_events, trace_offset = _read_trace_lines(
                        trace_path, trace_offset
                    )
                    if new_events:
                        event_id += 1
                        yield format_sse_typed(
                            event_id, "delta", {"events": new_events}
                        )

                        if any(
                            e.get("event") == "session_end" for e in new_events
                        ):
                            return
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
# Global: Cross-session lifecycle SSE
# ---------------------------------------------------------------------------


@router.get("/events")
async def global_events_sse(request: Request):
    """SSE endpoint for cross-session lifecycle notifications.

    Broadcasts named events: session_started, session_completed,
    session_failed, session_stopped.
    """
    bus: EventBus = request.app.state.event_bus

    async def event_stream():
        event_id = 0
        yield sse_retry(3000)

        async for session_event in bus.subscribe():
            if await request.is_disconnected():
                return
            event_id += 1
            yield format_sse_typed(event_id, session_event.kind, {
                "run_id": session_event.run_id,
                "project_id": session_event.project_id,
                **session_event.data,
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
