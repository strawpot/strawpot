"""Tests for strawpot.cancel — enums, state model, and tree traversal."""

import json
import os
import signal
import tempfile
import threading
from unittest.mock import MagicMock, patch

import pytest

from strawpot.cancel import (
    AgentState,
    CancelReason,
    cancel_dir,
    get_children,
    get_descendants,
    get_subtree_bottom_up,
    is_ancestor_of,
    mark_signal_done,
    read_cancel_signals,
    write_cancel_signal,
)


# ---------------------------------------------------------------------------
# Enum basics
# ---------------------------------------------------------------------------


class TestAgentState:
    """AgentState enum values and serialization."""

    def test_values(self):
        assert AgentState.RUNNING == "running"
        assert AgentState.CANCELLING == "cancelling"
        assert AgentState.CANCELLED == "cancelled"
        assert AgentState.COMPLETED == "completed"
        assert AgentState.FAILED == "failed"

    def test_str_serialization(self):
        """StrEnum values serialize naturally to JSON strings."""
        data = {"state": AgentState.RUNNING}
        encoded = json.dumps(data)
        decoded = json.loads(encoded)
        assert decoded["state"] == "running"

    def test_membership(self):
        assert "running" in [s.value for s in AgentState]
        assert "cancelled" in [s.value for s in AgentState]

    def test_all_states_present(self):
        assert len(AgentState) == 5


class TestCancelReason:
    """CancelReason enum values and serialization."""

    def test_values(self):
        assert CancelReason.USER == "user"
        assert CancelReason.PARENT == "parent"
        assert CancelReason.ANCESTOR == "ancestor"
        assert CancelReason.TIMEOUT == "timeout"

    def test_str_serialization(self):
        data = {"cancel_reason": CancelReason.PARENT}
        encoded = json.dumps(data)
        decoded = json.loads(encoded)
        assert decoded["cancel_reason"] == "parent"

    def test_all_reasons_present(self):
        assert len(CancelReason) == 4


# ---------------------------------------------------------------------------
# State integration with session agent tracking
# ---------------------------------------------------------------------------


