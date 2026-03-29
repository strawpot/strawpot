"""Unit tests for SSE utilities and TreeState builder."""

from unittest.mock import patch

from strawpot_gui.sse import TreeState, _compose_activity, format_sse, sse_retry


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
             "data": {"exit_code": 0,
                       "duration_ms": 10000}},
            {"event": "agent_end", "span_id": "s1",
             "data": {"exit_code": 0, "duration_ms": 30000}},
            {"event": "delegate_end", "span_id": "s1", "parent_span": None,
             "data": {"exit_code": 0,
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


class TestTreeStateCancelEvents:
    """Tests for cancel event processing in TreeState."""

    def test_cancel_start_sets_cancelling(self):
        state = TreeState()
        state.load_session_json({
            "agents": {
                "a1": {"role": "orch", "runtime": "cc", "parent": None},
                "a2": {"role": "worker", "runtime": "cc", "parent": "a1"},
            }
        })
        state.process_event({
            "event": "agent_cancel_start",
            "span_id": "s0",
            "data": {"agent_id": "a1", "descendants": ["a2"]},
        })
        assert state.nodes["a1"].status == "cancelling"
        assert state.nodes["a2"].status == "cancelling"

    def test_cancel_complete_sets_cancelled(self):
        state = TreeState()
        state.load_session_json({
            "agents": {
                "a1": {"role": "orch", "runtime": "cc", "parent": None},
                "a2": {"role": "worker", "runtime": "cc", "parent": "a1"},
            }
        })
        state.process_event({
            "event": "agent_cancel_complete",
            "span_id": "s0",
            "data": {"cancelled_agents": ["a2", "a1"]},
        })
        assert state.nodes["a1"].status == "cancelled"
        assert state.nodes["a2"].status == "cancelled"

    def test_cancel_unknown_agents_ignored(self):
        state = TreeState()
        # Should not raise on unknown agent IDs
        state.process_event({
            "event": "agent_cancel_start",
            "span_id": "s0",
            "data": {"agent_id": "unknown", "descendants": ["also_unknown"]},
        })
        state.process_event({
            "event": "agent_cancel_complete",
            "span_id": "s0",
            "data": {"cancelled_agents": ["unknown"]},
        })


class TestTreeStateToolActivity:
    """Tests for tool_start/tool_end activity tracking in TreeState."""

    def _make_state_with_running_agent(self, agent_id="a1"):
        """Helper: create a TreeState with one running agent."""
        state = TreeState()
        state.process_event({
            "event": "delegate_start", "span_id": "s1",
            "parent_span": None, "data": {"role": "impl"},
        })
        state.process_event({
            "event": "agent_spawn", "span_id": "s1", "ts": "T1",
            "data": {"agent_id": agent_id, "runtime": "cc", "pid": 1},
        })
        return state

    def test_tool_start_sets_current_activity_from_summary(self):
        """tool_start with a summary sets current_activity to the summary."""
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "tool_start", "span_id": "s2",
            "data": {"agent_id": "a1", "tool": "Bash", "summary": "Running tests"},
        })
        assert state.nodes["a1"].current_activity == "Running tests"

    def test_tool_start_falls_back_to_tool_name(self):
        """tool_start without summary uses the tool name as activity."""
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "tool_start", "span_id": "s2",
            "data": {"agent_id": "a1", "tool": "Read", "summary": ""},
        })
        assert state.nodes["a1"].current_activity == "Read"

    def test_tool_start_with_empty_tool_and_summary_sets_none(self):
        """tool_start with both empty tool and summary sets None."""
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "tool_start", "span_id": "s2",
            "data": {"agent_id": "a1", "tool": "", "summary": ""},
        })
        assert state.nodes["a1"].current_activity is None

    def test_tool_end_clears_current_activity(self):
        """tool_end resets current_activity to None."""
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "tool_start", "span_id": "s2",
            "data": {"agent_id": "a1", "tool": "Bash", "summary": "Running tests"},
        })
        assert state.nodes["a1"].current_activity == "Running tests"
        state.process_event({
            "event": "tool_end", "span_id": "s2",
            "data": {"agent_id": "a1", "tool": "Bash", "duration_ms": 500},
        })
        assert state.nodes["a1"].current_activity is None

    def test_tool_start_unknown_agent_ignored(self):
        """tool_start for a non-existent agent_id does not raise."""
        state = TreeState()
        state.process_event({
            "event": "tool_start", "span_id": "s2",
            "data": {"agent_id": "nonexistent", "tool": "Bash"},
        })
        assert "nonexistent" not in state.nodes

    def test_tool_end_unknown_agent_ignored(self):
        """tool_end for a non-existent agent_id does not raise."""
        state = TreeState()
        state.process_event({
            "event": "tool_end", "span_id": "s2",
            "data": {"agent_id": "nonexistent", "tool": "Bash"},
        })

    def test_tool_start_empty_agent_id_ignored(self):
        """tool_start with empty agent_id does nothing."""
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "tool_start", "span_id": "s2",
            "data": {"agent_id": "", "tool": "Bash", "summary": "x"},
        })
        assert state.nodes["a1"].current_activity is None

    def test_sequential_tool_starts_overwrite_activity(self):
        """A second tool_start overwrites the activity from the first."""
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "tool_start", "span_id": "s2",
            "data": {"agent_id": "a1", "tool": "Bash", "summary": "First"},
        })
        state.process_event({
            "event": "tool_start", "span_id": "s3",
            "data": {"agent_id": "a1", "tool": "Read", "summary": "Second"},
        })
        assert state.nodes["a1"].current_activity == "Second"

    def test_current_activity_included_in_to_dict(self):
        """current_activity field appears in serialized output."""
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "tool_start", "span_id": "s2",
            "data": {"agent_id": "a1", "tool": "Bash", "summary": "Building"},
        })
        result = state.to_dict()
        node = next(n for n in result["nodes"] if n["agent_id"] == "a1")
        assert node["current_activity"] == "Building"

    def test_current_activity_null_in_to_dict_by_default(self):
        """current_activity defaults to null in serialized output."""
        state = self._make_state_with_running_agent()
        result = state.to_dict()
        node = next(n for n in result["nodes"] if n["agent_id"] == "a1")
        assert node["current_activity"] is None

    def test_tool_start_on_completed_agent_still_sets_activity(self):
        """tool_start does not check node status — it sets activity even on completed agents.

        Note: this documents current behavior. set_activity() rejects
        non-running agents, but process_event(tool_start) does not.
        """
        state = self._make_state_with_running_agent()
        # Mark agent as completed
        state.process_event({
            "event": "agent_end", "span_id": "s1",
            "data": {"exit_code": 0, "duration_ms": 1000},
        })
        assert state.nodes["a1"].status == "completed"
        # tool_start still modifies it
        state.process_event({
            "event": "tool_start", "span_id": "s3",
            "data": {"agent_id": "a1", "tool": "Bash", "summary": "Late arrival"},
        })
        assert state.nodes["a1"].current_activity == "Late arrival"


