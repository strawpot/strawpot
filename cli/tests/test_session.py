"""Tests for strawpot.session."""

import json
import os
import tempfile
import threading
from unittest.mock import MagicMock, call, patch

import pytest

from denden.gen import denden_pb2
from strawpot.agents.protocol import AgentHandle, AgentResult
from strawpot.config import StrawPotConfig
from strawpot.delegation import PolicyDenied
from strawpot.isolation.protocol import IsolatedEnv, NoneIsolator
from strawpot.session import (
    AskUserRequest,
    AskUserResponse,
    Session,
    _boost_by_importance,
    _extract_session_recap,
    _track_recall,
    recover_stale_sessions,
)
from strawpot_memory.memory_protocol import RecallEntry, RecallResult, RememberResult


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
    overrides.setdefault("memory", "")
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


def _write_stale_session(tmp_path, run_id, **overrides):
    """Write a session.json file with the given run_id and a dead PID.

    Also creates a ``running/<run_id>`` symlink so
    ``recover_stale_sessions`` can discover the session.
    """
    session_dir = os.path.join(
        str(tmp_path), ".strawpot", "sessions", run_id
    )
    os.makedirs(session_dir, exist_ok=True)
    data = {
        "run_id": run_id,
        "working_dir": str(tmp_path),
        "runtime": "strawpot-claude-code",
        "denden_addr": "127.0.0.1:9700",
        "started_at": "2026-01-01T00:00:00+00:00",
        "pid": 99999999,  # almost certainly dead
        "agents": {},
    }
    data.update(overrides)
    with open(os.path.join(session_dir, "session.json"), "w") as f:
        json.dump(data, f)
    # Create running/ symlink at .strawpot/running/
    running_dir = os.path.join(str(tmp_path), ".strawpot", "running")
    os.makedirs(running_dir, exist_ok=True)
    os.symlink(os.path.join("..", "sessions", run_id), os.path.join(running_dir, run_id))
    return session_dir


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
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
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
        """start() creates and starts a DenDenServer via start() (non-blocking)."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        mock_server_cls.assert_called_once()
        server_instance = mock_server_cls.return_value
        server_instance.on_delegate.assert_called_once()
        server_instance.on_ask_user.assert_called_once()
        server_instance.start.assert_called_once()

    @patch("strawpot.session.DenDenServer")
    def test_spawns_orchestrator(self, mock_server_cls, tmp_path):
        """start() spawns the orchestrator with interactive mode (task='')."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
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
        assert kw["env"]["STRAWPOT_ROLE"] == "ai-ceo"

    @patch("strawpot.session.DenDenServer")
    def test_writes_session_file(self, mock_server_cls, tmp_path):
        """start() writes session state JSON file."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        # File is removed during stop(), so check session_data was built
        assert session._session_data["runtime"] == "strawpot-claude-code"
        assert "agents" in session._session_data

    @patch("strawpot.session.DenDenServer")
    def test_attaches_to_orchestrator(self, mock_server_cls, tmp_path):
        """start() calls runtime.attach() which blocks."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime
        )

        session.start(str(tmp_path))

        runtime.attach.assert_called_once()

    @patch("strawpot.session.DenDenServer")
    def test_always_uses_port_zero(self, mock_server_cls, tmp_path):
        """Server always uses port 0 (OS-assigned) to avoid port collisions."""
        server = MagicMock()
        server.bound_addr = "127.0.0.1:54321"
        mock_server_cls.return_value = server

        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        assert mock_server_cls.call_count == 1
        assert mock_server_cls.call_args == ({"addr": "127.0.0.1:0"},)
        assert session._denden_addr == "127.0.0.1:54321"

    @patch("strawpot.session.DenDenServer")
    def test_actual_addr_in_orchestrator_env(self, mock_server_cls, tmp_path):
        """Orchestrator env receives actual bound addr, not config addr."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:54321"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        session = _make_session(tmp_path, isolator=isolator, runtime=runtime)

        session.start(str(tmp_path))

        kw = runtime.spawn.call_args.kwargs
        assert kw["env"]["DENDEN_ADDR"] == "127.0.0.1:54321"

    @patch("strawpot.session.DenDenServer")
    def test_actual_addr_in_session_file(self, mock_server_cls, tmp_path):
        """Session file stores actual bound addr, not config addr."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:54321"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        assert session._session_data["denden_addr"] == "127.0.0.1:54321"


# ---------------------------------------------------------------------------
# Stop / cleanup
# ---------------------------------------------------------------------------


class TestStop:
    @patch("strawpot.session.DenDenServer")
    def test_stops_denden_server(self, mock_server_cls, tmp_path):
        """stop() stops the denden gRPC server via public stop() method."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        server_instance = mock_server_cls.return_value
        server_instance.stop.assert_called_once_with(grace=5)

    @patch("strawpot.session.DenDenServer")
    def test_calls_isolator_cleanup(self, mock_server_cls, tmp_path):
        """stop() calls isolator.cleanup()."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        isolator.cleanup.assert_called_once()

    @patch("strawpot.session.DenDenServer")
    def test_archives_session_dir(self, mock_server_cls, tmp_path):
        """stop() swaps running symlink to archive symlink."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        session = _make_session(tmp_path, isolator=isolator)

        session.start(str(tmp_path))

        strawpot_dir = os.path.join(str(tmp_path), ".strawpot")
        # Session dir stays in place
        session_dir = os.path.join(strawpot_dir, "sessions", session._run_id)
        assert os.path.isdir(session_dir)
        # Running symlink removed, archive symlink created
        assert not os.path.islink(os.path.join(strawpot_dir, "running", session._run_id))
        assert os.path.islink(os.path.join(strawpot_dir, "archive", session._run_id))


# ---------------------------------------------------------------------------
# stop() cleanup
# ---------------------------------------------------------------------------


class TestStopCleanup:
    def test_stop_calls_isolator_cleanup(self, tmp_path):
        """stop() calls isolator.cleanup when env is set."""
        session = _make_session(tmp_path)
        session._working_dir = str(tmp_path)
        session._run_id = "run_cleanup"
        session._env = IsolatedEnv(path=str(tmp_path))

        session.stop()

        session.isolator.cleanup.assert_called_once()


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
            output="output", exit_code=0
        )
        mock_ok.return_value = "ok"

        session = _make_session(tmp_path)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._denden_addr = "127.0.0.1:9700"
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        result = session._handle_delegate(self._make_denden_request())

        mock_handle.assert_called_once()
        mock_ok.assert_called_once()
        assert result == "ok"

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.ok_response")
    def test_empty_delegate_to_resolves_to_own_role(
        self, mock_ok, mock_handle, tmp_path
    ):
        """Empty delegateTo resolves to the agent's own role (self-delegation)."""
        from strawpot.delegation import DelegateResult

        mock_handle.return_value = DelegateResult(
            output="output", exit_code=0
        )
        mock_ok.return_value = "ok"

        session = _make_session(tmp_path)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._denden_addr = "127.0.0.1:9700"
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        # delegateTo is empty string — should resolve to "orchestrator"
        result = session._handle_delegate(
            self._make_denden_request(delegate_to="")
        )

        call_kwargs = mock_handle.call_args.kwargs
        assert call_kwargs["request"].role_slug == "orchestrator"
        assert result == "ok"

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.ok_response")
    def test_passes_denden_addr_to_handle_delegate(
        self, mock_ok, mock_handle, tmp_path
    ):
        """_handle_delegate passes actual denden_addr to handle_delegate()."""
        from strawpot.delegation import DelegateResult

        mock_handle.return_value = DelegateResult(
            output="ok", exit_code=0
        )
        mock_ok.return_value = "ok"

        session = _make_session(tmp_path)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._denden_addr = "127.0.0.1:54321"
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        session._handle_delegate(self._make_denden_request())

        call_kwargs = mock_handle.call_args.kwargs
        assert call_kwargs["denden_addr"] == "127.0.0.1:54321"

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
        session._denden_addr = "127.0.0.1:9700"
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
        session._denden_addr = "127.0.0.1:9700"
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        result = session._handle_delegate(self._make_denden_request())

        mock_error.assert_called_once()
        assert result == "error"

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.error_response")
    def test_nonzero_exit_returns_error_response(
        self, mock_error, mock_handle, tmp_path
    ):
        """Non-zero exit_code from sub-agent returns error_response."""
        from strawpot.delegation import DelegateResult

        mock_handle.return_value = DelegateResult(
            output="traceback...", exit_code=1
        )
        mock_error.return_value = "error"

        session = _make_session(tmp_path)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._denden_addr = "127.0.0.1:9700"
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        result = session._handle_delegate(self._make_denden_request())

        mock_error.assert_called_once_with(
            "req_123",
            "ERR_SUBAGENT_NONZERO_EXIT",
            "Sub-agent exited with code 1\n\nAgent output:\ntraceback...",
        )
        assert result == "error"