class TestAgentStateInSession:
    """Verify state field integration with session._agent_info."""

    def _make_session(self, tmp_path):
        """Create a minimal Session for testing agent state tracking."""
        from strawpot.agents.protocol import AgentHandle, AgentResult
        from strawpot.config import StrawPotConfig
        from strawpot.isolation.protocol import IsolatedEnv, NoneIsolator
        from strawpot.session import Session

        config = StrawPotConfig(memory="")
        runtime = MagicMock()
        runtime.name = "mock_runtime"
        runtime.spawn.return_value = AgentHandle(
            agent_id="orch", runtime_name="mock_runtime", pid=999
        )
        runtime.wait.return_value = AgentResult(summary="Done")
        wrapper = MagicMock()
        wrapper.name = "mock_wrapper"

        session = Session(
            config=config,
            runtime=runtime,
            wrapper=wrapper,
            isolator=NoneIsolator(),
            resolve_role=MagicMock(return_value={}),
            resolve_role_dirs=MagicMock(return_value=None),
            task="test task",
        )
        # Set up minimal internal state so _register_agent and
        # _write_session_file work.
        session._run_id = "test-run-id"
        session._working_dir = str(tmp_path)
        os.makedirs(
            os.path.join(str(tmp_path), ".strawpot", "sessions", "test-run-id"),
            exist_ok=True,
        )
        return session

    def test_register_sets_running_state(self, tmp_path):
        session = self._make_session(tmp_path)
        session._register_agent("agent-1", "worker", parent_id=None)
        info = session._agent_info["agent-1"]
        assert info["state"] == AgentState.RUNNING
        assert info["state"] == "running"

    def test_update_agent_state(self, tmp_path):
        session = self._make_session(tmp_path)
        session._register_agent("agent-1", "worker", parent_id=None)

        session._update_agent_state("agent-1", AgentState.COMPLETED)
        assert session._agent_info["agent-1"]["state"] == AgentState.COMPLETED
        assert "cancel_reason" not in session._agent_info["agent-1"]

    def test_update_agent_state_with_cancel_reason(self, tmp_path):
        session = self._make_session(tmp_path)
        session._register_agent("agent-1", "worker", parent_id=None)

        session._update_agent_state(
            "agent-1", AgentState.CANCELLED, cancel_reason=CancelReason.USER
        )
        info = session._agent_info["agent-1"]
        assert info["state"] == AgentState.CANCELLED
        assert info["cancel_reason"] == CancelReason.USER

    def test_update_unknown_agent_is_noop(self, tmp_path):
        session = self._make_session(tmp_path)
        # Should not raise
        session._update_agent_state("nonexistent", AgentState.CANCELLED)

    def test_state_transitions(self, tmp_path):
        """Verify typical state machine transitions."""
        session = self._make_session(tmp_path)
        session._register_agent("agent-1", "worker", parent_id=None)

        # RUNNING -> CANCELLING -> CANCELLED
        assert session._agent_info["agent-1"]["state"] == AgentState.RUNNING
        session._update_agent_state(
            "agent-1", AgentState.CANCELLING, cancel_reason=CancelReason.USER
        )
        assert session._agent_info["agent-1"]["state"] == AgentState.CANCELLING
        session._update_agent_state("agent-1", AgentState.CANCELLED)
        assert session._agent_info["agent-1"]["state"] == AgentState.CANCELLED

    def test_state_persisted_to_session_json(self, tmp_path):
        session = self._make_session(tmp_path)
        session._register_agent("agent-1", "worker", parent_id=None)
        session._write_session_file()

        session_file = os.path.join(
            str(tmp_path), ".strawpot", "sessions", "test-run-id", "session.json"
        )
        with open(session_file) as f:
            data = json.load(f)

        agent_data = data["agents"]["agent-1"]
        assert agent_data["state"] == "running"

    def test_state_update_writes_to_disk(self, tmp_path):
        session = self._make_session(tmp_path)
        session._register_agent("agent-1", "worker", parent_id=None)
        session._write_session_file()

        session._update_agent_state("agent-1", AgentState.COMPLETED)

        session_file = os.path.join(
            str(tmp_path), ".strawpot", "sessions", "test-run-id", "session.json"
        )
        with open(session_file) as f:
            data = json.load(f)

        assert data["agents"]["agent-1"]["state"] == "completed"

    def test_failed_state_on_nonzero_exit(self, tmp_path):
        """Verify FAILED state is set for non-zero exit code."""
        session = self._make_session(tmp_path)
        session._register_agent("agent-1", "worker", parent_id=None)

        # Simulate delegation completion with non-zero exit
        session._update_agent_state("agent-1", AgentState.FAILED)
        assert session._agent_info["agent-1"]["state"] == AgentState.FAILED


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    """CLI agents command should handle old session files without state field."""

    def test_missing_state_field_falls_back_to_pid(self):
        """Agent info without 'state' key should not break display logic."""
        # Old-style agent info (no state field)
        old_info = {
            "role": "worker",
            "runtime": "claude_code",
            "parent": None,
            "started_at": "2026-01-01T00:00:00Z",
            "pid": None,
        }
        # The CLI uses info.get("state") — should be None for old format
        status = old_info.get("state")
        assert status is None  # Falls back to PID check in CLI code


# ---------------------------------------------------------------------------
# cancel_agent() — cascading cancellation
# ---------------------------------------------------------------------------