class TestTreeStateSetActivity:
    """Tests for the set_activity() method used by log-based fallback."""

    def test_set_activity_on_running_agent(self):
        state = TreeState()
        state.load_session_json({
            "agents": {"a1": {"role": "impl", "runtime": "cc", "parent": None}},
        })
        assert state.set_activity("a1", "Reading file") is True
        assert state.nodes["a1"].current_activity == "Reading file"

    def test_set_activity_returns_false_when_unchanged(self):
        state = TreeState()
        state.load_session_json({
            "agents": {"a1": {"role": "impl", "runtime": "cc", "parent": None}},
        })
        state.set_activity("a1", "Reading file")
        assert state.set_activity("a1", "Reading file") is False

    def test_set_activity_returns_false_for_unknown_agent(self):
        state = TreeState()
        assert state.set_activity("nonexistent", "something") is False

    def test_set_activity_returns_false_for_non_running_agent(self):
        state = TreeState()
        state.load_session_json({
            "agents": {"a1": {"role": "impl", "runtime": "cc", "parent": None}},
        })
        state.nodes["a1"].status = "completed"
        assert state.set_activity("a1", "Reading file") is False

    def test_set_activity_clears_with_none(self):
        state = TreeState()
        state.load_session_json({
            "agents": {"a1": {"role": "impl", "runtime": "cc", "parent": None}},
        })
        state.set_activity("a1", "Reading file")
        assert state.set_activity("a1", None) is True
        assert state.nodes["a1"].current_activity is None

    def test_set_activity_clears_activity_action(self):
        """set_activity (log-fallback) clears activity_action since it has no type info."""
        state = TreeState()
        state.load_session_json({
            "agents": {"a1": {"role": "impl", "runtime": "cc", "parent": None}},
        })
        state.nodes["a1"].activity_action = "Read"
        state.set_activity("a1", "Doing something")
        assert state.nodes["a1"].activity_action is None


class TestComposeActivity:
    """Tests for the _compose_activity helper."""

    def test_action_only(self):
        assert _compose_activity("Think", "", "") == "Think"

    def test_action_and_target(self):
        assert _compose_activity("Read", "src/app.ts", "") == "Read src/app.ts"

    def test_action_target_detail(self):
        assert _compose_activity("Read", "src/app.ts", "lines 1-50") == "Read src/app.ts (lines 1-50)"

    def test_empty_action_returns_none(self):
        assert _compose_activity("", "target", "detail") is None

    def test_truncates_long_result(self):
        long_target = "x" * 200
        result = _compose_activity("Read", long_target, "")
        assert len(result) <= 121  # 120 + "…"
        assert result.endswith("…")


