"""Integration tests for cascading cancel — validates the full cancel flow
across the state model, tree traversal, cancel engine, file-based signal
protocol, and session watcher.

These tests use mock agents (no real subprocesses) to test the cancel flow
end-to-end within a single process.
"""

import json
import os
import signal
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from strawpot.cancel import (
    AgentState,
    CancelReason,
    cancel_dir,
    get_descendants,
    get_subtree_bottom_up,
    mark_signal_done,
    read_cancel_signals,
    write_cancel_signal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(tmp_path):
    """Create a minimal Session for integration testing."""
    from strawpot.agents.protocol import AgentHandle, AgentResult
    from strawpot.config import StrawPotConfig
    from strawpot.isolation.protocol import NoneIsolator
    from strawpot.session import Session

    config = StrawPotConfig(memory="")
    runtime = MagicMock()
    runtime.name = "mock_runtime"
    handle = AgentHandle(agent_id="orch", runtime_name="mock_runtime", pid=999)
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
    session._run_id = "run_test"
    session._working_dir = str(tmp_path)
    os.makedirs(
        os.path.join(str(tmp_path), ".strawpot", "sessions", "run_test"),
        exist_ok=True,
    )
    return session


def _register_tree(session, agents):
    """Register a tree of agents. agents is a list of (id, role, parent, pid)."""
    for aid, role, parent, pid in agents:
        session._register_agent(aid, role, parent_id=parent, pid=pid)


# ---------------------------------------------------------------------------
# Scenario 1: Cancel single leaf agent
# ---------------------------------------------------------------------------


class TestCancelSingleAgent:
    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_cancel_leaf_preserves_parent(self, mock_kill, mock_alive, tmp_path):
        session = _make_session(tmp_path)
        _register_tree(session, [
            ("orch", "orchestrator", None, 100),
            ("impl", "implementer", "orch", 200),
            ("rev", "reviewer", "orch", 300),
        ])

        cancelled = session.cancel_agent("impl")
        assert cancelled == ["impl"]
        assert session._agent_info["impl"]["state"] == AgentState.CANCELLED
        # Parent and sibling untouched
        assert session._agent_info["orch"]["state"] == AgentState.RUNNING
        assert session._agent_info["rev"]["state"] == AgentState.RUNNING


# ---------------------------------------------------------------------------
# Scenario 2: Cancel agent with descendants (bottom-up order)
# ---------------------------------------------------------------------------


class TestCancelWithDescendants:
    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_bottom_up_cancel_order(self, mock_kill, mock_alive, tmp_path):
        session = _make_session(tmp_path)
        _register_tree(session, [
            ("orch", "orchestrator", None, 100),
            ("planner", "planner", "orch", 200),
            ("executor", "executor", "planner", 300),
        ])

        cancelled = session.cancel_agent("planner")
        # executor (leaf) first, then planner
        assert cancelled == ["executor", "planner"]
        assert session._agent_info["executor"]["state"] == AgentState.CANCELLED
        assert session._agent_info["planner"]["state"] == AgentState.CANCELLED
        # Orchestrator untouched
        assert session._agent_info["orch"]["state"] == AgentState.RUNNING


# ---------------------------------------------------------------------------
# Scenario 3: Cancel entire run (from orchestrator)
# ---------------------------------------------------------------------------


class TestCancelEntireRun:
    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_cancel_all_agents(self, mock_kill, mock_alive, tmp_path):
        session = _make_session(tmp_path)
        _register_tree(session, [
            ("orch", "orchestrator", None, 100),
            ("a1", "worker", "orch", 200),
            ("a2", "worker", "orch", 300),
            ("a3", "coder", "a1", 400),
        ])

        cancelled = session.cancel_agent("orch")
        assert set(cancelled) == {"orch", "a1", "a2", "a3"}
        for aid in ("orch", "a1", "a2", "a3"):
            assert session._agent_info[aid]["state"] == AgentState.CANCELLED


# ---------------------------------------------------------------------------
# Scenario 4: Force cancel
# ---------------------------------------------------------------------------


class TestForceCancel:
    @patch("strawpot.session.is_pid_alive", return_value=True)
    @patch("strawpot.session.kill_process_tree")
    def test_force_skips_graceful(self, mock_kill, mock_alive, tmp_path):
        session = _make_session(tmp_path)
        _register_tree(session, [("a1", "worker", None, 100)])

        with patch("os.kill") as mock_os_kill:
            cancelled = session.cancel_agent("a1", force=True)

        assert cancelled == ["a1"]
        # SIGINT should NOT have been sent (force mode)
        mock_os_kill.assert_not_called()
        # kill_process_tree should have been called
        mock_kill.assert_called()


# ---------------------------------------------------------------------------
# Scenario 5: Cancel already-exited agent
# ---------------------------------------------------------------------------


class TestCancelAlreadyExited:
    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_completed_agent_not_killed(self, mock_kill, mock_alive, tmp_path):
        session = _make_session(tmp_path)
        _register_tree(session, [("a1", "worker", None, 100)])
        session._update_agent_state("a1", AgentState.COMPLETED)

        cancelled = session.cancel_agent("a1")
        assert cancelled == ["a1"]
        # State should remain COMPLETED, not change to CANCELLED
        mock_kill.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 6: Cancel reason propagation
# ---------------------------------------------------------------------------


class TestCancelReasonPropagation:
    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_reason_assignment(self, mock_kill, mock_alive, tmp_path):
        session = _make_session(tmp_path)
        _register_tree(session, [
            ("root", "orch", None, 100),
            ("child", "worker", "root", 200),
            ("grandchild", "coder", "child", 300),
        ])

        session.cancel_agent("root", reason=CancelReason.USER)
        assert session._agent_info["root"]["cancel_reason"] == CancelReason.USER
        assert session._agent_info["child"]["cancel_reason"] == CancelReason.PARENT
        assert session._agent_info["grandchild"]["cancel_reason"] == CancelReason.ANCESTOR


# ---------------------------------------------------------------------------
# Scenario 7: File-based cancel signal round-trip
# ---------------------------------------------------------------------------


class TestFileSignalRoundTrip:
    def test_write_read_process_done(self, tmp_path):
        session_dir = str(tmp_path / "session")
        os.makedirs(session_dir)

        # 1. Write signal
        path = write_cancel_signal(session_dir, "agent-x", force=True)
        assert path.exists()

        # 2. Read signals
        signals = read_cancel_signals(session_dir)
        assert len(signals) == 1
        assert signals[0]["agent_id"] == "agent-x"
        assert signals[0]["force"] is True

        # 3. Mark done
        mark_signal_done(signals[0]["_path"])

        # 4. No more pending signals
        assert read_cancel_signals(session_dir) == []

        # 5. .done file exists
        done_file = str(path).replace(".json", ".done")
        assert os.path.exists(done_file)


# ---------------------------------------------------------------------------
# Scenario 8: Session.json state persistence through cancel
# ---------------------------------------------------------------------------


class TestStatePersistenceThroughCancel:
    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_disk_state_matches_memory(self, mock_kill, mock_alive, tmp_path):
        session = _make_session(tmp_path)
        _register_tree(session, [
            ("orch", "orchestrator", None, 100),
            ("a1", "worker", "orch", 200),
        ])
        session._write_session_file()

        session.cancel_agent("orch")

        # Read back from disk
        session_file = os.path.join(
            str(tmp_path), ".strawpot", "sessions", "run_test", "session.json"
        )
        with open(session_file) as f:
            data = json.load(f)

        # Verify disk matches memory
        assert data["agents"]["orch"]["state"] == "cancelled"
        assert data["agents"]["a1"]["state"] == "cancelled"
        assert data["agents"]["orch"]["cancel_reason"] == "user"
        assert data["agents"]["a1"]["cancel_reason"] == "parent"


# ---------------------------------------------------------------------------
# Scenario 9: Session listing with status filters after cancel
# ---------------------------------------------------------------------------


class TestListingAfterCancel:
    @patch("strawpot.session.is_pid_alive", return_value=False)
    @patch("strawpot.session.kill_process_tree")
    def test_filter_cancelled_agents(self, mock_kill, mock_alive, tmp_path):
        session = _make_session(tmp_path)
        _register_tree(session, [
            ("orch", "orchestrator", None, 100),
            ("a1", "worker", "orch", 200),
            ("a2", "reviewer", "orch", 300),
        ])

        # Cancel only a1
        session.cancel_agent("a1")

        # Filter cancelled
        cancelled = [
            aid for aid, info in session._agent_info.items()
            if info.get("state") == AgentState.CANCELLED
        ]
        assert cancelled == ["a1"]

        # Filter running
        running = [
            aid for aid, info in session._agent_info.items()
            if info.get("state") == AgentState.RUNNING
        ]
        assert set(running) == {"orch", "a2"}


# ---------------------------------------------------------------------------
# Scenario 10: Tree traversal correctness
# ---------------------------------------------------------------------------


class TestTreeTraversalIntegration:
    def test_complex_tree_cancel_order(self):
        """Verify bottom-up order for a complex tree:
        A -> {B -> {D, E -> F}, C -> G}
        Expected bottom-up: F, E, D, B, G, C (leaves first)
        """
        tree = {
            "A": {"parent": None},
            "B": {"parent": "A"},
            "C": {"parent": "A"},
            "D": {"parent": "B"},
            "E": {"parent": "B"},
            "F": {"parent": "E"},
            "G": {"parent": "C"},
        }
        bottom_up = get_subtree_bottom_up("A", tree)
        # F must come before E, D must come before B, G must come before C
        assert bottom_up.index("F") < bottom_up.index("E")
        assert bottom_up.index("D") < bottom_up.index("B")
        assert bottom_up.index("E") < bottom_up.index("B")
        assert bottom_up.index("G") < bottom_up.index("C")
        # All descendants present
        assert set(bottom_up) == {"B", "C", "D", "E", "F", "G"}
