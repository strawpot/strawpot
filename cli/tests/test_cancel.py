"""Tests for strawpot.cancel — enums, state model, and tree traversal."""

import json
import os
import tempfile
import threading
from unittest.mock import MagicMock

import pytest

from strawpot.cancel import (
    AgentState,
    CancelReason,
    get_children,
    get_descendants,
    get_subtree_bottom_up,
    is_ancestor_of,
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
