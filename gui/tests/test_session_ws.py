"""Integration tests for the WebSocket session endpoint."""

import json
import os

from strawpot_gui.db import sync_sessions

from test_sessions_sync import _register_project, _write_session, _write_trace


def _collect_until(ws, until_type: str) -> list[dict]:
    """Receive WS messages until one of the given type is seen."""
    messages = []
    while True:
        msg = ws.receive_json()
        messages.append(msg)
        if msg.get("type") == until_type:
            break
    return messages


# ---------------------------------------------------------------------------
# Session not found
# ---------------------------------------------------------------------------


class TestSessionWSNotFound:
    def test_unknown_session_receives_error(self, client):
        with client.websocket_connect("/ws/sessions/run_nonexistent") as ws:
            msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "not found" in msg["message"].lower()


# ---------------------------------------------------------------------------
# Terminal sessions
# ---------------------------------------------------------------------------


class TestSessionWSTerminalSession:
    def test_sends_tree_snapshot_and_stream_complete(self, client, tmp_path):
        """Completed session: tree_snapshot + stream_complete, then close."""
        _register_project(client, tmp_path)
        _write_session(tmp_path, "run_ws1", archived=True)
        sync_sessions(client.app.state.db_path)

        with client.websocket_connect("/ws/sessions/run_ws1") as ws:
            messages = _collect_until(ws, "stream_complete")

        types = [m["type"] for m in messages]
        assert "tree_snapshot" in types
        assert "stream_complete" in types

    def test_trace_snapshot_included_when_trace_exists(self, client, tmp_path):
        """Trace events are batched into a trace_snapshot message."""
        _register_project(client, tmp_path)
        session_dir = _write_session(tmp_path, "run_ws2", archived=True)
        _write_trace(session_dir, [
            {"ts": "T1", "event": "session_start", "trace_id": "run_ws2",
             "span_id": "s0", "data": {}},
            {"ts": "T2", "event": "session_end", "trace_id": "run_ws2",
             "span_id": "s0", "data": {"duration_ms": 5000}},
        ])
        sync_sessions(client.app.state.db_path)

        with client.websocket_connect("/ws/sessions/run_ws2") as ws:
            messages = _collect_until(ws, "stream_complete")

        by_type = {m["type"]: m for m in messages}
        assert "trace_snapshot" in by_type
        assert len(by_type["trace_snapshot"]["events"]) == 2
        assert by_type["trace_snapshot"]["events"][0]["event"] == "session_start"
        assert by_type["trace_snapshot"]["next_offset"] > 0

    def test_no_trace_snapshot_when_trace_empty(self, client, tmp_path):
        """No trace_snapshot message when session has no trace file."""
        _register_project(client, tmp_path)
        _write_session(tmp_path, "run_ws3", archived=True)
        sync_sessions(client.app.state.db_path)

        with client.websocket_connect("/ws/sessions/run_ws3") as ws:
            messages = _collect_until(ws, "stream_complete")

        types = [m["type"] for m in messages]
        assert "trace_snapshot" not in types

    def test_tree_snapshot_contains_nodes_from_trace(self, client, tmp_path):
        """Sub-agents from trace events appear in tree_snapshot nodes."""
        _register_project(client, tmp_path)
        session_dir = _write_session(tmp_path, "run_ws4", archived=True)
        _write_trace(session_dir, [
            {"ts": "T1", "event": "session_start", "trace_id": "run_ws4",
             "span_id": "s0", "data": {}},
            {"ts": "T2", "event": "delegate_start", "trace_id": "run_ws4",
             "span_id": "s1", "parent_span": "s0",
             "data": {"role": "implementer"}},
            {"ts": "T3", "event": "agent_spawn", "trace_id": "run_ws4",
             "span_id": "s1", "parent_span": "s0",
             "data": {"agent_id": "agent_impl", "runtime": "cc", "pid": 999}},
            {"ts": "T4", "event": "agent_end", "trace_id": "run_ws4",
             "span_id": "s1", "data": {"exit_code": 0, "duration_ms": 10000}},
            {"ts": "T5", "event": "session_end", "trace_id": "run_ws4",
             "span_id": "s0", "data": {"duration_ms": 11000}},
        ])
        sync_sessions(client.app.state.db_path)

        with client.websocket_connect("/ws/sessions/run_ws4") as ws:
            messages = _collect_until(ws, "stream_complete")

        tree = next(m for m in messages if m["type"] == "tree_snapshot")
        agent_ids = [n["agent_id"] for n in tree["nodes"]]
        assert "agent_abc" in agent_ids
        assert "agent_impl" in agent_ids
        impl = next(n for n in tree["nodes"] if n["agent_id"] == "agent_impl")
        assert impl["status"] == "completed"
        assert impl["parent"] == "agent_abc"

    def test_denied_delegations_in_tree_snapshot(self, client, tmp_path):
        """Denied delegations appear in tree_snapshot."""
        _register_project(client, tmp_path)
        session_dir = _write_session(tmp_path, "run_ws5", archived=True)
        _write_trace(session_dir, [
            {"ts": "T1", "event": "session_start", "trace_id": "run_ws5",
             "span_id": "s0", "data": {}},
            {"ts": "T2", "event": "delegate_denied", "trace_id": "run_ws5",
             "span_id": "s1", "parent_span": "s0",
             "data": {"role": "admin", "reason": "DENY_DEPTH_LIMIT"}},
            {"ts": "T3", "event": "session_end", "trace_id": "run_ws5",
             "span_id": "s0", "data": {"duration_ms": 1000}},
        ])
        sync_sessions(client.app.state.db_path)

        with client.websocket_connect("/ws/sessions/run_ws5") as ws:
            messages = _collect_until(ws, "stream_complete")

        tree = next(m for m in messages if m["type"] == "tree_snapshot")
        assert len(tree["denied_delegations"]) == 1
        assert tree["denied_delegations"][0]["role"] == "admin"
        assert tree["denied_delegations"][0]["reason"] == "DENY_DEPTH_LIMIT"