class TestCancelAgent:
    """Tests for Session.cancel_agent() cascading cancel."""

    def _make_session(self, tmp_path):
        """Create a minimal Session for testing cancel."""
        from strawpot.agents.protocol import AgentHandle, AgentResult
        from strawpot.config import StrawPotConfig
        from strawpot.isolation.protocol import NoneIsolator
        from strawpot.session import Session

        config = StrawPotConfig(memory="")
        runtime = MagicMock()
        runtime.name = "mock_runtime"
        runtime.spawn.return_value = AgentHandle(
            agent_id="orch", runtime_name="mock_runtime", pid=999
        )
        runtime.wait.return_value = AgentResult(summary="Done")
        wrapper = MagicMock()
        wrapper.name = "mock_wrapper"

        session = Session(
            config=config,
            runtime=runtime,
            wrapper=wrapper,
            isolator=NoneIsolator(),
            resolve_role=MagicMock(return_value={}),
            resolve_role_dirs=MagicMock(return_value=None),
            task="test task",
        )
        session._run_id = "test-run-id"
        session._working_dir = str(tmp_path)
        os.makedirs(
            os.path.join(str(tmp_path), ".strawpot", "sessions", "test-run-id"),
            exist_ok=True,
        )
        return session

    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_cancel_single_agent_no_pid(self, mock_kill, mock_alive, tmp_path):
        """Cancel an agent that has no live process."""
        session = self._make_session(tmp_path)
        session._register_agent("a1", "worker", parent_id=None, pid=None)

        result = session.cancel_agent("a1")
        assert result == ["a1"]
        assert session._agent_info["a1"]["state"] == AgentState.CANCELLED
        assert session._agent_info["a1"]["cancel_reason"] == CancelReason.USER
        mock_kill.assert_not_called()

    @patch("strawpot.session.is_pid_alive", return_value=True)
    @patch("strawpot.session.kill_process_tree")
    def test_cancel_single_agent_force(self, mock_kill, mock_alive, tmp_path):
        """Force cancel skips graceful interrupt."""
        session = self._make_session(tmp_path)
        session._register_agent("a1", "worker", parent_id=None, pid=12345)

        result = session.cancel_agent("a1", force=True)
        assert result == ["a1"]
        assert session._agent_info["a1"]["state"] == AgentState.CANCELLED
        mock_kill.assert_called()

    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_cancel_cascades_to_children(self, mock_kill, mock_alive, tmp_path):
        """Cancel propagates to all descendants."""
        session = self._make_session(tmp_path)
        session._register_agent("a1", "worker", parent_id=None)
        session._register_agent("a2", "reviewer", parent_id="a1")
        session._register_agent("a3", "coder", parent_id="a2")

        result = session.cancel_agent("a1")
        # Bottom-up order: a3 first, then a2, then a1
        assert result == ["a3", "a2", "a1"]
        assert session._agent_info["a1"]["state"] == AgentState.CANCELLED
        assert session._agent_info["a2"]["state"] == AgentState.CANCELLED
        assert session._agent_info["a3"]["state"] == AgentState.CANCELLED

    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_cancel_reason_propagation(self, mock_kill, mock_alive, tmp_path):
        """Direct children get PARENT reason, deeper get ANCESTOR."""
        session = self._make_session(tmp_path)
        session._register_agent("a1", "worker", parent_id=None)
        session._register_agent("a2", "reviewer", parent_id="a1")
        session._register_agent("a3", "coder", parent_id="a2")

        session.cancel_agent("a1", reason=CancelReason.USER)
        assert session._agent_info["a1"]["cancel_reason"] == CancelReason.USER
        assert session._agent_info["a2"]["cancel_reason"] == CancelReason.PARENT
        assert session._agent_info["a3"]["cancel_reason"] == CancelReason.ANCESTOR

    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_already_completed_agent_still_in_result(self, mock_kill, mock_alive, tmp_path):
        """Agents that already exited are included but not killed."""
        session = self._make_session(tmp_path)
        session._register_agent("a1", "worker", parent_id=None, pid=100)
        session._update_agent_state("a1", AgentState.COMPLETED)

        result = session.cancel_agent("a1")
        assert result == ["a1"]
        # State stays COMPLETED (already terminal)
        mock_kill.assert_not_called()

    @patch("strawpot.session.is_pid_alive")
    @patch("strawpot.session.kill_process_tree")
    @patch("os.kill")
    def test_graceful_then_force(self, mock_os_kill, mock_tree_kill, mock_alive, tmp_path):
        """Graceful interrupt sent first, then force kill after timeout."""
        # is_pid_alive returns True consistently (agent doesn't exit gracefully)
        mock_alive.return_value = True
        session = self._make_session(tmp_path)
        session._register_agent("a1", "worker", parent_id=None, pid=12345)

        result = session.cancel_agent("a1", timeout=0.2)
        assert result == ["a1"]
        # SIGINT should have been sent
        mock_os_kill.assert_called_with(12345, signal.SIGINT)
        # Force kill should follow since agent didn't exit
        mock_tree_kill.assert_called()
        assert session._agent_info["a1"]["state"] == AgentState.CANCELLED

    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_cancel_wide_tree(self, mock_kill, mock_alive, tmp_path):
        """Cancel a parent with multiple children."""
        session = self._make_session(tmp_path)
        session._register_agent("root", "orch", parent_id=None)
        session._register_agent("c1", "worker", parent_id="root")
        session._register_agent("c2", "worker", parent_id="root")
        session._register_agent("c3", "worker", parent_id="root")

        result = session.cancel_agent("root")
        assert set(result) == {"root", "c1", "c2", "c3"}
        # Root should be last
        assert result[-1] == "root"

    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_cancel_deep_tree(self, mock_kill, mock_alive, tmp_path):
        """Cancel a deep tree (4 levels)."""
        session = self._make_session(tmp_path)
        session._register_agent("L0", "orch", parent_id=None)
        session._register_agent("L1", "planner", parent_id="L0")
        session._register_agent("L2", "executor", parent_id="L1")
        session._register_agent("L3", "coder", parent_id="L2")

        result = session.cancel_agent("L0")
        assert result == ["L3", "L2", "L1", "L0"]

    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_cancel_nonexistent_agent(self, mock_kill, mock_alive, tmp_path):
        """Cancelling a nonexistent agent returns empty list."""
        session = self._make_session(tmp_path)
        result = session.cancel_agent("nonexistent")
        assert result == []

    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_state_persisted_after_cancel(self, mock_kill, mock_alive, tmp_path):
        """session.json is updated on disk after cancel."""
        session = self._make_session(tmp_path)
        session._register_agent("a1", "worker", parent_id=None)
        session._write_session_file()

        session.cancel_agent("a1")

        session_file = os.path.join(
            str(tmp_path), ".strawpot", "sessions", "test-run-id", "session.json"
        )
        with open(session_file) as f:
            data = json.load(f)
        assert data["agents"]["a1"]["state"] == "cancelled"
        assert data["agents"]["a1"]["cancel_reason"] == "user"


