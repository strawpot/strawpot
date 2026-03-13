"""WebSocket endpoint for real-time session monitoring.

Single bidirectional connection per session replaces the former pair of
SSE connections (/tree + /events), eliminating HTTP/1.1 connection-pool
exhaustion when multiple tabs are open.

Protocol
--------
Client → server (after connect):
  {"type": "init", "trace_offset": 0}          # optional; 0 = full snapshot
  {"type": "ask_user_response", "request_id": "...", "text": "..."}
  {"type": "subscribe_logs", "agent_id": "...", "offset": 0}
  {"type": "unsubscribe_logs", "agent_id": "..."}

Server → client:
  {"type": "tree_snapshot", nodes: [...], ...}  # on connect
  {"type": "tree_delta",    nodes: [...], ...}  # on tree change
  {"type": "trace_snapshot", "events": [...], "next_offset": N}
  {"type": "trace_delta",    "events": [...], "next_offset": N}
  {"type": "chat_history",   "messages": [...]}
  {"type": "ask_user",       ...AskUserPending}
  {"type": "ask_user_resolved", "request_id": "..."}
  {"type": "agent_log_snapshot", "agent_id": "...", "lines": [...], "offset": N}
  {"type": "agent_log_delta",    "agent_id": "...", "lines": [...], "offset": N}
  {"type": "agent_log_done",     "agent_id": "..."}
  {"type": "stream_complete"}
  {"type": "error", "message": "..."}

Global WebSocket: /ws/events
  Server → client (receive-only):
  {"type": "session_started|session_completed|session_failed|session_stopped",
   "run_id": "...", "project_id": N, ...}
"""

import asyncio
import glob
import json
import os

from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from strawpot_gui.event_bus import event_bus
from strawpot_gui.routers.logs import read_log_delta, read_log_tail, validate_agent
from strawpot_gui.sse import (
    TreeState,
    resolve_session_dir,
    watch_dir,
)

router = APIRouter(tags=["websocket"])


# ---------------------------------------------------------------------------
# Helpers (shared logic with the former SSE tree router)
# ---------------------------------------------------------------------------