# ---------------------------------------------------------------------------
# Ask user handler
# ---------------------------------------------------------------------------


class TestHandleAskUser:
    @patch("strawpot.session.ok_response")
    def test_default_handler_auto_responds(self, mock_ok, tmp_path):
        """Default ask_user handler returns auto-response."""
        mock_ok.return_value = "ok"

        session = _make_session(tmp_path)
        request = MagicMock()
        request.request_id = "req_456"
        request.ask_user.question = "which db?"
        request.ask_user.choices = ["postgres", "sqlite"]
        request.ask_user.default_value = ""
        request.ask_user.why = ""
        request.ask_user.response_format = ""

        result = session._handle_ask_user(request)

        mock_ok.assert_called_once()
        call_kwargs = mock_ok.call_args
        assert call_kwargs[0][0] == "req_456"
        assert result == "ok"

    @patch("strawpot.session.ok_response")
    def test_default_handler_uses_default_value(self, mock_ok, tmp_path):
        """Default handler returns default_value when provided."""
        mock_ok.return_value = "ok"

        session = _make_session(tmp_path)
        request = MagicMock()
        request.request_id = "req_789"
        request.ask_user.question = "which db?"
        request.ask_user.choices = []
        request.ask_user.default_value = "postgres"
        request.ask_user.why = ""
        request.ask_user.response_format = ""

        session._handle_ask_user(request)

        call_kwargs = mock_ok.call_args
        ask_result = call_kwargs[1]["ask_user_result"]
        assert ask_result.text == "postgres"

    @patch("strawpot.session.ok_response")
    def test_custom_handler(self, mock_ok, tmp_path):
        """Custom ask_user handler is called when provided."""
        mock_ok.return_value = "ok"

        def custom_handler(req: AskUserRequest) -> AskUserResponse:
            return AskUserResponse(text=f"custom: {req.question}")

        session = _make_session(tmp_path, ask_user_handler=custom_handler)
        request = MagicMock()
        request.request_id = "req_abc"
        request.ask_user.question = "pick one"
        request.ask_user.choices = ["a", "b"]
        request.ask_user.default_value = ""
        request.ask_user.why = ""
        request.ask_user.response_format = ""

        session._handle_ask_user(request)

        call_kwargs = mock_ok.call_args
        ask_result = call_kwargs[1]["ask_user_result"]
        assert ask_result.text == "custom: pick one"

    @patch("strawpot.session.ok_response")
    def test_passes_all_fields_to_handler(self, mock_ok, tmp_path):
        """Handler receives all protobuf fields via AskUserRequest."""
        mock_ok.return_value = "ok"
        received = {}

        def capture_handler(req: AskUserRequest) -> AskUserResponse:
            received["question"] = req.question
            received["choices"] = req.choices
            received["default_value"] = req.default_value
            received["why"] = req.why
            received["response_format"] = req.response_format
            return AskUserResponse(text="ok")

        session = _make_session(tmp_path, ask_user_handler=capture_handler)
        request = MagicMock()
        request.request_id = "req_fields"
        request.ask_user.question = "which db?"
        request.ask_user.choices = ["pg", "sqlite"]
        request.ask_user.default_value = "pg"
        request.ask_user.why = "need to pick a database"
        request.ask_user.response_format = "text"

        session._handle_ask_user(request)

        assert received["question"] == "which db?"
        assert received["choices"] == ["pg", "sqlite"]
        assert received["default_value"] == "pg"
        assert received["why"] == "need to pick a database"
        assert received["response_format"] == "text"

    @patch("strawpot.session.error_response")
    def test_handler_exception_returns_error(self, mock_error, tmp_path):
        """If the handler raises, return an error response."""
        mock_error.return_value = "err"

        def failing_handler(req: AskUserRequest) -> AskUserResponse:
            raise RuntimeError("handler broke")

        session = _make_session(tmp_path, ask_user_handler=failing_handler)
        request = MagicMock()
        request.request_id = "req_fail"
        request.ask_user.question = "test"
        request.ask_user.choices = []
        request.ask_user.default_value = ""
        request.ask_user.why = ""
        request.ask_user.response_format = ""

        result = session._handle_ask_user(request)

        mock_error.assert_called_once_with(
            "req_fail", "ERR_ASK_USER", "handler broke"
        )
        assert result == "err"


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
        assert data["runtime"] == "strawpot-claude-code"
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

    def test_archive_session_dir(self, tmp_path):
        """_archive_session_dir swaps running symlink for archive symlink."""
        session = _make_session(tmp_path)
        session._working_dir = str(tmp_path)
        session._run_id = "run_rm"
        session._env = IsolatedEnv(path=str(tmp_path))
        session._write_session_file()

        strawpot_dir = os.path.join(str(tmp_path), ".strawpot")
        session_dir = os.path.join(strawpot_dir, "sessions", "run_rm")
        running_link = os.path.join(strawpot_dir, "running", "run_rm")
        assert os.path.isdir(session_dir)
        assert os.path.islink(running_link)

        session._archive_session_dir()

        # Session dir stays in place
        assert os.path.isdir(session_dir)
        assert os.path.isfile(os.path.join(session_dir, "session.json"))
        # Running symlink removed, archive symlink created
        assert not os.path.islink(running_link)
        archive_link = os.path.join(strawpot_dir, "archive", "run_rm")
        assert os.path.islink(archive_link)
        assert os.path.isdir(archive_link)


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------