# ---------------------------------------------------------------------------
# Shutdown cascade
# ---------------------------------------------------------------------------


class TestShutdownCascade:
    """Tests for _shutdown_orchestrator using cascading cancel."""

    def _make_session(self, tmp_path):
        from strawpot.agents.protocol import AgentHandle, AgentResult
        from strawpot.config import StrawPotConfig
        from strawpot.isolation.protocol import NoneIsolator
        from strawpot.session import Session

        config = StrawPotConfig(memory="")
        runtime = MagicMock()
        runtime.name = "mock_runtime"
        handle = AgentHandle(agent_id="orch-1", runtime_name="mock_runtime", pid=999)
        runtime.spawn.return_value = handle
        runtime.wait.return_value = AgentResult(summary="Done")
        wrapper = MagicMock()
        wrapper.name = "mock_wrapper"

        session = Session(
            config=config,
            runtime=runtime,
            wrapper=wrapper,
            isolator=NoneIsolator(),
            resolve_role=MagicMock(return_value={}),
            resolve_role_dirs=MagicMock(return_value=None),
            task="test task",
        )
        session._run_id = "test-run-id"
        session._working_dir = str(tmp_path)
        session._orchestrator_handle = handle
        os.makedirs(
            os.path.join(str(tmp_path), ".strawpot", "sessions", "test-run-id"),
            exist_ok=True,
        )
        return session, runtime

    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_shutdown_uses_cascading_cancel(self, mock_kill, mock_alive, tmp_path):
        """Shutdown with registered agents uses cancel_agent, not runtime.kill."""
        session, runtime = self._make_session(tmp_path)
        session._register_agent("orch-1", "orchestrator", parent_id=None, pid=999)
        session._register_agent("sub-1", "worker", parent_id="orch-1", pid=888)

        session._shutdown_orchestrator()

        assert session._shutting_down is True
        # cancel_agent was used — not runtime.kill
        runtime.kill.assert_not_called()
        # Both agents should be cancelled
        assert session._agent_info["orch-1"]["state"] == AgentState.CANCELLED
        assert session._agent_info["sub-1"]["state"] == AgentState.CANCELLED

    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_shutdown_force_mode(self, mock_kill, mock_alive, tmp_path):
        """Force shutdown skips graceful interrupt."""
        session, runtime = self._make_session(tmp_path)
        session._register_agent("orch-1", "orchestrator", parent_id=None, pid=999)

        session._shutdown_orchestrator(force=True)

        assert session._shutting_down is True
        assert session._agent_info["orch-1"]["state"] == AgentState.CANCELLED

    def test_shutdown_falls_back_to_kill(self, tmp_path):
        """Without agent tracking, falls back to runtime.kill."""
        session, runtime = self._make_session(tmp_path)
        # Don't register any agents — orch_id not in _agent_info

        session._shutdown_orchestrator()

        assert session._shutting_down is True
        runtime.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Stale session recovery with agent PIDs