class TestTreeStateActivityUpdate:
    """Tests for activity_update event handling in TreeState."""

    def _make_state_with_running_agent(self, agent_id="a1"):
        """Helper: create a TreeState with one running agent."""
        state = TreeState()
        state.process_event({
            "event": "delegate_start", "span_id": "s1",
            "parent_span": None, "data": {"role": "impl"},
        })
        state.process_event({
            "event": "agent_spawn", "span_id": "s1", "ts": "T1",
            "data": {"agent_id": agent_id, "runtime": "cc", "pid": 1},
        })
        return state

    def test_activity_update_sets_current_activity(self):
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "a1", "action": "Read", "target": "src/app.ts", "detail": ""},
        })
        assert state.nodes["a1"].current_activity == "Read src/app.ts"

    def test_activity_update_sets_activity_action(self):
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "a1", "action": "Bash", "target": "npm test"},
        })
        assert state.nodes["a1"].activity_action == "Bash"

    def test_activity_update_with_detail(self):
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "a1", "action": "Read", "target": "file.ts", "detail": "lines 1-50"},
        })
        assert state.nodes["a1"].current_activity == "Read file.ts (lines 1-50)"

    def test_activity_update_action_only(self):
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "a1", "action": "Think"},
        })
        assert state.nodes["a1"].current_activity == "Think"
        assert state.nodes["a1"].activity_action == "Think"

    def test_activity_update_empty_action_sets_none(self):
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "a1", "action": ""},
        })
        assert state.nodes["a1"].current_activity is None
        assert state.nodes["a1"].activity_action is None

    @patch("strawpot_gui.sse.time")
    def test_debounce_drops_rapid_events(self, mock_time):
        mock_time.monotonic.side_effect = [1.0, 1.3]  # 300ms apart
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "a1", "action": "Read", "target": "file1.ts"},
        })
        state.process_event({
            "event": "activity_update", "span_id": "s3",
            "data": {"agent_id": "a1", "action": "Write", "target": "file2.ts"},
        })
        # Second event dropped — still shows first
        assert state.nodes["a1"].current_activity == "Read file1.ts"
        assert state.nodes["a1"].activity_action == "Read"

    @patch("strawpot_gui.sse.time")
    def test_debounce_accepts_after_threshold(self, mock_time):
        mock_time.monotonic.side_effect = [1.0, 1.6]  # 600ms apart
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "a1", "action": "Read", "target": "file1.ts"},
        })
        state.process_event({
            "event": "activity_update", "span_id": "s3",
            "data": {"agent_id": "a1", "action": "Write", "target": "file2.ts"},
        })
        assert state.nodes["a1"].current_activity == "Write file2.ts"
        assert state.nodes["a1"].activity_action == "Write"

    def test_activity_update_unknown_agent_ignored(self):
        state = TreeState()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "nonexistent", "action": "Read"},
        })
        assert "nonexistent" not in state.nodes

    def test_activity_update_empty_agent_ignored(self):
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "", "action": "Read"},
        })
        assert state.nodes["a1"].current_activity is None

    def test_tool_end_clears_activity_action(self):
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "a1", "action": "Read", "target": "file.ts"},
        })
        assert state.nodes["a1"].activity_action == "Read"
        state.process_event({
            "event": "tool_end", "span_id": "s3",
            "data": {"agent_id": "a1", "tool": "Read"},
        })
        assert state.nodes["a1"].activity_action is None
        assert state.nodes["a1"].current_activity is None

    def test_activity_action_in_to_dict(self):
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "a1", "action": "Search", "target": "handleSubmit"},
        })
        result = state.to_dict()
        node = next(n for n in result["nodes"] if n["agent_id"] == "a1")
        assert node["activity_action"] == "Search"

    def test_activity_action_null_by_default(self):
        state = self._make_state_with_running_agent()
        result = state.to_dict()
        node = next(n for n in result["nodes"] if n["agent_id"] == "a1")
        assert node["activity_action"] is None

    def test_debounce_cleanup_on_agent_end(self):
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "a1", "action": "Read", "target": "f.ts"},
        })
        assert "a1" in state._activity_debounce
        state.process_event({
            "event": "agent_end", "span_id": "s1",
            "data": {"exit_code": 0, "duration_ms": 1000},
        })
        assert "a1" not in state._activity_debounce

    def test_debounce_cleanup_on_delegate_end(self):
        state = self._make_state_with_running_agent()
        state.process_event({
            "event": "activity_update", "span_id": "s2",
            "data": {"agent_id": "a1", "action": "Read", "target": "f.ts"},
        })
        assert "a1" in state._activity_debounce
        state.process_event({
            "event": "delegate_end", "span_id": "s1",
            "data": {"exit_code": 0, "duration_ms": 1000},
        })
        assert "a1" not in state._activity_debounce