class TestRecoverStaleSessions:
    def test_no_sessions_dir(self, tmp_path):
        """No .strawpot/sessions/ directory — returns empty list."""
        result = recover_stale_sessions(str(tmp_path), _make_config())
        assert result == []

    def test_empty_sessions_dir(self, tmp_path):
        """Empty sessions directory — returns empty list."""
        os.makedirs(os.path.join(str(tmp_path), ".strawpot", "sessions"))
        result = recover_stale_sessions(str(tmp_path), _make_config())
        assert result == []

    def test_stale_session_archived(self, tmp_path):
        """Stale session swaps running→archive symlink."""
        session_dir = _write_stale_session(tmp_path, "run_stale1")

        result = recover_stale_sessions(str(tmp_path), _make_config())

        assert result == ["run_stale1"]
        # Session dir stays in place
        assert os.path.isdir(session_dir)
        # Running symlink removed, archive symlink created
        strawpot_dir = os.path.join(str(tmp_path), ".strawpot")
        assert not os.path.islink(os.path.join(strawpot_dir, "running", "run_stale1"))
        assert os.path.islink(os.path.join(strawpot_dir, "archive", "run_stale1"))

    def test_running_session_skipped(self, tmp_path):
        """Session with a live PID is not recovered."""
        session_dir = _write_stale_session(
            tmp_path, "run_alive", pid=os.getpid()
        )

        result = recover_stale_sessions(str(tmp_path), _make_config())

        assert result == []
        assert os.path.exists(session_dir)

    def test_different_working_dir_skipped(self, tmp_path):
        """Session from a different project directory is skipped."""
        session_dir = _write_stale_session(
            tmp_path, "run_other", working_dir="/some/other/project"
        )

        result = recover_stale_sessions(str(tmp_path), _make_config())

        assert result == []
        assert os.path.exists(session_dir)

    def test_corrupt_session_json_skipped(self, tmp_path):
        """Corrupt session.json is skipped without crashing."""
        strawpot_dir = os.path.join(str(tmp_path), ".strawpot")
        session_dir = os.path.join(strawpot_dir, "sessions", "run_corrupt")
        os.makedirs(session_dir, exist_ok=True)
        with open(os.path.join(session_dir, "session.json"), "w") as f:
            f.write("NOT JSON")
        # Create running/ symlink so it's discovered
        running_dir = os.path.join(strawpot_dir, "running")
        os.makedirs(running_dir, exist_ok=True)
        os.symlink(os.path.join("..", "sessions", "run_corrupt"), os.path.join(running_dir, "run_corrupt"))

        result = recover_stale_sessions(str(tmp_path), _make_config())

        assert result == []

    def test_multiple_stale_sessions(self, tmp_path):
        """Multiple stale sessions are all archived."""
        dir1 = _write_stale_session(tmp_path, "run_a")
        dir2 = _write_stale_session(tmp_path, "run_b")

        result = recover_stale_sessions(str(tmp_path), _make_config())

        assert sorted(result) == ["run_a", "run_b"]
        # Session dirs stay in place
        assert os.path.isdir(dir1)
        assert os.path.isdir(dir2)
        # Archive symlinks created
        archive = os.path.join(str(tmp_path), ".strawpot", "archive")
        assert os.path.islink(os.path.join(archive, "run_a"))
        assert os.path.islink(os.path.join(archive, "run_b"))

    def test_archive_dir_skipped_during_scan(self, tmp_path):
        """Archived sessions (only in archive/) are not re-recovered."""
        # Create a real stale session with running/ symlink
        _write_stale_session(tmp_path, "run_real")
        # Create an already-archived session (no running/ symlink)
        strawpot_dir = os.path.join(str(tmp_path), ".strawpot")
        old_dir = os.path.join(strawpot_dir, "sessions", "run_old")
        os.makedirs(old_dir, exist_ok=True)
        with open(os.path.join(old_dir, "session.json"), "w") as f:
            json.dump({"run_id": "run_old", "working_dir": str(tmp_path), "pid": 1}, f)
        archive_dir = os.path.join(strawpot_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        os.symlink(os.path.join("..", "sessions", "run_old"), os.path.join(archive_dir, "run_old"))

        result = recover_stale_sessions(str(tmp_path), _make_config())

        # Only the session with a running/ symlink is recovered
        assert result == ["run_real"]


# ---------------------------------------------------------------------------
# Remember handler
# ---------------------------------------------------------------------------


class TestHandleRemember:
    def _make_denden_request(
        self,
        content="important fact",
        keywords=None,
        scope="project",
        agent_id="agent_orch",
        run_id="run_test",
    ):
        """Create a mock denden protobuf request with remember payload."""
        request = MagicMock()
        request.request_id = "req_rem_1"
        request.remember.content = content
        request.remember.keywords = keywords or ["kw1"]
        request.remember.scope = scope
        request.trace.agent_instance_id = agent_id
        request.trace.run_id = run_id
        request.WhichOneof.return_value = "remember"
        return request

    @patch("strawpot.session.error_response")
    def test_no_memory_provider(self, mock_error, tmp_path):
        """Session with no memory provider returns error_response."""
        mock_error.return_value = "err"

        session = _make_session(tmp_path)
        session._memory_provider = None

        result = session._handle_remember(self._make_denden_request())

        mock_error.assert_called_once_with(
            "req_rem_1", "ERR_NO_MEMORY", "no memory provider configured"
        )
        assert result == "err"

    @patch("strawpot.session.ok_response")
    def test_successful_remember(self, mock_ok, tmp_path):
        """Successful remember returns ok_response with remember_result."""
        mock_ok.return_value = "ok"

        session = _make_session(tmp_path)
        session._run_id = "run_test"
        memory = MagicMock()
        memory.remember.return_value = RememberResult(
            status="accepted", entry_id="k_1"
        )
        session._memory_provider = memory
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        result = session._handle_remember(self._make_denden_request())

        memory.remember.assert_called_once()
        mock_ok.assert_called_once()
        call_kwargs = mock_ok.call_args
        remember_result = call_kwargs[1]["remember_result"]
        assert remember_result.status == "accepted"
        assert remember_result.entry_id == "k_1"
        assert result == "ok"

    @patch("strawpot.session.error_response")
    def test_remember_exception(self, mock_error, tmp_path):
        """RuntimeError from provider returns error_response."""
        mock_error.return_value = "err"

        session = _make_session(tmp_path)
        session._run_id = "run_test"
        memory = MagicMock()
        memory.remember.side_effect = RuntimeError("disk full")
        session._memory_provider = memory
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        result = session._handle_remember(self._make_denden_request())

        mock_error.assert_called_once_with(
            "req_rem_1", "ERR_REMEMBER", "disk full"
        )
        assert result == "err"


# ---------------------------------------------------------------------------
# Recall handler
# ---------------------------------------------------------------------------


class TestHandleRecall:
    def _make_denden_request(
        self,
        query="find something",
        keywords=None,
        scope="project",
        max_results=5,
        agent_id="agent_orch",
        run_id="run_test",
    ):
        """Create a mock denden protobuf request with recall payload."""
        request = MagicMock()
        request.request_id = "req_rec_1"
        request.recall.query = query
        request.recall.keywords = keywords or ["kw1"]
        request.recall.scope = scope
        request.recall.max_results = max_results
        request.trace.agent_instance_id = agent_id
        request.trace.run_id = run_id
        request.WhichOneof.return_value = "recall"
        return request

    @patch("strawpot.session.error_response")
    def test_no_memory_provider(self, mock_error, tmp_path):
        """Session with no memory provider returns error_response."""
        mock_error.return_value = "err"

        session = _make_session(tmp_path)
        session._memory_provider = None

        result = session._handle_recall(self._make_denden_request())

        mock_error.assert_called_once_with(
            "req_rec_1", "ERR_NO_MEMORY", "no memory provider configured"
        )
        assert result == "err"

    @patch("strawpot.session.ok_response")
    def test_successful_recall(self, mock_ok, tmp_path):
        """Successful recall returns ok_response with recall_result."""
        mock_ok.return_value = "ok"

        session = _make_session(tmp_path)
        session._run_id = "run_test"
        memory = MagicMock()
        memory.recall.return_value = RecallResult(
            entries=[
                RecallEntry(
                    entry_id="e_1",
                    content="remembered fact",
                    keywords=["kw1"],
                    scope="project",
                    score=0.95,
                ),
            ]
        )
        session._memory_provider = memory
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        result = session._handle_recall(self._make_denden_request())

        memory.recall.assert_called_once()
        mock_ok.assert_called_once()
        call_kwargs = mock_ok.call_args
        recall_result = call_kwargs[1]["recall_result"]
        assert len(recall_result.entries) == 1
        assert recall_result.entries[0].entry_id == "e_1"
        assert recall_result.entries[0].content == "remembered fact"
        assert result == "ok"

    @patch("strawpot.session.error_response")
    def test_recall_exception(self, mock_error, tmp_path):
        """RuntimeError from provider returns error_response."""
        mock_error.return_value = "err"

        session = _make_session(tmp_path)
        session._run_id = "run_test"
        memory = MagicMock()
        memory.recall.side_effect = RuntimeError("db unreachable")
        session._memory_provider = memory
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        result = session._handle_recall(self._make_denden_request())

        mock_error.assert_called_once_with(
            "req_rec_1", "ERR_RECALL", "db unreachable"
        )
        assert result == "err"

    @patch("strawpot.session.ok_response")
    def test_recall_empty_results(self, mock_ok, tmp_path):
        """Empty recall results still returns ok_response."""
        mock_ok.return_value = "ok"

        session = _make_session(tmp_path)
        session._run_id = "run_test"
        memory = MagicMock()
        memory.recall.return_value = RecallResult(entries=[])
        session._memory_provider = memory
        session._register_agent(
            "agent_orch", role="orchestrator", parent_id=None
        )

        result = session._handle_recall(self._make_denden_request())

        memory.recall.assert_called_once()
        mock_ok.assert_called_once()
        call_kwargs = mock_ok.call_args
        recall_result = call_kwargs[1]["recall_result"]
        assert len(recall_result.entries) == 0
        assert result == "ok"


# ---------------------------------------------------------------------------
# Importance tracking in recall
# ---------------------------------------------------------------------------


class TestTrackRecall:
    """Tests for _track_recall helper."""

    def test_records_entry_ids(self, tmp_path):
        """Calling _track_recall persists stats to disk."""
        _track_recall(["e1", "e2"], str(tmp_path))

        from strawpot.memory.importance import load_stats

        stats = load_stats(str(tmp_path))
        assert stats["e1"].recall_count == 1
        assert stats["e2"].recall_count == 1

    @patch("strawpot.session.logger")
    def test_failure_is_silent(self, mock_logger):
        """Failures in tracking don't propagate."""
        with patch(
            "strawpot.memory.importance.record_recall",
            side_effect=OSError("disk full"),
        ):
            # Should not raise
            _track_recall(["e1"], "/nonexistent")


class TestBoostByImportance:
    """Tests for _boost_by_importance helper."""

    def test_boosts_known_entries(self, tmp_path):
        """Entries with importance stats get boosted scores."""
        import time

        from strawpot.memory.importance import EntryStats, save_stats

        now = time.time()
        save_stats(
            {"e1": EntryStats(recall_count=10, last_recalled=now, created=now - 100)},
            str(tmp_path),
        )

        result = RecallResult(
            entries=[
                RecallEntry(entry_id="e1", content="fact", score=1.0),
                RecallEntry(entry_id="e2", content="other", score=0.9),
            ]
        )

        boosted = _boost_by_importance(result, str(tmp_path))
        # e1 should be boosted, e2 should be unchanged
        assert boosted.entries[0].entry_id == "e1"
        assert boosted.entries[0].score > 1.0
        assert boosted.entries[1].score == 0.9

    def test_no_stats_preserves_order(self, tmp_path):
        """When no stats file exists, scores and order are unchanged."""
        result = RecallResult(
            entries=[
                RecallEntry(entry_id="e1", content="a", score=0.9),
                RecallEntry(entry_id="e2", content="b", score=1.0),
            ]
        )

        boosted = _boost_by_importance(result, str(tmp_path))
        # No stats → no boosting, original order preserved
        assert boosted.entries[0].entry_id == "e1"
        assert boosted.entries[0].score == 0.9
        assert boosted.entries[1].entry_id == "e2"
        assert boosted.entries[1].score == 1.0

    def test_failure_returns_original(self, tmp_path):
        """If importance loading fails, result is returned unmodified."""
        result = RecallResult(
            entries=[
                RecallEntry(entry_id="e1", content="a", score=0.5),
            ]
        )

        with patch(
            "strawpot.memory.importance.load_stats",
            side_effect=Exception("broken"),
        ):
            boosted = _boost_by_importance(result, str(tmp_path))
            assert boosted.entries[0].score == 0.5

    def test_re_sorts_by_boosted_score(self, tmp_path):
        """Boosted entries are re-sorted so higher-importance entries surface."""
        import time

        from strawpot.memory.importance import EntryStats, save_stats

        now = time.time()
        # e2 has high importance, e1 has none
        save_stats(
            {"e2": EntryStats(recall_count=50, last_recalled=now, created=now - 100)},
            str(tmp_path),
        )

        result = RecallResult(
            entries=[
                RecallEntry(entry_id="e1", content="a", score=1.0),
                RecallEntry(entry_id="e2", content="b", score=0.8),
            ]
        )

        boosted = _boost_by_importance(result, str(tmp_path))
        # e2 should be first after boost despite lower original score
        assert boosted.entries[0].entry_id == "e2"
        assert boosted.entries[0].score > 0.8

    def test_no_partial_mutation_on_computation_error(self, tmp_path):
        """If importance_score raises mid-loop, no entries are mutated (AC #2)."""
        import time

        from strawpot.memory.importance import EntryStats, save_stats

        now = time.time()
        save_stats(
            {
                "e1": EntryStats(recall_count=10, last_recalled=now, created=now),
                "e2": EntryStats(recall_count=5, last_recalled=now, created=now),
            },
            str(tmp_path),
        )

        result = RecallResult(
            entries=[
                RecallEntry(entry_id="e1", content="a", score=1.0),
                RecallEntry(entry_id="e2", content="b", score=0.9),
            ]
        )

        with patch(
            "strawpot.memory.importance.importance_score",
            side_effect=[10.0, Exception("mid-computation crash")],
        ):
            boosted = _boost_by_importance(result, str(tmp_path))
            # On exception, original result is returned unmodified
            assert boosted.entries[0].score == 1.0
            assert boosted.entries[1].score == 0.9


class TestRecallWithImportanceIntegration:
    """Integration test: _handle_recall triggers importance tracking."""

    def _make_denden_request(self, agent_id="agent_orch", run_id="run_test"):
        request = MagicMock()
        request.request_id = "req_imp_1"
        request.recall.query = "find something"
        request.recall.keywords = ["kw1"]
        request.recall.scope = "project"
        request.recall.max_results = 5
        request.trace.agent_instance_id = agent_id
        request.trace.run_id = run_id
        request.WhichOneof.return_value = "recall"
        return request

    @patch("strawpot.session._track_recall")
    @patch("strawpot.session._boost_by_importance")
    @patch("strawpot.session.ok_response")
    def test_recall_calls_tracking(self, mock_ok, mock_boost, mock_track, tmp_path):
        """Successful recall triggers both boost and tracking."""
        mock_ok.return_value = "ok"
        entries = [
            RecallEntry(entry_id="e1", content="fact", score=0.9),
        ]
        boosted_result = RecallResult(entries=entries)
        mock_boost.return_value = boosted_result

        session = _make_session(tmp_path)
        session._run_id = "run_test"
        session._working_dir = str(tmp_path)
        memory = MagicMock()
        memory.recall.return_value = RecallResult(entries=entries)
        session._memory_provider = memory
        session._register_agent("agent_orch", role="orchestrator", parent_id=None)

        session._handle_recall(self._make_denden_request())

        mock_boost.assert_called_once()
        mock_track.assert_called_once_with(["e1"], str(tmp_path))


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


class TestSignalHandling:
    """Tests for three-level Ctrl+C handling.

    By default ``_mock_runtime().interrupt()`` returns a truthy MagicMock,
    simulating interactive (tmux) mode where the interrupt is forwarded.
    Tests for direct mode explicitly set ``interrupt.return_value = False``.
    """

    # -- Interactive (tmux) mode: interrupt forwarded --

    def test_interactive_first_sigint_sets_interrupted(self, tmp_path):
        """First SIGINT sets _interrupted flag but NOT _shutting_down (tmux)."""
        runtime = _mock_runtime()
        session = _make_session(tmp_path, runtime=runtime)
        session._orchestrator_handle = runtime.spawn.return_value

        with patch("strawpot.session.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            session._handle_sigint(None, None)

        assert session._interrupted is True
        assert session._shutting_down is False

    def test_interactive_first_sigint_forwards_interrupt(self, tmp_path):
        """First SIGINT calls runtime.interrupt() — NOT kill() (tmux)."""
        runtime = _mock_runtime()
        session = _make_session(tmp_path, runtime=runtime)
        handle = runtime.spawn.return_value
        session._orchestrator_handle = handle

        with patch("strawpot.session.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            session._handle_sigint(None, None)

        runtime.interrupt.assert_called_once_with(handle)
        runtime.kill.assert_not_called()

    def test_interactive_second_sigint_within_window_shuts_down(self, tmp_path):
        """Second SIGINT within 2s kills orchestrator (tmux)."""
        runtime = _mock_runtime()
        session = _make_session(tmp_path, runtime=runtime)
        handle = runtime.spawn.return_value
        session._orchestrator_handle = handle

        with patch("strawpot.session.time") as mock_time:
            mock_time.monotonic.side_effect = [100.0, 101.0]
            session._handle_sigint(None, None)  # Level 1: interrupt
            session._handle_sigint(None, None)  # Level 2: shutdown

        assert session._shutting_down is True
        runtime.kill.assert_called_once_with(handle)

    def test_interactive_second_sigint_outside_window_reinterrupts(self, tmp_path):
        """Second SIGINT after 2s resets to Level 1 (tmux)."""
        runtime = _mock_runtime()
        session = _make_session(tmp_path, runtime=runtime)
        handle = runtime.spawn.return_value
        session._orchestrator_handle = handle

        with patch("strawpot.session.time") as mock_time:
            mock_time.monotonic.side_effect = [100.0, 103.0]
            session._handle_sigint(None, None)
            session._handle_sigint(None, None)

        assert session._interrupted is True
        assert session._shutting_down is False
        assert runtime.interrupt.call_count == 2
        runtime.kill.assert_not_called()

    def test_interactive_full_three_levels(self, tmp_path):
        """Full sequence: interrupt → shutdown → force quit (tmux)."""
        runtime = _mock_runtime()
        session = _make_session(tmp_path, runtime=runtime)
        session._orchestrator_handle = runtime.spawn.return_value

        with patch("strawpot.session.time") as mock_time:
            mock_time.monotonic.side_effect = [100.0, 101.0]
            session._handle_sigint(None, None)   # Level 1: interrupt
            session._handle_sigint(None, None)   # Level 2: shutdown

        assert session._shutting_down is True

        with patch("os._exit") as mock_exit:
            session._handle_sigint(None, None)   # Level 3: force quit

        mock_exit.assert_called_once_with(1)

    # -- Direct mode: interrupt not forwarded, escalate immediately --

    def test_direct_first_sigint_escalates_to_shutdown(self, tmp_path):
        """First SIGINT in direct mode skips interrupt and shuts down."""
        runtime = _mock_runtime()
        runtime.interrupt.return_value = False
        session = _make_session(tmp_path, runtime=runtime)
        handle = runtime.spawn.return_value
        session._orchestrator_handle = handle

        with patch("strawpot.session.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            session._handle_sigint(None, None)

        assert session._shutting_down is True
        runtime.kill.assert_called_once_with(handle)

    def test_direct_second_sigint_force_quits(self, tmp_path):
        """Second SIGINT in direct mode force-quits (only two levels)."""
        runtime = _mock_runtime()
        runtime.interrupt.return_value = False
        session = _make_session(tmp_path, runtime=runtime)
        session._orchestrator_handle = runtime.spawn.return_value

        with patch("strawpot.session.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            session._handle_sigint(None, None)   # Level 1 → shutdown

        with patch("os._exit") as mock_exit:
            session._handle_sigint(None, None)   # Level 2 → force quit

        mock_exit.assert_called_once_with(1)

    # -- Common behavior (both modes) --

    def test_first_sigint_no_orchestrator(self, tmp_path):
        """First SIGINT with no orchestrator handle does not crash."""
        session = _make_session(tmp_path)
        session._orchestrator_handle = None

        with patch("strawpot.session.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            session._handle_sigint(None, None)

        assert session._interrupted is True
        # No handle → interrupt not called → forwarded=False → shutdown
        assert session._shutting_down is True

    def test_first_sigint_interrupt_failure_escalates(self, tmp_path):
        """If runtime.interrupt() raises, escalate to shutdown."""
        runtime = _mock_runtime()
        runtime.interrupt.side_effect = RuntimeError("tmux not found")
        session = _make_session(tmp_path, runtime=runtime)
        session._orchestrator_handle = runtime.spawn.return_value

        with patch("strawpot.session.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            session._handle_sigint(None, None)

        # Exception → forwarded stays False → shutdown
        assert session._shutting_down is True

    def test_force_quit_during_shutdown(self, tmp_path):
        """SIGINT during shutdown calls os._exit(1)."""
        session = _make_session(tmp_path)
        session._shutting_down = True

        with patch("os._exit") as mock_exit:
            session._handle_sigint(None, None)

        mock_exit.assert_called_once_with(1)

    def test_shutdown_kill_failure_still_sets_flag(self, tmp_path):
        """If runtime.kill() fails during shutdown, _shutting_down is still set."""
        runtime = _mock_runtime()
        runtime.kill.side_effect = RuntimeError("tmux error")
        session = _make_session(tmp_path, runtime=runtime)
        session._orchestrator_handle = runtime.spawn.return_value

        with patch("strawpot.session.time") as mock_time:
            mock_time.monotonic.side_effect = [100.0, 101.0]
            session._handle_sigint(None, None)  # Level 1
            session._handle_sigint(None, None)  # Level 2 (kill fails)

        assert session._shutting_down is True

    @patch("strawpot.session.DenDenServer")
    def test_handler_installed_and_restored(self, mock_server_cls, tmp_path):
        """Signal handler is installed before attach and restored after stop."""
        import signal

        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime
        )

        original = signal.getsignal(signal.SIGINT)
        session.start(str(tmp_path))
        restored = signal.getsignal(signal.SIGINT)

        assert restored is original

    @patch("strawpot.session.DenDenServer")
    def test_stop_runs_after_shutdown(self, mock_server_cls, tmp_path):
        """stop() runs via finally block after shutdown kills orchestrator."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime
        )

        with patch.object(session, "stop") as mock_stop:
            session.start(str(tmp_path))

        mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# Noninteractive mode (--task)
# ---------------------------------------------------------------------------


class TestNoninteractiveMode:
    @patch("strawpot.session.DenDenServer")
    def test_spawn_receives_task(self, mock_server_cls, tmp_path):
        """spawn() receives the task string when --task is given."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime, task="fix the bug"
        )

        session.start(str(tmp_path))

        kw = runtime.spawn.call_args.kwargs
        assert kw["task"] == "fix the bug"

    @patch("strawpot.session.DenDenServer")
    def test_wait_called_instead_of_attach(self, mock_server_cls, tmp_path):
        """Noninteractive mode calls wait() instead of attach()."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime, task="do something"
        )

        session.start(str(tmp_path))

        runtime.wait.assert_called_once()
        runtime.attach.assert_not_called()

    @patch("strawpot.session.DenDenServer")
    def test_attach_called_when_no_task(self, mock_server_cls, tmp_path):
        """Interactive mode (no task) calls attach() as before."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime
        )

        session.start(str(tmp_path))

        runtime.attach.assert_called_once()
        runtime.wait.assert_not_called()

    @patch("strawpot.session.DenDenServer")
    def test_nonzero_exit_code(self, mock_server_cls, tmp_path):
        """sys.exit() is called with the agent's nonzero exit code."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        runtime.wait.return_value = AgentResult(
            summary="Failed", exit_code=1
        )
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime, task="fail"
        )

        with pytest.raises(SystemExit) as exc_info:
            session.start(str(tmp_path))

        assert exc_info.value.code == 1

    @patch("strawpot.session.DenDenServer")
    def test_zero_exit_code_no_sys_exit(self, mock_server_cls, tmp_path):
        """No sys.exit() on success (exit code 0)."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        runtime.wait.return_value = AgentResult(
            summary="Done", exit_code=0
        )
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime, task="succeed"
        )

        # Should not raise SystemExit
        session.start(str(tmp_path))

    @patch("strawpot.session.DenDenServer")
    def test_signal_handler_still_installed(self, mock_server_cls, tmp_path):
        """Signal handler is installed and restored in noninteractive mode."""
        import signal

        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime, task="a task"
        )

        original = signal.getsignal(signal.SIGINT)
        session.start(str(tmp_path))
        restored = signal.getsignal(signal.SIGINT)

        assert restored is original

    @patch("strawpot.session.DenDenServer")
    def test_stop_runs_after_task_completes(self, mock_server_cls, tmp_path):
        """stop() runs via finally block after task completion."""
        mock_server_cls.return_value.bound_addr = "127.0.0.1:9700"
        isolator = _mock_isolator()
        isolator.create.return_value = IsolatedEnv(path=str(tmp_path))
        runtime = _mock_runtime()
        session = _make_session(
            tmp_path, isolator=isolator, runtime=runtime, task="a task"
        )

        with patch.object(session, "stop") as mock_stop:
            session.start(str(tmp_path))

        mock_stop.assert_called_once()



# ---------------------------------------------------------------------------
# Max delegations per session
# ---------------------------------------------------------------------------


class TestMaxNumDelegations:
    def _make_denden_request(
        self,
        delegate_to="implementer",
        task_text="Do something",
        agent_id="agent_orch",
        run_id="run_test",
    ):
        request = MagicMock()
        request.request_id = "req_123"
        request.delegate.delegate_to = delegate_to
        request.delegate.task.text = task_text
        request.delegate.task.return_format = 0  # TEXT
        request.trace.agent_instance_id = agent_id
        request.trace.run_id = run_id
        return request

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.ok_response")
    def test_delegation_allowed_under_limit(
        self, mock_ok, mock_handle, tmp_path
    ):
        """Delegations below the limit succeed normally."""
        from strawpot.delegation import DelegateResult

        mock_handle.return_value = DelegateResult(output="ok", exit_code=0)
        mock_ok.return_value = "ok"

        config = _make_config(max_num_delegations=3)
        session = _make_session(tmp_path, config=config)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._denden_addr = "127.0.0.1:9700"
        session._register_agent("agent_orch", role="orchestrator", parent_id=None)

        result = session._handle_delegate(self._make_denden_request())
        assert result == "ok"
        assert session._delegation_count == 1

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.ok_response")
    @patch("strawpot.session.denied_response")
    def test_delegation_denied_at_limit(
        self, mock_denied, mock_ok, mock_handle, tmp_path
    ):
        """Delegations at the limit are denied without spawning."""
        from strawpot.delegation import DelegateResult

        mock_handle.return_value = DelegateResult(output="ok", exit_code=0)
        mock_ok.return_value = "ok"
        mock_denied.return_value = "denied"

        config = _make_config(max_num_delegations=2)
        session = _make_session(tmp_path, config=config)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._denden_addr = "127.0.0.1:9700"
        session._register_agent("agent_orch", role="orchestrator", parent_id=None)

        # First two succeed (different tasks to avoid cache hits)
        session._handle_delegate(self._make_denden_request(task_text="task 1"))
        session._handle_delegate(self._make_denden_request(task_text="task 2"))
        assert session._delegation_count == 2

        # Third is denied
        result = session._handle_delegate(self._make_denden_request(task_text="task 3"))
        assert result == "denied"
        mock_denied.assert_called_once()
        assert "DENY_DELEGATIONS_LIMIT" in mock_denied.call_args.args

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.ok_response")
    def test_zero_means_unlimited(self, mock_ok, mock_handle, tmp_path):
        """max_num_delegations=0 means no limit."""
        from strawpot.delegation import DelegateResult

        mock_handle.return_value = DelegateResult(output="ok", exit_code=0)
        mock_ok.return_value = "ok"

        config = _make_config(max_num_delegations=0)
        session = _make_session(tmp_path, config=config)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._denden_addr = "127.0.0.1:9700"
        session._register_agent("agent_orch", role="orchestrator", parent_id=None)

        for i in range(10):
            session._handle_delegate(self._make_denden_request(task_text=f"task {i}"))

        assert session._delegation_count == 10
        assert mock_handle.call_count == 10

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.ok_response")
    def test_cache_hits_count_toward_limit(self, mock_ok, mock_handle, tmp_path):
        """Cache hits should also increment the delegation counter."""
        from strawpot.delegation import DelegateResult

        mock_handle.return_value = DelegateResult(output="result", exit_code=0)
        mock_ok.return_value = "ok"

        config = _make_config(
            max_num_delegations=2,
            cache_delegations=True,
        )
        session = _make_session(tmp_path, config=config)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._denden_addr = "127.0.0.1:9700"
        session._register_agent("agent_orch", role="orchestrator", parent_id=None)

        # First call spawns an agent — count goes to 1
        session._handle_delegate(self._make_denden_request())
        assert session._delegation_count == 1

        # Same request again — cache hit, count still increments to 2
        session._handle_delegate(self._make_denden_request())
        assert session._delegation_count == 2
        assert mock_handle.call_count == 1  # only spawned once (cache hit)

        # Third call — limit reached, denied
        resp = session._handle_delegate(self._make_denden_request())
        assert "DENY_DELEGATIONS_LIMIT" in str(resp)


# ---------------------------------------------------------------------------
# Activity watcher loop
# ---------------------------------------------------------------------------


class TestActivityWatcherLoop:
    """Tests for the _activity_watcher_loop orchestration logic.

    These tests exercise the watcher's state machine directly by:
    - Setting up Session internals (_agent_info, _agent_spans, _tracer)
    - Writing fake log files
    - Running a single iteration of the loop (stop event fires after one tick)
    """

    def _make_session_for_watcher(self, tmp_path):
        """Create a minimally-configured Session for watcher tests."""
        session = _make_session(tmp_path)
        session._tracer = MagicMock()
        session._cancel_watcher_stop = threading.Event()
        # Point session dir to tmp_path so log files are discoverable
        session._session_dir = lambda: str(tmp_path)
        return session

    def _write_agent_log(self, tmp_path, agent_id, content):
        """Write a fake agent log file."""
        log_dir = tmp_path / "agents" / agent_id
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / ".log").write_text(content)

    def _register_agent(self, session, agent_id, span_id="span_1", state="running"):
        from strawpot.cancel import AgentState
        session._agent_info[agent_id] = {"state": AgentState(state)}
        session._agent_spans[agent_id] = span_id

    def _run_iterations(self, session, n=1, between=None):
        """Run the watcher loop for *n* iterations then stop.

        ``between`` is an optional callback invoked after each iteration
        (except the last) — use it to change log files or agent state
        between ticks.

        The loop's ``current`` dict is local, so we must run all
        iterations in a single call to preserve state tracking.
        """
        count = 0
        original_wait = session._cancel_watcher_stop.wait

        def _tick_wait(**kwargs):
            nonlocal count
            count += 1
            if between and count < n:
                between(count)
            if count >= n:
                session._cancel_watcher_stop.set()
            return count >= n

        session._cancel_watcher_stop.clear()
        session._cancel_watcher_stop.wait = _tick_wait
        session._ACTIVITY_POLL_INTERVAL = 0.01
        session._activity_watcher_loop()
        session._cancel_watcher_stop.wait = original_wait

    def test_new_activity_emits_tool_start(self, tmp_path):
        session = self._make_session_for_watcher(tmp_path)
        self._register_agent(session, "agent_1", "span_1")
        self._write_agent_log(tmp_path, "agent_1", "⠋ Reading src/app.ts...\n")

        self._run_iterations(session)

        session._tracer.tool_start.assert_called_once_with(
            span_id="span_1",
            agent_id="agent_1",
            tool="Read",
            summary="Reading src/app.ts...",
        )
        # Drain emits tool_end on shutdown for still-tracked activity.
        session._tracer.tool_end.assert_called_once_with(
            span_id="span_1", agent_id="agent_1", tool="Read",
        )

    def test_activity_change_emits_tool_end_then_tool_start(self, tmp_path):
        """When activity changes, tool_end fires for old, tool_start for new."""
        session = self._make_session_for_watcher(tmp_path)
        self._register_agent(session, "agent_1", "span_1")
        self._write_agent_log(tmp_path, "agent_1", "⠋ Reading file.py...\n")

        def change_log(_tick):
            self._write_agent_log(tmp_path, "agent_1", "⠙ Editing file.py...\n")

        self._run_iterations(session, n=2, between=change_log)

        # Iteration 1: tool_start(Read). Iteration 2: tool_end(Read) + tool_start(Edit).
        # Drain: tool_end(Edit).
        assert session._tracer.tool_start.call_count == 2
        assert session._tracer.tool_end.call_count == 2  # Read + Edit (drain)
        session._tracer.tool_start.assert_called_with(
            span_id="span_1", agent_id="agent_1",
            tool="Edit", summary="Editing file.py...",
        )

    def test_activity_cleared_emits_tool_end(self, tmp_path):
        """When log no longer contains activity, tool_end fires."""
        session = self._make_session_for_watcher(tmp_path)
        self._register_agent(session, "agent_1", "span_1")
        self._write_agent_log(tmp_path, "agent_1", "⠋ Reading file.py...\n")

        def clear_log(_tick):
            self._write_agent_log(tmp_path, "agent_1", "Here is the result:\n")

        self._run_iterations(session, n=2, between=clear_log)

        # Iteration 1: tool_start(Read). Iteration 2: tool_end(Read).
        session._tracer.tool_start.assert_called_once()
        session._tracer.tool_end.assert_called_once_with(
            span_id="span_1", agent_id="agent_1", tool="Read",
        )

    def test_agent_stops_while_active_emits_tool_end(self, tmp_path):
        """When an agent leaves RUNNING state, its pending activity is closed."""
        from strawpot.cancel import AgentState

        session = self._make_session_for_watcher(tmp_path)
        self._register_agent(session, "agent_1", "span_1")
        self._write_agent_log(tmp_path, "agent_1", "⠋ Reading file.py...\n")

        def stop_agent(_tick):
            session._agent_info["agent_1"]["state"] = AgentState.COMPLETED

        self._run_iterations(session, n=2, between=stop_agent)

        # Iteration 1: tool_start. Iteration 2: agent no longer running → tool_end.
        session._tracer.tool_start.assert_called_once()
        session._tracer.tool_end.assert_called_once_with(
            span_id="span_1", agent_id="agent_1", tool="Read",
        )

    def test_no_log_file_does_not_crash(self, tmp_path):
        """Missing log file produces no tracer calls and no crash."""
        session = self._make_session_for_watcher(tmp_path)
        self._register_agent(session, "agent_1", "span_1")
        # No log file written

        self._run_iterations(session)

        session._tracer.tool_start.assert_not_called()
        session._tracer.tool_end.assert_not_called()

    def test_same_activity_no_duplicate_events(self, tmp_path):
        """Same activity across iterations should not re-emit tool_start."""
        session = self._make_session_for_watcher(tmp_path)
        self._register_agent(session, "agent_1", "span_1")
        self._write_agent_log(tmp_path, "agent_1", "⠋ Reading file.py...\n")

        # Run two iterations with the same log content
        self._run_iterations(session, n=2)

        # tool_start called only once (dedup on second iteration)
        assert session._tracer.tool_start.call_count == 1
        # Drain emits tool_end on shutdown.
        session._tracer.tool_end.assert_called_once_with(
            span_id="span_1", agent_id="agent_1", tool="Read",
        )

    def test_exception_in_parse_does_not_kill_loop(self, tmp_path):
        """Errors during activity parsing are caught; loop continues."""
        session = self._make_session_for_watcher(tmp_path)
        self._register_agent(session, "agent_1", "span_1")
        self._write_agent_log(tmp_path, "agent_1", "⠋ Reading file.py...\n")

        with patch("strawpot.activity.parse_activity_structured", side_effect=RuntimeError("boom")):
            # Should not raise — exception is caught
            self._run_iterations(session)

        # No tracer calls since parsing failed
        session._tracer.tool_start.assert_not_called()

    def test_skips_non_running_agents(self, tmp_path):
        """Agents in COMPLETED/CANCELLED state are not polled."""
        from strawpot.cancel import AgentState

        session = self._make_session_for_watcher(tmp_path)
        self._register_agent(session, "agent_1", "span_1", state="completed")
        self._write_agent_log(tmp_path, "agent_1", "⠋ Reading file.py...\n")

        self._run_iterations(session)

        session._tracer.tool_start.assert_not_called()

    def test_no_tracer_skips_watcher(self, tmp_path):
        """_start_activity_watcher is a no-op when tracer is None."""
        session = _make_session(tmp_path)
        session._tracer = None
        # Should return immediately without spawning a thread
        session._start_activity_watcher()
        # No crash — that's the assertion