# ---------------------------------------------------------------------------


class TestStaleRecoveryAgents:
    """Tests for stale session recovery killing remaining agent PIDs."""

    @patch("strawpot.session.kill_process_tree")
    @patch("strawpot.session.is_pid_alive")
    def test_stale_recovery_kills_agent_pids(self, mock_alive, mock_kill, tmp_path):
        """Stale session recovery should kill agent PIDs that are still alive."""
        from strawpot.config import StrawPotConfig
        from strawpot.session import recover_stale_sessions

        run_id = "run_test123"
        sessions_dir = tmp_path / ".strawpot" / "sessions" / run_id
        running_dir = tmp_path / ".strawpot" / "running"
        sessions_dir.mkdir(parents=True)
        running_dir.mkdir(parents=True)
        # Create symlink
        os.symlink(str(sessions_dir), str(running_dir / run_id))

        session_data = {
            "run_id": run_id,
            "working_dir": str(tmp_path),
            "pid": 11111,
            "isolation": "none",
            "agents": {
                "agent-a": {"pid": 22222, "role": "worker"},
                "agent-b": {"pid": 33333, "role": "reviewer"},
                "agent-c": {"pid": None, "role": "planner"},
            },
        }
        with open(sessions_dir / "session.json", "w") as f:
            json.dump(session_data, f)

        # Session PID is dead, agent PIDs are alive
        def pid_alive(pid):
            return pid in (22222, 33333)

        mock_alive.side_effect = pid_alive

        config = StrawPotConfig(memory="")
        recovered = recover_stale_sessions(str(tmp_path), config)

        assert run_id in recovered
        # Should have tried to kill the two alive agent PIDs
        mock_kill.assert_any_call(22222)
        mock_kill.assert_any_call(33333)
        assert mock_kill.call_count == 2


# ---------------------------------------------------------------------------
# Tree traversal utilities
# ---------------------------------------------------------------------------

# Test tree shapes:
#
# LINEAR:      A -> B -> C -> D
# WIDE:        A -> {B, C, D}
# MIXED:       A -> {B -> {D, E}, C -> F}
# SINGLE:      A (no children)
# EMPTY:       {} (empty dict)


def _linear_tree():
    """A -> B -> C -> D"""
    return {
        "A": {"parent": None},
        "B": {"parent": "A"},
        "C": {"parent": "B"},
        "D": {"parent": "C"},
    }


def _wide_tree():
    """A -> {B, C, D}"""
    return {
        "A": {"parent": None},
        "B": {"parent": "A"},
        "C": {"parent": "A"},
        "D": {"parent": "A"},
    }


def _mixed_tree():
    """A -> {B -> {D, E}, C -> F}"""
    return {
        "A": {"parent": None},
        "B": {"parent": "A"},
        "C": {"parent": "A"},
        "D": {"parent": "B"},
        "E": {"parent": "B"},
        "F": {"parent": "C"},
    }