def _read_session_json(session_dir: str) -> dict | None:
    path = os.path.join(session_dir, "session.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _read_trace_lines(trace_path: str, offset: int) -> tuple[list[dict], int]:
    """Read new JSONL lines from trace_path starting at byte offset."""
    events: list[dict] = []
    try:
        with open(trace_path, "r", encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    events.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
            new_offset = f.tell()
    except OSError:
        return [], offset
    return events, new_offset


def _scan_pending_ask_users(session_dir: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    pattern = os.path.join(session_dir, "ask_user_pending_*.json")
    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            req_id = data.get("request_id", "")
            if req_id:
                result[req_id] = data
        except (OSError, json.JSONDecodeError):
            pass
    return result


def _read_chat_messages(session_dir: str) -> list[dict]:
    path = os.path.join(session_dir, "chat_messages.jsonl")
    messages: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    messages.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return messages


def _build_full_state(session_dir: str) -> tuple[TreeState, int]:
    state = TreeState()
    data = _read_session_json(session_dir)
    if data:
        state.load_session_json(data)
    trace_path = os.path.join(session_dir, "trace.jsonl")
    events, offset = _read_trace_lines(trace_path, 0)
    for ev in events:
        state.process_event(ev)
    return state, offset


def _write_ask_user_response(session_dir: str, request_id: str, text: str) -> None:
    path = os.path.join(session_dir, f"ask_user_response_{request_id}.json")
    payload = json.dumps({"request_id": request_id, "text": text})
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)


def _publish_terminal(run_id: str, status: str, project_id: int | None) -> None:
    kind = f"session_{status}" if status in ("completed", "failed", "stopped") else None
    if kind:
        from strawpot_gui.event_bus import SessionEvent
        event_bus.publish(SessionEvent(kind=kind, run_id=run_id, project_id=project_id))


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/sessions/{run_id}")
async def session_ws(websocket: WebSocket, run_id: str) -> None:
    """Real-time session WebSocket.

    Sends tree state, trace events, chat history, and ask_user
    notifications.  Accepts ask_user_response messages from the client.
    """
    db_path: str = websocket.app.state.db_path
    session_dir, status, project_id = resolve_session_dir(db_path, run_id)

    if session_dir is None:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "Session not found"})
        await websocket.close(code=4004)
        return

    await websocket.accept()

    # ---- Read optional init message for trace offset resumption ----
    trace_offset = 0
    early_subscribes: list[dict] = []
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
        msg = json.loads(raw)
        if msg.get("type") == "init":
            trace_offset = int(msg.get("trace_offset", 0))
        elif msg.get("type") == "subscribe_logs":
            early_subscribes.append(msg)
    except (asyncio.TimeoutError, json.JSONDecodeError, ValueError, WebSocketDisconnect):
        pass

    # ---- Build and send initial state ----
    state, _ = _build_full_state(session_dir)
    await websocket.send_json({"type": "tree_snapshot", **state.to_dict()})

    trace_path = os.path.join(session_dir, "trace.jsonl")
    all_trace, new_offset = _read_trace_lines(trace_path, trace_offset)
    if all_trace:
        await websocket.send_json({
            "type": "trace_snapshot",
            "events": all_trace,
            "next_offset": new_offset,
        })
    trace_offset = new_offset

    chat_messages = _read_chat_messages(session_dir)
    if chat_messages:
        await websocket.send_json({"type": "chat_history", "messages": chat_messages})

    known_pending_ids: set[str] = set()
    pending_map = _scan_pending_ask_users(session_dir)
    for req_id, ask_data in pending_map.items():
        known_pending_ids.add(req_id)
        await websocket.send_json({"type": "ask_user", **ask_data})

    # Terminal sessions: handle pending subscribe_logs, send final state, close
    if status in ("completed", "failed", "stopped") or state.is_terminal:
        async def _send_log_snapshot(agent_id: str) -> None:
            if validate_agent(session_dir, agent_id):
                lines, offset = read_log_tail(
                    os.path.join(session_dir, "agents", agent_id, ".log")
                )
                await websocket.send_json({
                    "type": "agent_log_snapshot",
                    "agent_id": agent_id,
                    "lines": lines,
                    "offset": offset,
                })
                await websocket.send_json({
                    "type": "agent_log_done",
                    "agent_id": agent_id,
                })

        # Process any subscribe_logs received during init
        for sub in early_subscribes:
            aid = sub.get("agent_id", "")
            if aid:
                await _send_log_snapshot(aid)

        # Drain additional subscribe_logs from the client
        try:
            while True:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "subscribe_logs":
                    aid = msg.get("agent_id", "")
                    if aid:
                        await _send_log_snapshot(aid)
        except (asyncio.TimeoutError, WebSocketDisconnect):
            pass
        await websocket.send_json({"type": "stream_complete"})
        await websocket.close()
        return

    # ---- Active session: watch files + handle client messages ----
    send_queue: asyncio.Queue[dict | None] = asyncio.Queue()
    stop = asyncio.Event()
    log_watcher_tasks: dict[str, asyncio.Task] = {}

    async def agent_log_watcher(agent_id: str, initial_offset: int | None) -> None:
        """Watch a single agent's .log file and push deltas to send_queue."""
        log_path = os.path.join(session_dir, "agents", agent_id, ".log")
        agent_dir = os.path.join(session_dir, "agents", agent_id)

        # Send initial snapshot
        lines, offset = read_log_tail(log_path)
        send_queue.put_nowait({
            "type": "agent_log_snapshot",
            "agent_id": agent_id,
            "lines": lines,
            "offset": offset,
        })

        if initial_offset is not None and initial_offset > 0:
            offset = initial_offset

        # If already terminal, send done immediately
        if status in ("completed", "failed", "stopped") or state.is_terminal:
            send_queue.put_nowait({"type": "agent_log_done", "agent_id": agent_id})
            return

        log_stop = asyncio.Event()

        def check_stop():
            if stop.is_set():
                log_stop.set()

        try:
            async for changed_files in watch_dir(agent_dir, log_stop):
                check_stop()
                if log_stop.is_set():
                    return

                if not changed_files:
                    # Timeout — check if session ended
                    if state.is_terminal or stop.is_set():
                        new_lines, offset = read_log_delta(log_path, offset)
                        if new_lines:
                            send_queue.put_nowait({
                                "type": "agent_log_delta",
                                "agent_id": agent_id,
                                "lines": new_lines,
                                "offset": offset,
                            })
                        send_queue.put_nowait({"type": "agent_log_done", "agent_id": agent_id})
                        return
                    continue

                if any(f.endswith(".log") for f in changed_files):
                    new_lines, offset = read_log_delta(log_path, offset)
                    if new_lines:
                        send_queue.put_nowait({
                            "type": "agent_log_delta",
                            "agent_id": agent_id,
                            "lines": new_lines,
                            "offset": offset,
                        })
        except asyncio.CancelledError:
            pass
        finally:
            log_stop.set()

    async def file_watcher() -> None:
        nonlocal trace_offset, known_pending_ids
        db_path_local = db_path
        try:
            async for changed_files in watch_dir(session_dir, stop):
                changed = False

                if not changed_files:
                    # Timeout — check DB status only
                    _, current_status, _ = resolve_session_dir(db_path_local, run_id)
                    if current_status in ("completed", "failed", "stopped"):
                        new_evs, trace_offset = _read_trace_lines(trace_path, trace_offset)
                        for ev in new_evs:
                            state.process_event(ev)
                        if new_evs:
                            send_queue.put_nowait({
                                "type": "trace_delta",
                                "events": new_evs,
                                "next_offset": trace_offset,
                            })
                            send_queue.put_nowait({"type": "tree_delta", **state.to_dict()})
                        _publish_terminal(run_id, current_status, project_id)
                        send_queue.put_nowait({"type": "stream_complete"})
                        send_queue.put_nowait(None)
                        return
                    continue

                if any(f.endswith("session.json") for f in changed_files):
                    data = _read_session_json(session_dir)
                    if data:
                        state.load_session_json(data)
                        changed = True

                if any(f.endswith("trace.jsonl") for f in changed_files):
                    new_evs, trace_offset = _read_trace_lines(trace_path, trace_offset)
                    for ev in new_evs:
                        state.process_event(ev)
                    if new_evs:
                        changed = True
                        send_queue.put_nowait({
                            "type": "trace_delta",
                            "events": new_evs,
                            "next_offset": trace_offset,
                        })

                if any(
                    "ask_user_pending_" in f or "ask_user_response_" in f
                    for f in changed_files
                ):
                    current_pending = _scan_pending_ask_users(session_dir)
                    current_ids = set(current_pending.keys())
                    for req_id in current_ids - known_pending_ids:
                        send_queue.put_nowait({"type": "ask_user", **current_pending[req_id]})
                    for req_id in known_pending_ids - current_ids:
                        send_queue.put_nowait({"type": "ask_user_resolved", "request_id": req_id})
                    known_pending_ids = current_ids

                if any(f.endswith("chat_messages.jsonl") for f in changed_files):
                    updated = _read_chat_messages(session_dir)
                    if updated:
                        send_queue.put_nowait({"type": "chat_history", "messages": updated})

                if changed:
                    send_queue.put_nowait({"type": "tree_delta", **state.to_dict()})

                if state.is_terminal:
                    _publish_terminal(run_id, "completed", project_id)
                    send_queue.put_nowait({"type": "stream_complete"})
                    send_queue.put_nowait(None)
                    return
        finally:
            stop.set()
            send_queue.put_nowait(None)

    async def message_receiver() -> None:
        """Handle incoming client messages (ask_user_response, subscribe/unsubscribe_logs)."""
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg_type = msg.get("type")
                if msg_type == "ask_user_response":
                    req_id = msg.get("request_id", "")
                    text = msg.get("text", "")
                    if req_id:
                        try:
                            _write_ask_user_response(session_dir, req_id, text)
                        except OSError:
                            pass
                elif msg_type == "subscribe_logs":
                    agent_id = msg.get("agent_id", "")
                    if agent_id and agent_id not in log_watcher_tasks:
                        if validate_agent(session_dir, agent_id):
                            offset = msg.get("offset")
                            task = asyncio.create_task(
                                agent_log_watcher(agent_id, offset)
                            )
                            log_watcher_tasks[agent_id] = task
                elif msg_type == "unsubscribe_logs":
                    agent_id = msg.get("agent_id", "")
                    task = log_watcher_tasks.pop(agent_id, None)
                    if task:
                        task.cancel()
        except WebSocketDisconnect:
            stop.set()
            send_queue.put_nowait(None)

    async def message_sender() -> None:
        """Drain send_queue and write to the WebSocket."""
        while True:
            msg = await send_queue.get()
            if msg is None:
                break
            try:
                await websocket.send_json(msg)
                if msg.get("type") == "stream_complete":
                    await websocket.close()
                    break
            except Exception:
                break

    watcher_task = asyncio.create_task(file_watcher())
    receiver_task = asyncio.create_task(message_receiver())
    sender_task = asyncio.create_task(message_sender())

    try:
        await asyncio.wait(
            {watcher_task, receiver_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        stop.set()
        send_queue.put_nowait(None)
        all_tasks = [watcher_task, receiver_task, sender_task]
        all_tasks.extend(log_watcher_tasks.values())
        log_watcher_tasks.clear()
        for task in all_tasks:
            task.cancel()
        await asyncio.gather(*all_tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# Global WebSocket: lifecycle events
# ---------------------------------------------------------------------------


@router.websocket("/ws/events")
async def global_events_ws(websocket: WebSocket) -> None:
    """Global WebSocket for session lifecycle notifications.

    Replaces the SSE ``/api/events`` endpoint.  Receive-only — the server
    accepts but ignores any client frames.
    """
    await websocket.accept()

    bus = event_bus

    try:
        async for session_event in bus.subscribe():
            if session_event is None:
                # Periodic heartbeat — send ping to detect dead connections
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue
            try:
                await websocket.send_json({
                    "type": session_event.kind,
                    "run_id": session_event.run_id,
                    "project_id": session_event.project_id,
                    **session_event.data,
                })
            except Exception:
                break
    except WebSocketDisconnect:
        pass