# ---------------------------------------------------------------------------
# Session recap extraction
# ---------------------------------------------------------------------------


class TestExtractSessionRecap:
    def test_extracts_recap_section(self):
        output = "Some output.\n\n## Session Recap\n\nCompleted task X.\n- Done"
        result = _extract_session_recap(output)
        assert result.startswith("## Session Recap")
        assert "Completed task X." in result

    def test_empty_output(self):
        assert _extract_session_recap("") == ""

    def test_no_recap(self):
        assert _extract_session_recap("Just normal output.") == ""

    def test_truncates_long_recap(self):
        recap = "## Session Recap\n\n" + "x" * 3000
        result = _extract_session_recap(recap)
        assert len(result) == 2000

    def test_preserves_full_section(self):
        output = "Preamble.\n\n## Session Recap\n\nLine1\nLine2\n\nLine3"
        result = _extract_session_recap(output)
        assert "Line1" in result
        assert "Line2" in result
        assert "Line3" in result

    def test_multiple_recaps_uses_last(self):
        """When output contains quoted and own recap, use the last one."""
        output = (
            "Here was the previous session:\n\n"
            "## Session Recap\n\nOld recap from last time.\n\n"
            "Now my work:\n\n"
            "## Session Recap\n\nNew recap from this session."
        )
        result = _extract_session_recap(output)
        assert "New recap from this session." in result
        assert "Old recap from last time." not in result

    def test_stops_at_next_heading(self):
        """Recap extraction stops at the next ## heading."""
        output = (
            "## Session Recap\n\nRecap content.\n\n"
            "## Appendix\n\nTrailing stuff."
        )
        result = _extract_session_recap(output)
        assert "Recap content." in result
        assert "Trailing stuff." not in result
        assert "## Appendix" not in result

    def test_word_boundary_no_false_match(self):
        """'## Session Recaps' should NOT match due to word boundary."""
        output = "## Session Recaps\n\nThis is a plural heading, not a recap."
        result = _extract_session_recap(output)
        # \b after 'Recap' means 's' breaks the boundary — should NOT match
        assert result == ""

    def test_recap_at_start_of_output(self):
        """Recap heading at the very start of output is captured."""
        output = "## Session Recap\n\nEntire output is the recap."
        result = _extract_session_recap(output)
        assert result.startswith("## Session Recap")
        assert "Entire output is the recap." in result

    def test_whitespace_only_recap_body(self):
        """Recap with only whitespace after heading still returns heading."""
        output = "Done.\n\n## Session Recap\n\n   \n  "
        result = _extract_session_recap(output)
        # strip() applied — should still start with the heading
        assert result.startswith("## Session Recap")