class TestGetChildren:
    def test_linear_chain(self):
        tree = _linear_tree()
        assert get_children("A", tree) == ["B"]
        assert get_children("B", tree) == ["C"]
        assert get_children("D", tree) == []

    def test_wide_tree(self):
        tree = _wide_tree()
        children = get_children("A", tree)
        assert set(children) == {"B", "C", "D"}

    def test_mixed_tree(self):
        tree = _mixed_tree()
        assert set(get_children("B", tree)) == {"D", "E"}
        assert get_children("C", tree) == ["F"]

    def test_no_children(self):
        tree = _linear_tree()
        assert get_children("D", tree) == []

    def test_missing_agent(self):
        tree = _linear_tree()
        assert get_children("NONEXISTENT", tree) == []

    def test_empty_tree(self):
        assert get_children("A", {}) == []


class TestGetDescendants:
    def test_linear_chain(self):
        tree = _linear_tree()
        desc = get_descendants("A", tree)
        assert desc == ["B", "C", "D"]

    def test_wide_tree(self):
        tree = _wide_tree()
        desc = get_descendants("A", tree)
        assert set(desc) == {"B", "C", "D"}

    def test_mixed_tree(self):
        tree = _mixed_tree()
        desc = get_descendants("A", tree)
        assert set(desc) == {"B", "C", "D", "E", "F"}
        # BFS order: level 1 (B, C) before level 2 (D, E, F)
        b_idx = desc.index("B")
        d_idx = desc.index("D")
        assert b_idx < d_idx  # Parent before child in BFS

    def test_leaf_node(self):
        tree = _linear_tree()
        assert get_descendants("D", tree) == []

    def test_missing_agent(self):
        tree = _linear_tree()
        assert get_descendants("NONEXISTENT", tree) == []

    def test_subtree(self):
        tree = _mixed_tree()
        assert set(get_descendants("B", tree)) == {"D", "E"}

    def test_empty_tree(self):
        assert get_descendants("A", {}) == []


class TestGetSubtreeBottomUp:
    def test_linear_chain(self):
        tree = _linear_tree()
        bottom_up = get_subtree_bottom_up("A", tree)
        assert bottom_up == ["D", "C", "B"]

    def test_mixed_tree_leaves_first(self):
        tree = _mixed_tree()
        bottom_up = get_subtree_bottom_up("A", tree)
        # Leaves (D, E, F) must come before their parents (B, C)
        assert set(bottom_up) == {"B", "C", "D", "E", "F"}
        for leaf in ["D", "E"]:
            assert bottom_up.index(leaf) < bottom_up.index("B")
        assert bottom_up.index("F") < bottom_up.index("C")

    def test_wide_tree(self):
        tree = _wide_tree()
        bottom_up = get_subtree_bottom_up("A", tree)
        assert set(bottom_up) == {"B", "C", "D"}

    def test_does_not_include_root(self):
        tree = _linear_tree()
        bottom_up = get_subtree_bottom_up("A", tree)
        assert "A" not in bottom_up

    def test_leaf_returns_empty(self):
        tree = _linear_tree()
        assert get_subtree_bottom_up("D", tree) == []


