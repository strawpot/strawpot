"""Unit tests for SSE utilities and TreeState builder."""

from strawpot_gui.sse import TreeState, format_sse, sse_retry


class TestFormatSSE:
    def test_basic_format(self):
        result = format_sse(1, {"hello": "world"})
        assert result == 'id: 1\ndata: {"hello":"world"}\n\n'

    def test_retry_format(self):
        result = sse_retry(5000)
        assert result == "retry: 5000\n\n"

    def test_default_retry(self):
        result = sse_retry()
        assert result == "retry: 3000\n\n"


class TestTreeStateSessionJson:
    def test_load_root_agent(self):
        state = TreeState()
        state.load_session_json({
            "agents": {
                "agent_root": {
                    "role": "orchestrator",
                    "runtime": "strawpot-claude-code",
                    "parent": None,
                    "started_at": "T0",
                }
            }
        })
        result = state.to_dict()
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["agent_id"] == "agent_root"
        assert result["nodes"][0]["status"] == "running"

    def test_load_ignores_existing_agents(self):
        state = TreeState()
        state.load_session_json({
            "agents": {
                "agent_root": {
                    "role": "orchestrator",
                    "runtime": "strawpot-claude-code",
                    "parent": None,
                    "started_at": "T0",
                }
            }
        })
        # Loading again shouldn't overwrite
        state.load_session_json({
            "agents": {
                "agent_root": {
                    "role": "different",
                    "runtime": "different",
                    "parent": None,
                    "started_at": "T1",
                }
            }
        })
        assert state.to_dict()["nodes"][0]["role"] == "orchestrator"

    def test_empty_agents(self):
        state = TreeState()
        state.load_session_json({"agents": {}})
        assert state.to_dict()["nodes"] == []


class TestTreeStateTraceEvents:
    def test_delegate_start_creates_pending(self):
        state = TreeState()
        state.load_session_json({
            "agents": {
                "agent_root": {
                    "role": "orchestrator",
                    "runtime": "cc",
                    "parent": None,
                    "started_at": "T0",
                }
            }
        })
        state.process_event({
            "event": "session_start", "span_id": "s0", "data": {},
        })
        state.process_event({
            "event": "delegate_start", "span_id": "s1",
            "parent_span": "s0",
            "data": {"role": "implementer"},
        })
        result = state.to_dict()
        assert len(result["pending_delegations"]) == 1
        assert result["pending_delegations"][0]["role"] == "implementer"
        assert result["pending_delegations"][0]["requested_by"] == "agent_root"

    def test_agent_spawn_promotes_pending(self):
        state = TreeState()
        state.load_session_json({
            "agents": {
                "agent_root": {
                    "role": "orchestrator",
                    "runtime": "cc",
                    "parent": None,
                    "started_at": "T0",
                }
            }
        })
        state.process_event({
            "event": "session_start", "span_id": "s0", "data": {},
        })
        state.process_event({
            "event": "delegate_start", "span_id": "s1",
            "parent_span": "s0",
            "data": {"role": "implementer"},
        })
        state.process_event({
            "event": "agent_spawn", "span_id": "s1", "ts": "T2",
            "data": {"agent_id": "agent_impl", "runtime": "cc", "pid": 999},
        })
        result = state.to_dict()
        assert len(result["pending_delegations"]) == 0
        agent_ids = [n["agent_id"] for n in result["nodes"]]
        assert "agent_impl" in agent_ids
        impl = next(n for n in result["nodes"] if n["agent_id"] == "agent_impl")
        assert impl["parent"] == "agent_root"
        assert impl["status"] == "running"

    def test_agent_end_marks_completed(self):
        state = TreeState()
        state.process_event({
            "event": "session_start", "span_id": "s0", "data": {},
        })
        state.process_event({
            "event": "delegate_start", "span_id": "s1",
            "parent_span": "s0",
            "data": {"role": "impl"},
        })
        state.process_event({
            "event": "agent_spawn", "span_id": "s1", "ts": "T1",
            "data": {"agent_id": "a1", "runtime": "cc", "pid": 1},
        })
        state.process_event({
            "event": "agent_end", "span_id": "s1",
            "data": {"exit_code": 0, "duration_ms": 5000},
        })
        node = state.nodes["a1"]
        assert node.status == "completed"
        assert node.exit_code == 0
        assert node.duration_ms == 5000

    def test_agent_end_nonzero_marks_failed(self):
        state = TreeState()
        state.process_event({
            "event": "delegate_start", "span_id": "s1",
            "parent_span": None,
            "data": {"role": "impl"},
        })
        state.process_event({
            "event": "agent_spawn", "span_id": "s1", "ts": "T1",
            "data": {"agent_id": "a1", "runtime": "cc", "pid": 1},
        })
        state.process_event({
            "event": "agent_end", "span_id": "s1",
            "data": {"exit_code": 1, "duration_ms": 3000},
        })
        assert state.nodes["a1"].status == "failed"

    def test_delegate_denied_recorded(self):
        state = TreeState()
        state.process_event({
            "event": "delegate_denied", "span_id": "s2",
            "parent_span": "s0",
            "data": {"role": "admin", "reason": "DENY_DEPTH_LIMIT"},
        })
        result = state.to_dict()
        assert len(result["denied_delegations"]) == 1
        assert result["denied_delegations"][0]["role"] == "admin"
        assert result["denied_delegations"][0]["reason"] == "DENY_DEPTH_LIMIT"

    def test_agent_spawn_uses_event_role_when_no_pending(self):
        """Root agent_spawn (no prior delegate_start) reads role from event data."""
        state = TreeState()
        state.process_event({
            "event": "session_start", "span_id": "s0", "data": {},
        })
        state.process_event({
            "event": "agent_spawn", "span_id": "s0", "ts": "T0",
            "data": {
                "agent_id": "agent_root",
                "role": "ai-ceo",
                "runtime": "strawpot-claude-code",
                "pid": 123,
            },
        })
        assert state.nodes["agent_root"].role == "ai-ceo"

    def test_session_end_marks_terminal(self):
        state = TreeState()
        state.process_event({
            "event": "session_end", "span_id": "s0",
            "data": {"duration_ms": 1000},
        })
        assert state.is_terminal

    def test_session_end_completes_root(self):
        state = TreeState()
        state.load_session_json({
            "agents": {
                "agent_root": {
                    "role": "orchestrator",
                    "runtime": "cc",
                    "parent": None,
                    "started_at": "T0",
                }
            }
        })
        state.process_event({
            "event": "session_end", "span_id": "s0",
            "data": {"duration_ms": 5000},
        })
        assert state.nodes["agent_root"].status == "completed"
        assert state.nodes["agent_root"].duration_ms == 5000


