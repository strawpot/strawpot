"""Tests for strawpot.session."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from strawpot.agents.protocol import AgentHandle, AgentResult
from strawpot.config import StrawPotConfig
from strawpot.delegation import PolicyDenied
from strawpot.isolation.protocol import IsolatedEnv, NoneIsolator
from strawpot.session import Session, resolve_isolator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_role(base, slug, body="Role body.", description="test"):
    d = os.path.join(base, "roles", slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "ROLE.md"), "w") as f:
        f.write(
            f"---\nname: {slug}\ndescription: {description}\n---\n{body}\n"
        )
    return d


def _make_config(**overrides):
    return StrawPotConfig(**overrides)


def _mock_runtime():
    runtime = MagicMock()
    runtime.name = "mock_runtime"
    runtime.spawn.return_value = AgentHandle(
        agent_id="agent_test", runtime_name="mock_runtime", pid=999
    )
    runtime.wait.return_value = AgentResult(summary="Done")
    runtime.attach.return_value = None
    return runtime


def _mock_wrapper():
    wrapper = MagicMock()
    wrapper.name = "mock_wrapper"
    wrapper.spawn.return_value = AgentHandle(
        agent_id="agent_sub", runtime_name="mock_wrapper", pid=888
    )
    wrapper.wait.return_value = AgentResult(
        summary="Sub done", output="ok", exit_code=0
    )
    wrapper.is_alive.return_value = False
    return wrapper


def _mock_isolator():
    isolator = MagicMock()
    isolator.create.return_value = IsolatedEnv(path=tempfile.gettempdir())
    isolator.cleanup.return_value = None
    return isolator


def _make_resolved(tmp_path, slug="orchestrator", body="You orchestrate."):
    role_path = _write_role(str(tmp_path / "registry"), slug, body)
    return {
        "slug": slug,
        "kind": "role",
        "version": "1.0",
        "path": role_path,
        "source": "local",
        "dependencies": [],
    }


def _make_session(tmp_path, **overrides):
    """Create a Session with sensible defaults for testing."""
    resolved = _make_resolved(tmp_path)
    defaults = {
        "config": _make_config(),
        "wrapper": _mock_wrapper(),
        "runtime": _mock_runtime(),
        "isolator": _mock_isolator(),
        "resolve_role": lambda slug, kind="role": resolved,
        "resolve_role_dirs": lambda s: None,
    }
    defaults.update(overrides)
    return Session(**defaults)


# ---------------------------------------------------------------------------
# resolve_isolator
# ---------------------------------------------------------------------------


class TestResolveIsolator:
    def test_none(self):
        isolator = resolve_isolator("none")
        assert isinstance(isolator, NoneIsolator)

    def test_worktree(self):
        from strawpot.isolation.worktree import WorktreeIsolator

        isolator = resolve_isolator("worktree")
        assert isinstance(isolator, WorktreeIsolator)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown isolation"):
            resolve_isolator("docker")


# ---------------------------------------------------------------------------
# Session init
# ---------------------------------------------------------------------------


class TestSessionInit:
    def test_stores_config(self, tmp_path):
        config = _make_config(runtime="test_runtime")
        session = _make_session(tmp_path, config=config)
        assert session.config.runtime == "test_runtime"

    def test_stores_isolator(self, tmp_path):
        isolator = _mock_isolator()
        session = _make_session(tmp_path, isolator=isolator)
        assert session.isolator is isolator


# ---------------------------------------------------------------------------
# Start flow
# ---------------------------------------------------------------------------


class TestStartFlow:
    @patch("strawpot.session.DenDenServer")
    def test_creates_isolation_env(self, mock_server_cls, tmp_path):
        """start() calls isolator.create with correct args."""
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        isolator.create.assert_called_once()
        call_kwargs = isolator.create.call_args.kwargs
        assert call_kwargs["base_dir"] == str(tmp_path)
        assert call_kwargs["session_id"].startswith("run_")

    @patch("strawpot.session.DenDenServer")
    def test_starts_denden_server(self, mock_server_cls, tmp_path):
        """start() creates and starts a DenDenServer."""
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        mock_server_cls.assert_called_once()
        server_instance = mock_server_cls.return_value
        server_instance.on_delegate.assert_called_once()
        server_instance.on_ask_user.assert_called_once()

    @patch("strawpot.session.DenDenServer")
    def test_spawns_orchestrator(self, mock_server_cls, tmp_path):
        """start() spawns the orchestrator with interactive mode (task='')."""
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime
        )

        session.start(str(tmp_path))

        runtime.spawn.assert_called_once()
        kw = runtime.spawn.call_args.kwargs
        assert kw["task"] == ""
        assert "PERMISSION_MODE" in kw["env"]
        assert "DENDEN_ADDR" in kw["env"]
        assert "DENDEN_AGENT_ID" in kw["env"]
        assert "DENDEN_RUN_ID" in kw["env"]

    @patch("strawpot.session.DenDenServer")
    def test_writes_session_file(self, mock_server_cls, tmp_path):
        """start() writes session state JSON file."""
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        # File is removed during stop(), so check session_data was built
        assert session._session_data["isolation"] == "none"
        assert session._session_data["runtime"] == "claude_code"
        assert "agents" in session._session_data

    @patch("strawpot.session.DenDenServer")
    def test_attaches_to_orchestrator(self, mock_server_cls, tmp_path):
        """start() calls runtime.attach() which blocks."""
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime
        )

        session.start(str(tmp_path))

        runtime.attach.assert_called_once()


# ---------------------------------------------------------------------------
# Stop / cleanup
# ---------------------------------------------------------------------------


class TestStop:
    @patch("strawpot.session.DenDenServer")
    def test_stops_denden_server(self, mock_server_cls, tmp_path):
        """stop() stops the denden gRPC server."""
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        # The server's internal _server.stop should have been called
        server_instance = mock_server_cls.return_value
        if server_instance._server:
            server_instance._server.stop.assert_called()

    @patch("strawpot.session.DenDenServer")
    def test_calls_isolator_cleanup(self, mock_server_cls, tmp_path):
        """stop() calls isolator.cleanup()."""
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        isolator.cleanup.assert_called_once()

    @patch("strawpot.session.DenDenServer")
    def test_removes_session_dir(self, mock_server_cls, tmp_path):
        """stop() removes the entire session directory."""
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        # After stop, session directory should be removed
        session_dir = os.path.join(
            str(tmp_path), ".strawpot", "sessions", session._run_id
        )
        assert not os.path.exists(session_dir)


# ---------------------------------------------------------------------------
# Delegate handler
# ---------------------------------------------------------------------------


class TestHandleDelegate:
    def _make_denden_request(
        self,
        delegate_to="implementer",
        task_text="Do something",
        agent_id="agent_orch",
        run_id="run_test",
    ):
        """Create a mock denden protobuf request."""
        request = MagicMock()
        request.request_id = "req_123"
        request.delegate.delegate_to = delegate_to
        request.delegate.task.text = task_text
        request.trace.agent_instance_id = agent_id
        request.trace.run_id = run_id
        request.WhichOneof.return_value = "delegate"
        return request

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.ok_response")
    def test_successful_delegation(
        self, mock_ok, mock_handle, tmp_path
    ):
        """Successful delegation returns ok_response."""
        from strawpot.delegation import DelegateResult

        mock_handle.return_value = DelegateResult(
            summary="Task done", output="output", exit_code=0
        )
        mock_ok.return_value = "ok"

        session = _make_session(tmp_path)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        result = session._handle_delegate(self._make_denden_request())

        mock_handle.assert_called_once()
        mock_ok.assert_called_once()
        assert result == "ok"

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.denied_response")
    def test_policy_denied(self, mock_denied, mock_handle, tmp_path):
        """PolicyDenied returns denied_response."""
        mock_handle.side_effect = PolicyDenied("DENY_ROLE_NOT_ALLOWED")
        mock_denied.return_value = "denied"

        session = _make_session(tmp_path)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        result = session._handle_delegate(self._make_denden_request())

        mock_denied.assert_called_once()
        assert result == "denied"

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.error_response")
    def test_error_returns_error_response(
        self, mock_error, mock_handle, tmp_path
    ):
        """Unexpected error returns error_response."""
        mock_handle.side_effect = RuntimeError("something broke")
        mock_error.return_value = "error"

        session = _make_session(tmp_path)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        result = session._handle_delegate(self._make_denden_request())

        mock_error.assert_called_once()
        assert result == "error"


# ---------------------------------------------------------------------------
# Ask user handler
# ---------------------------------------------------------------------------


class TestHandleAskUser:
    @patch("strawpot.session.error_response")
    def test_returns_not_implemented(self, mock_error, tmp_path):
        """ask_user returns NOT_IMPLEMENTED error for now."""
        mock_error.return_value = "not_impl"

        session = _make_session(tmp_path)
        request = MagicMock()
        request.request_id = "req_456"

        result = session._handle_ask_user(request)

        mock_error.assert_called_once_with(
            "req_456", "NOT_IMPLEMENTED", "ask_user is not yet implemented"
        )
        assert result == "not_impl"


# ---------------------------------------------------------------------------
# Agent tracking
# ---------------------------------------------------------------------------


class TestAgentTracking:
    def test_register_agent(self, tmp_path):
        session = _make_session(tmp_path)
        session._register_agent(
            "agent_1", role="implementer", parent_id="agent_0", pid=123
        )

        assert "agent_1" in session._agent_info
        assert session._agent_info["agent_1"]["role"] == "implementer"
        assert session._agent_info["agent_1"]["parent"] == "agent_0"
        assert session._agent_info["agent_1"]["pid"] == 123

    def test_agent_role(self, tmp_path):
        session = _make_session(tmp_path)
        session._register_agent(
            "agent_1", role="reviewer", parent_id=None
        )
        assert session._agent_role("agent_1") == "reviewer"
        assert session._agent_role("unknown") == "unknown"

    def test_agent_depth_root(self, tmp_path):
        """Root agent (no parent) has depth 0."""
        session = _make_session(tmp_path)
        session._register_agent(
            "agent_root", role="orchestrator", parent_id=None
        )
        assert session._agent_depth("agent_root") == 0

    def test_agent_depth_nested(self, tmp_path):
        """Nested agent depth is calculated from parent chain."""
        session = _make_session(tmp_path)
        session._register_agent(
            "agent_0", role="orchestrator", parent_id=None
        )
        session._register_agent(
            "agent_1", role="implementer", parent_id="agent_0"
        )
        session._register_agent(
            "agent_2", role="reviewer", parent_id="agent_1"
        )
        assert session._agent_depth("agent_0") == 0
        assert session._agent_depth("agent_1") == 1
        assert session._agent_depth("agent_2") == 2


# ---------------------------------------------------------------------------
# Session state file
# ---------------------------------------------------------------------------


class TestSessionStateFile:
    def test_session_data_structure(self, tmp_path):
        """Session data has the required fields."""
        session = _make_session(tmp_path)
        session._working_dir = str(tmp_path)
        session._run_id = "run_test123"
        session._env = IsolatedEnv(path=str(tmp_path))
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None, pid=42
        )
        session._write_session_file()

        data = session._session_data
        assert data["run_id"] == "run_test123"
        assert data["working_dir"] == str(tmp_path)
        assert data["isolation"] == "none"
        assert data["runtime"] == "claude_code"
        assert "pid" in data
        assert "started_at" in data
        assert "agents" in data
        assert "agent_orch" in data["agents"]

    def test_session_file_written_to_disk(self, tmp_path):
        """Session file is written as valid JSON at session_dir/session.json."""
        session = _make_session(tmp_path)
        session._working_dir = str(tmp_path)
        session._run_id = "run_disk"
        session._env = IsolatedEnv(path=str(tmp_path))
        session._write_session_file()

        assert os.path.isfile(session._session_file)
        expected_path = os.path.join(
            str(tmp_path), ".strawpot", "sessions", "run_disk", "session.json"
        )
        assert session._session_file == expected_path
        with open(session._session_file) as f:
            data = json.load(f)
        assert data["run_id"] == "run_disk"

    def test_worktree_info_included(self, tmp_path):
        """Worktree info is included when env has a branch."""
        session = _make_session(tmp_path)
        session._working_dir = str(tmp_path)
        session._run_id = "run_wt"
        wt_path = str(tmp_path / "worktree")
        session._env = IsolatedEnv(
            path=wt_path, branch="strawpot/run_wt"
        )
        session._write_session_file()

        data = session._session_data
        assert data["worktree"] == wt_path
        assert data["worktree_branch"] == "strawpot/run_wt"

    def test_remove_session_dir(self, tmp_path):
        """_remove_session_dir removes the entire session directory."""
        session = _make_session(tmp_path)
        session._working_dir = str(tmp_path)
        session._run_id = "run_rm"
        session._env = IsolatedEnv(path=str(tmp_path))
        session._write_session_file()

        session_dir = os.path.join(
            str(tmp_path), ".strawpot", "sessions", "run_rm"
        )
        assert os.path.isdir(session_dir)
        session._remove_session_dir()
        assert not os.path.exists(session_dir)