class TestIsAncestorOf:
    def test_direct_parent(self):
        tree = _linear_tree()
        assert is_ancestor_of("A", "B", tree) is True

    def test_grandparent(self):
        tree = _linear_tree()
        assert is_ancestor_of("A", "D", tree) is True

    def test_not_ancestor(self):
        tree = _linear_tree()
        assert is_ancestor_of("D", "A", tree) is False

    def test_self_is_not_ancestor(self):
        tree = _linear_tree()
        assert is_ancestor_of("A", "A", tree) is False

    def test_sibling_not_ancestor(self):
        tree = _wide_tree()
        assert is_ancestor_of("B", "C", tree) is False

    def test_missing_agent(self):
        tree = _linear_tree()
        assert is_ancestor_of("NONEXISTENT", "A", tree) is False
        assert is_ancestor_of("A", "NONEXISTENT", tree) is False

    def test_mixed_tree(self):
        tree = _mixed_tree()
        assert is_ancestor_of("A", "F", tree) is True
        assert is_ancestor_of("C", "F", tree) is True
        assert is_ancestor_of("B", "F", tree) is False

    def test_cycle_protection(self):
        """Cycles in parent chain should not cause infinite loops."""
        cyclic = {
            "A": {"parent": "B"},
            "B": {"parent": "A"},
        }
        # Should terminate (return False) rather than loop forever
        assert is_ancestor_of("C", "A", cyclic) is False

    def test_missing_parent_ref(self):
        """Missing parent reference should be treated as root."""
        tree = {
            "A": {},  # No 'parent' key at all
            "B": {"parent": "A"},
        }
        assert is_ancestor_of("A", "B", tree) is True


# ---------------------------------------------------------------------------
# File-based cancel signal protocol
# ---------------------------------------------------------------------------


class TestWriteCancelSignal:
    def test_writes_agent_cancel(self, tmp_path):
        session_dir = str(tmp_path / "session")
        os.makedirs(session_dir)
        path = write_cancel_signal(session_dir, "agent-abc", force=False)
        assert path.name == "agent-abc.json"
        with open(path) as f:
            data = json.load(f)
        assert data["agent_id"] == "agent-abc"
        assert data["force"] is False
        assert data["requested_by"] == "cli"
        assert "requested_at" in data

    def test_writes_run_cancel(self, tmp_path):
        session_dir = str(tmp_path / "session")
        os.makedirs(session_dir)
        path = write_cancel_signal(session_dir, None, force=True, requested_by="gui")
        assert path.name == "_run.json"
        with open(path) as f:
            data = json.load(f)
        assert data["agent_id"] is None
        assert data["force"] is True
        assert data["requested_by"] == "gui"

    def test_atomic_write(self, tmp_path):
        """No partial files left behind."""
        session_dir = str(tmp_path / "session")
        os.makedirs(session_dir)
        write_cancel_signal(session_dir, "a1")
        cdir = cancel_dir(session_dir)
        files = os.listdir(cdir)
        assert all(not f.endswith(".tmp") for f in files)


class TestReadCancelSignals:
    def test_reads_pending_signals(self, tmp_path):
        session_dir = str(tmp_path / "session")
        write_cancel_signal(session_dir, "a1", force=False)
        write_cancel_signal(session_dir, "a2", force=True)
        signals = read_cancel_signals(session_dir)
        assert len(signals) == 2
        agent_ids = {s["agent_id"] for s in signals}
        assert agent_ids == {"a1", "a2"}
        # Each signal should have _path
        assert all("_path" in s for s in signals)

    def test_empty_dir_returns_empty(self, tmp_path):
        session_dir = str(tmp_path / "session")
        os.makedirs(cancel_dir(session_dir))
        assert read_cancel_signals(session_dir) == []

    def test_missing_dir_returns_empty(self, tmp_path):
        assert read_cancel_signals(str(tmp_path / "nonexistent")) == []

    def test_skips_done_files(self, tmp_path):
        session_dir = str(tmp_path / "session")
        path = write_cancel_signal(session_dir, "a1")
        mark_signal_done(str(path))
        # .done file should not be read
        signals = read_cancel_signals(session_dir)
        assert len(signals) == 0

    def test_skips_malformed_files(self, tmp_path):
        session_dir = str(tmp_path / "session")
        cdir = cancel_dir(session_dir)
        os.makedirs(cdir)
        with open(os.path.join(cdir, "bad.json"), "w") as f:
            f.write("not valid json{{{")
        signals = read_cancel_signals(session_dir)
        assert len(signals) == 0


class TestMarkSignalDone:
    def test_renames_to_done(self, tmp_path):
        session_dir = str(tmp_path / "session")
        path = write_cancel_signal(session_dir, "a1")
        mark_signal_done(str(path))
        assert not path.exists()
        done_path = str(path).replace(".json", ".done")
        assert os.path.exists(done_path)
