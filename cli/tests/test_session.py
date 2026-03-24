"""Tests for strawpot.session."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

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
    recover_stale_sessions,
    resolve_isolator,
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
        "isolation": "none",
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
        assert session._session_data["isolation"] == "none"
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
# Merge integration in stop()
# ---------------------------------------------------------------------------


class TestStopMerge:
    def test_calls_merge_for_worktree(self, tmp_path):
        """stop() calls _merge_session_changes when env has a branch."""
        session = _make_session(tmp_path)
        session._working_dir = str(tmp_path)
        session._run_id = "run_merge_wt"
        session._env = IsolatedEnv(
            path=str(tmp_path / "wt"), branch="strawpot/run_merge_wt"
        )
        session._session_data = {
            "base_branch": "main",
            "worktree_branch": "strawpot/run_merge_wt",
        }

        with patch.object(session, "_merge_session_changes", return_value=True) as mock_merge:
            session.stop()

        mock_merge.assert_called_once()

    def test_skips_merge_for_none_isolation(self, tmp_path):
        """stop() does not call _merge_session_changes when env has no branch."""
        session = _make_session(tmp_path)
        session._working_dir = str(tmp_path)
        session._run_id = "run_merge_none"
        session._env = IsolatedEnv(path=str(tmp_path))

        with patch.object(session, "_merge_session_changes") as mock_merge:
            session.stop()

        mock_merge.assert_not_called()

    def test_delete_branch_false_for_pr(self, tmp_path):
        """When merge returns False, cleanup receives delete_branch=False."""
        from strawpot.isolation.worktree import WorktreeIsolator

        wt_isolator = MagicMock(spec=WorktreeIsolator)
        wt_isolator.cleanup.return_value = None
        session = _make_session(tmp_path, isolator=wt_isolator)
        session._working_dir = str(tmp_path)
        session._run_id = "run_pr"
        session._env = IsolatedEnv(
            path=str(tmp_path / "wt"), branch="strawpot/run_pr"
        )
        session._session_data = {
            "base_branch": "main",
            "worktree_branch": "strawpot/run_pr",
        }

        with patch.object(session, "_merge_session_changes", return_value=False):
            session.stop()

        wt_isolator.cleanup.assert_called_once()
        call_kwargs = wt_isolator.cleanup.call_args.kwargs
        assert call_kwargs["delete_branch"] is False

    def test_worktree_cleanup_always_keeps_branch(self, tmp_path):
        """Worktree isolator cleanup always receives delete_branch=False.

        Branch deletion is now handled separately by _cleanup_session_branch
        (issue #459) rather than inside the isolator.
        """
        from strawpot.isolation.worktree import WorktreeIsolator

        wt_isolator = MagicMock(spec=WorktreeIsolator)
        wt_isolator.cleanup.return_value = None
        session = _make_session(tmp_path, isolator=wt_isolator)
        session._working_dir = str(tmp_path)
        session._run_id = "run_local"
        session._env = IsolatedEnv(
            path=str(tmp_path / "wt"), branch="strawpot/run_local"
        )
        session._session_data = {
            "base_branch": "main",
            "worktree_branch": "strawpot/run_local",
        }

        with patch.object(session, "_merge_session_changes", return_value=True):
            session.stop()

        wt_isolator.cleanup.assert_called_once()
        call_kwargs = wt_isolator.cleanup.call_args.kwargs
        assert call_kwargs["delete_branch"] is False

    def test_merge_failure_still_cleans_up(self, tmp_path):
        """If merge raises an exception, isolator.cleanup still runs."""
        session = _make_session(tmp_path)
        session._working_dir = str(tmp_path)
        session._run_id = "run_fail"
        session._env = IsolatedEnv(
            path=str(tmp_path / "wt"), branch="strawpot/run_fail"
        )
        session._session_data = {
            "base_branch": "main",
            "worktree_branch": "strawpot/run_fail",
        }

        with patch.object(
            session, "_merge_session_changes", side_effect=RuntimeError("boom")
        ):
            # Should not raise
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
        assert data["isolation"] == "none"
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

    def test_stale_none_isolation(self, tmp_path):
        """Stale session with isolation=none — swaps running→archive symlink."""
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

    @patch("strawpot.session._recover_merge", return_value=True)
    @patch("strawpot.session.WorktreeIsolator")
    def test_stale_worktree_runs_merge_and_cleanup(
        self, mock_wt_cls, mock_merge, tmp_path
    ):
        """Stale worktree session runs merge + isolator cleanup."""
        wt_path = str(tmp_path / "worktrees" / "run_wt")
        os.makedirs(wt_path)
        session_dir = _write_stale_session(
            tmp_path,
            "run_wt",
            isolation="worktree",
            worktree=wt_path,
            worktree_branch="strawpot/run_wt",
            base_branch="main",
        )

        result = recover_stale_sessions(str(tmp_path), _make_config())

        assert result == ["run_wt"]
        mock_merge.assert_called_once()
        mock_wt_cls.return_value.cleanup.assert_called_once()
        cleanup_kwargs = mock_wt_cls.return_value.cleanup.call_args.kwargs
        assert cleanup_kwargs["delete_branch"] is True
        # Session dir stays, archive symlink created
        assert os.path.isdir(session_dir)
        strawpot_dir = os.path.join(str(tmp_path), ".strawpot")
        assert os.path.islink(os.path.join(strawpot_dir, "archive", "run_wt"))

    @patch("strawpot.session._recover_merge", return_value=False)
    @patch("strawpot.session.WorktreeIsolator")
    def test_worktree_pr_strategy_keeps_branch(
        self, mock_wt_cls, mock_merge, tmp_path
    ):
        """PR strategy merge returns False — branch is kept."""
        wt_path = str(tmp_path / "worktrees" / "run_pr")
        os.makedirs(wt_path)
        _write_stale_session(
            tmp_path,
            "run_pr",
            isolation="worktree",
            worktree=wt_path,
            worktree_branch="strawpot/run_pr",
            base_branch="main",
        )

        recover_stale_sessions(str(tmp_path), _make_config())

        cleanup_kwargs = mock_wt_cls.return_value.cleanup.call_args.kwargs
        assert cleanup_kwargs["delete_branch"] is False

    def test_worktree_missing_branch_info_skips_merge(self, tmp_path):
        """Worktree session without branch info skips merge, still cleans up."""
        wt_path = str(tmp_path / "worktrees" / "run_noinfo")
        os.makedirs(wt_path)
        session_dir = _write_stale_session(
            tmp_path,
            "run_noinfo",
            isolation="worktree",
            worktree=wt_path,
            # no worktree_branch or base_branch
        )

        with patch("strawpot.session.WorktreeIsolator") as mock_wt_cls:
            result = recover_stale_sessions(str(tmp_path), _make_config())

        assert result == ["run_noinfo"]
        mock_wt_cls.return_value.cleanup.assert_called_once()
        # Session dir stays, archive symlink created
        assert os.path.isdir(session_dir)
        strawpot_dir = os.path.join(str(tmp_path), ".strawpot")
        assert os.path.islink(os.path.join(strawpot_dir, "archive", "run_noinfo"))

    def test_worktree_dir_missing_skips_merge(self, tmp_path):
        """Worktree dir already removed — skips merge, still cleans up."""
        session_dir = _write_stale_session(
            tmp_path,
            "run_gone",
            isolation="worktree",
            worktree=str(tmp_path / "gone"),
            worktree_branch="strawpot/run_gone",
            base_branch="main",
        )

        with patch("strawpot.session.WorktreeIsolator") as mock_wt_cls:
            result = recover_stale_sessions(str(tmp_path), _make_config())

        assert result == ["run_gone"]
        # Cleanup still called even though worktree is missing (idempotent)
        mock_wt_cls.return_value.cleanup.assert_called_once()
        # Session dir stays, archive symlink created
        assert os.path.isdir(session_dir)
        strawpot_dir = os.path.join(str(tmp_path), ".strawpot")
        assert os.path.islink(os.path.join(strawpot_dir, "archive", "run_gone"))

    @patch("strawpot.session.WorktreeIsolator")
    def test_isolator_cleanup_failure_still_archives_dir(
        self, mock_wt_cls, tmp_path
    ):
        """If isolator cleanup raises, session dir is still archived."""
        wt_path = str(tmp_path / "worktrees" / "run_fail")
        os.makedirs(wt_path)
        mock_wt_cls.return_value.cleanup.side_effect = RuntimeError("git fail")
        session_dir = _write_stale_session(
            tmp_path,
            "run_fail",
            isolation="worktree",
            worktree=wt_path,
            worktree_branch="strawpot/run_fail",
        )

        result = recover_stale_sessions(str(tmp_path), _make_config())

        assert result == ["run_fail"]
        # Session dir stays, archive symlink created
        assert os.path.isdir(session_dir)
        strawpot_dir = os.path.join(str(tmp_path), ".strawpot")
        assert os.path.islink(os.path.join(strawpot_dir, "archive", "run_fail"))

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