# ---------------------------------------------------------------------------
# ask_user
# ---------------------------------------------------------------------------


class TestSessionWSAskUser:
    def test_pending_ask_user_not_sent_for_terminal_session(self, client, tmp_path):
        """Terminal sessions do not send stale ask_user messages."""
        _register_project(client, tmp_path)
        session_dir = _write_session(tmp_path, "run_ws6", archived=True)
        pending_path = os.path.join(session_dir, "ask_user_pending_req1.json")
        with open(pending_path, "w") as f:
            json.dump({
                "request_id": "req1",
                "question": "Choose a color?",
                "type": "ask_user",
                "timestamp": 1234567890.0,
            }, f)
        sync_sessions(client.app.state.db_path)

        with client.websocket_connect("/ws/sessions/run_ws6") as ws:
            messages = _collect_until(ws, "stream_complete")

        ask = next((m for m in messages if m.get("type") == "ask_user"), None)
        assert ask is None, "Terminal sessions should not send stale ask_user messages"

    def test_ask_user_response_writes_file(self, tmp_path):
        """_write_ask_user_response writes the correct response file.

        Tests the function the WS message_receiver calls directly — avoids
        active-session TestClient teardown complications with file_watcher.
        """
        from strawpot_gui.routers.ws import _write_ask_user_response

        session_dir = str(tmp_path)
        _write_ask_user_response(session_dir, "req2", "42")

        response_path = tmp_path / "ask_user_response_req2.json"
        assert response_path.is_file()
        data = json.loads(response_path.read_text())
        assert data["request_id"] == "req2"
        assert data["text"] == "42"


# ---------------------------------------------------------------------------
# Trace offset resumption
# ---------------------------------------------------------------------------


class TestSessionWSTraceResumption:
    def test_offset_skips_already_seen_events(self, client, tmp_path):
        """Sending trace_offset=N skips events before byte offset N."""
        _register_project(client, tmp_path)
        session_dir = _write_session(tmp_path, "run_ws8", archived=True)
        _write_trace(session_dir, [
            {"ts": "T1", "event": "session_start", "trace_id": "run_ws8",
             "span_id": "s0", "data": {}},
            {"ts": "T2", "event": "session_end", "trace_id": "run_ws8",
             "span_id": "s0", "data": {"duration_ms": 1000}},
        ])
        sync_sessions(client.app.state.db_path)

        # First connect — get all events and record offset
        with client.websocket_connect("/ws/sessions/run_ws8") as ws:
            messages = _collect_until(ws, "stream_complete")
        trace_msg = next(m for m in messages if m["type"] == "trace_snapshot")
        full_offset = trace_msg["next_offset"]
        assert full_offset > 0

        # Second connect with full offset → no new events → no trace_snapshot
        with client.websocket_connect("/ws/sessions/run_ws8") as ws:
            ws.send_json({"type": "init", "trace_offset": full_offset})
            messages2 = _collect_until(ws, "stream_complete")

        types2 = [m["type"] for m in messages2]
        assert "trace_snapshot" not in types2
        assert "tree_snapshot" in types2
        assert "stream_complete" in types2


# ---------------------------------------------------------------------------
# Agent log subscriptions (subscribe_logs / unsubscribe_logs)
# ---------------------------------------------------------------------------


