"""SSE streaming endpoints for real-time session monitoring."""

import asyncio
import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from strawpot_gui.event_bus import EventBus, SessionEvent, event_bus
from strawpot_gui.sse import (
    TreeState,
    format_sse,
    format_sse_typed,
    resolve_session_dir,
    sse_retry,
    watch_dir,
)

router = APIRouter(prefix="/api", tags=["sse"])


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


def _append_chat_message(
    session_dir: str, role: str, text: str, msg_id: str, timestamp: float
) -> None:
    """Append a chat message to the session's chat_messages.jsonl."""
    path = os.path.join(session_dir, "chat_messages.jsonl")
    entry = json.dumps(
        {"id": msg_id, "role": role, "text": text, "timestamp": timestamp}
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def _read_chat_messages(session_dir: str) -> list[dict]:
    """Read all chat messages from chat_messages.jsonl."""
    path = os.path.join(session_dir, "chat_messages.jsonl")
    messages: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return messages


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


def _publish_terminal(run_id: str, status: str, project_id: int | None = None) -> None:
    """Publish a lifecycle event when a session reaches terminal state."""
    kind = f"session_{status}" if status in ("completed", "failed", "stopped") else None
    if kind:
        event_bus.publish(SessionEvent(kind=kind, run_id=run_id, project_id=project_id))


# ---------------------------------------------------------------------------
# Per-session: Agent tree SSE
# ---------------------------------------------------------------------------


@router.get("/sessions/{run_id}/tree")
async def session_tree_sse(run_id: str, request: Request):
    """SSE endpoint for real-time agent tree updates."""
    db_path = request.app.state.db_path
    session_dir, status, project_id = resolve_session_dir(db_path, run_id)

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

        # Send chat history on initial connect
        chat_messages = _read_chat_messages(session_dir)
        if chat_messages:
            event_id += 1
            yield format_sse_typed(event_id, "chat_history", {"messages": chat_messages})

        # Track which ask_user IDs have already been persisted
        persisted_ask_ids: set[str] = {m["id"] for m in chat_messages if m.get("role") == "agent"}

        # Check for pending ask_user on initial connect
        ask_user_path = os.path.join(session_dir, "ask_user_pending.json")
        if os.path.isfile(ask_user_path):
            try:
                with open(ask_user_path, encoding="utf-8") as f:
                    ask_data = json.load(f)
                req_id = ask_data.get("request_id", "")
                if req_id and req_id not in persisted_ask_ids:
                    _append_chat_message(
                        session_dir, "agent", ask_data.get("question", ""),
                        req_id, ask_data.get("timestamp", 0),
                    )
                    persisted_ask_ids.add(req_id)
                event_id += 1
                yield format_sse_typed(event_id, "ask_user", ask_data)
            except (OSError, json.JSONDecodeError):
                pass

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
            async for changed_files in watch_dir(session_dir, stop):
                if await request.is_disconnected():
                    return

                changed = False

                if not changed_files:
                    # Timeout — no file changes; check DB status only
                    _, current_status, _ = resolve_session_dir(db_path, run_id)
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
                        _publish_terminal(run_id, current_status, project_id)
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

                # Detect ask_user bridge files
                if any(
                    f.endswith("ask_user_pending.json")
                    or f.endswith("ask_user_response.json")
                    for f in changed_files
                ):
                    pending = os.path.join(session_dir, "ask_user_pending.json")
                    if os.path.isfile(pending):
                        try:
                            with open(pending, encoding="utf-8") as f:
                                ask_data = json.load(f)
                            req_id = ask_data.get("request_id", "")
                            if req_id and req_id not in persisted_ask_ids:
                                _append_chat_message(
                                    session_dir, "agent",
                                    ask_data.get("question", ""),
                                    req_id, ask_data.get("timestamp", 0),
                                )
                                persisted_ask_ids.add(req_id)
                            event_id += 1
                            yield format_sse_typed(event_id, "ask_user", ask_data)
                        except (OSError, json.JSONDecodeError):
                            pass
                    else:
                        # Pending file removed → question resolved
                        event_id += 1
                        yield format_sse_typed(
                            event_id, "ask_user_resolved", {}
                        )

                if changed:
                    event_id += 1
                    yield format_sse(event_id, state.to_dict())

                if state.is_terminal:
                    _publish_terminal(run_id, "completed", project_id)
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
    session_dir, status, _ = resolve_session_dir(db_path, run_id)

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
            async for changed_files in watch_dir(session_dir, stop):
                if await request.is_disconnected():
                    return

                if not changed_files:
                    # Timeout — check DB status
                    _, current_status, _ = resolve_session_dir(db_path, run_id)
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
            if session_event is None:
                continue
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