class TestTreeStateFullLifecycle:
    def test_full_scenario(self):
        state = TreeState()
        state.load_session_json({
            "agents": {
                "agent_root": {
                    "role": "orchestrator",
                    "runtime": "strawpot-claude-code",
                    "parent": None,
                    "started_at": "T0",
                    "pid": 100,
                }
            }
        })
        events = [
            {"event": "session_start", "span_id": "s0",
             "data": {"run_id": "r1", "role": "orchestrator"}},
            {"event": "delegate_start", "span_id": "s1", "parent_span": "s0",
             "data": {"role": "implementer"}},
            {"event": "agent_spawn", "span_id": "s1", "ts": "T1",
             "data": {"agent_id": "agent_impl", "runtime": "cc", "pid": 200}},
            {"event": "delegate_start", "span_id": "s2", "parent_span": "s1",
             "data": {"role": "reviewer"}},
            {"event": "delegate_denied", "span_id": "s3", "parent_span": "s1",
             "data": {"role": "admin", "reason": "DENY_DEPTH_LIMIT"}},
            {"event": "agent_spawn", "span_id": "s2", "ts": "T2",
             "data": {"agent_id": "agent_rev", "runtime": "cc", "pid": 300}},
            {"event": "agent_end", "span_id": "s2",
             "data": {"exit_code": 0, "duration_ms": 10000}},
            {"event": "delegate_end", "span_id": "s2",
             "data": {"exit_code": 0, "summary": "Review done",
                       "duration_ms": 10000}},
            {"event": "agent_end", "span_id": "s1",
             "data": {"exit_code": 0, "duration_ms": 30000}},
            {"event": "delegate_end", "span_id": "s1", "parent_span": None,
             "data": {"exit_code": 0, "summary": "Implemented",
                       "duration_ms": 30000}},
            {"event": "session_end", "span_id": "s0",
             "data": {"duration_ms": 35000}},
        ]
        for ev in events:
            state.process_event(ev)

        result = state.to_dict()

        # 3 nodes: root, implementer, reviewer
        assert len(result["nodes"]) == 3
        ids = {n["agent_id"] for n in result["nodes"]}
        assert ids == {"agent_root", "agent_impl", "agent_rev"}

        # All completed
        for node in result["nodes"]:
            assert node["status"] == "completed"

        # Reviewer's parent is implementer
        rev = next(n for n in result["nodes"] if n["agent_id"] == "agent_rev")
        assert rev["parent"] == "agent_impl"

        # Implementer's parent is root
        impl = next(
            n for n in result["nodes"] if n["agent_id"] == "agent_impl"
        )
        assert impl["parent"] == "agent_root"

        # No pending delegations
        assert len(result["pending_delegations"]) == 0

        # 1 denied delegation
        assert len(result["denied_delegations"]) == 1
        assert result["denied_delegations"][0]["role"] == "admin"

        assert state.is_terminal
