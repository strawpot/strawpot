"""Tests for strawpot.cancel — enums and state model."""

import json
import os
import tempfile
import threading
from unittest.mock import MagicMock

import pytest

from strawpot.cancel import AgentState, CancelReason


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