# ---------------------------------------------------------------------------
# Session warm-start remember (stop path)
# ---------------------------------------------------------------------------


class TestSessionWarmStartRemember:
    """Test that stop() stores session recap for warm-start."""

    def _make_session_with_memory(self, tmp_path):
        """Create a session with a mock memory provider and a completed agent."""
        session = _make_session(tmp_path)
        memory = MagicMock()
        memory.name = "mock-memory"
        memory.dump.return_value = None
        memory.remember.return_value = RememberResult(
            status="accepted", entry_id="k_1"
        )
        session._memory_provider = memory
        session._run_id = "run_test"
        session._group_id = "g_test"
        session.config = _make_config(orchestrator_role="imu")
        session._orchestrator_role_prompt = "You are imu."
        session.memory_task = "Do the thing."
        session._orchestrator_result = AgentResult(
            summary="Done",
            output="Work done.\n\n## Session Recap\n\nCompleted task.",
            exit_code=0,
        )
        # Register an orchestrator agent (no parent)
        session._agent_info = {"agent_orch": {"parent": None}}
        return session, memory

    def test_remember_called_with_recap(self, tmp_path):
        """stop() stores session recap via remember()."""
        session, memory = self._make_session_with_memory(tmp_path)
        session.stop()

        recap_calls = [
            c for c in memory.remember.call_args_list
            if "session-recap" in c.kwargs.get("keywords", [])
        ]
        assert len(recap_calls) == 1
        kw = recap_calls[0].kwargs
        assert "session-recap" in kw["keywords"]
        assert "warm-start" in kw["keywords"]
        assert "imu" in kw["keywords"]
        assert "run_test" in kw["keywords"]
        assert kw["scope"] == "project"
        assert "Completed task." in kw["content"]

    def test_no_remember_when_no_recap(self, tmp_path):
        """stop() does not call remember when there's no recap."""
        session, memory = self._make_session_with_memory(tmp_path)
        session._orchestrator_result = AgentResult(
            summary="Done", output="No recap here.", exit_code=0
        )
        session.stop()

        memory.remember.assert_not_called()

    def test_remember_failure_does_not_crash(self, tmp_path):
        """stop() completes even if remember() raises."""
        session, memory = self._make_session_with_memory(tmp_path)
        memory.remember.side_effect = RuntimeError("disk full")
        # Should not raise
        session.stop()

    def test_no_remember_when_orchestrator_result_none(self, tmp_path):
        """stop() does not call remember when orchestrator never finished."""
        session, memory = self._make_session_with_memory(tmp_path)
        session._orchestrator_result = None
        session.stop()

        memory.remember.assert_not_called()