class TestSessionWSAgentLogs:
    def test_subscribe_logs_terminal_session(self, client, tmp_path):
        """subscribe_logs on a terminal session sends snapshot + done."""
        _register_project(client, tmp_path)
        session_dir = _write_session(tmp_path, "run_log1", archived=True)

        # Write a log file for the agent
        agent_dir = os.path.join(session_dir, "agents", "agent_abc")
        os.makedirs(agent_dir, exist_ok=True)
        with open(os.path.join(agent_dir, ".log"), "w") as f:
            f.write("line 1\nline 2\nline 3\n")

        sync_sessions(client.app.state.db_path)

        with client.websocket_connect("/ws/sessions/run_log1") as ws:
            # Send subscribe_logs immediately (server drains these for terminal sessions)
            ws.send_json({"type": "subscribe_logs", "agent_id": "agent_abc"})
            messages = _collect_until(ws, "stream_complete")

        # Find log messages
        snapshot = next((m for m in messages if m["type"] == "agent_log_snapshot"), None)
        done = next((m for m in messages if m["type"] == "agent_log_done"), None)

        assert snapshot is not None
        assert snapshot["agent_id"] == "agent_abc"
        assert snapshot["lines"] == ["line 1", "line 2", "line 3"]
        assert snapshot["offset"] > 0
        assert done is not None
        assert done["agent_id"] == "agent_abc"

    def test_subscribe_logs_invalid_agent(self, client, tmp_path):
        """subscribe_logs with unknown agent_id is silently ignored."""
        _register_project(client, tmp_path)
        _write_session(tmp_path, "run_log2", archived=True)
        sync_sessions(client.app.state.db_path)

        with client.websocket_connect("/ws/sessions/run_log2") as ws:
            # Send immediately — server drains subscribe_logs for terminal sessions
            ws.send_json({"type": "subscribe_logs", "agent_id": "nonexistent"})
            messages = _collect_until(ws, "stream_complete")

        # No agent_log_snapshot for invalid agent
        log_msgs = [m for m in messages if m["type"].startswith("agent_log_")]
        assert len(log_msgs) == 0

    def test_subscribe_logs_empty_log(self, client, tmp_path):
        """subscribe_logs with no log file sends empty snapshot + done."""
        _register_project(client, tmp_path)
        session_dir = _write_session(tmp_path, "run_log3", archived=True)

        # Create agent dir but no .log file
        agent_dir = os.path.join(session_dir, "agents", "agent_abc")
        os.makedirs(agent_dir, exist_ok=True)

        sync_sessions(client.app.state.db_path)

        with client.websocket_connect("/ws/sessions/run_log3") as ws:
            # Send immediately — server drains subscribe_logs for terminal sessions
            ws.send_json({"type": "subscribe_logs", "agent_id": "agent_abc"})
            messages = _collect_until(ws, "stream_complete")

        snapshot = next((m for m in messages if m["type"] == "agent_log_snapshot"), None)
        assert snapshot is not None
        assert snapshot["lines"] == []
        assert snapshot["offset"] == 0


# ---------------------------------------------------------------------------
# Global WebSocket: /ws/events
# ---------------------------------------------------------------------------


class TestGlobalEventsWS:
    def test_receives_lifecycle_event(self, client):
        """Global WS receives events published to the event bus."""
        from strawpot_gui.event_bus import SessionEvent, event_bus

        with client.websocket_connect("/ws/events") as ws:
            # Publish an event
            event_bus.publish(SessionEvent(
                kind="session_completed",
                run_id="run_evt1",
                project_id=42,
            ))

            msg = ws.receive_json()
            # Skip pings if any
            while msg.get("type") == "ping":
                msg = ws.receive_json()

        assert msg["type"] == "session_completed"
        assert msg["run_id"] == "run_evt1"
        assert msg["project_id"] == 42

    def test_receives_multiple_events(self, client):
        """Global WS receives multiple events in sequence."""
        from strawpot_gui.event_bus import SessionEvent, event_bus

        with client.websocket_connect("/ws/events") as ws:
            event_bus.publish(SessionEvent(kind="session_started", run_id="r1"))
            event_bus.publish(SessionEvent(kind="session_completed", run_id="r2"))

            events = []
            for _ in range(10):  # read up to 10 messages
                msg = ws.receive_json()
                if msg.get("type") != "ping":
                    events.append(msg)
                if len(events) >= 2:
                    break

        assert events[0]["type"] == "session_started"
        assert events[0]["run_id"] == "r1"
        assert events[1]["type"] == "session_completed"
        assert events[1]["run_id"] == "r2"
