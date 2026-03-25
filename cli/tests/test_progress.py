"""Tests for progress event types and Session event emission."""

import logging
from unittest.mock import MagicMock, patch

from strawpot.progress import ProgressEvent


# ---------------------------------------------------------------------------
# ProgressEvent dataclass tests
# ---------------------------------------------------------------------------

_FIXED_TS = "2026-03-24T10:00:00+00:00"


class TestProgressEvent:
    """ProgressEvent dataclass stores all fields correctly."""

    def test_fields_set_correctly(self):
        event = ProgressEvent(
            kind="delegate_start",
            role="implementer",
            detail="Add dark mode toggle",
            timestamp=_FIXED_TS,
            duration_ms=0,
            status="",
            depth=1,
        )
        assert event.kind == "delegate_start"
        assert event.role == "implementer"
        assert event.detail == "Add dark mode toggle"
        assert event.timestamp == _FIXED_TS
        assert event.duration_ms == 0
        assert event.status == ""
        assert event.depth == 1

    def test_has_exactly_seven_fields(self):
        """Guard against accidental field additions or removals."""
        field_names = [f.name for f in ProgressEvent.__dataclass_fields__.values()]
        assert field_names == [
            "kind",
            "role",
            "detail",
            "timestamp",
            "duration_ms",
            "status",
            "depth",
        ]

    def test_end_event_with_duration(self):
        event = ProgressEvent(
            kind="delegate_end",
            role="code-reviewer",
            detail="",
            timestamp=_FIXED_TS,
            duration_ms=12345,
            status="ok",
            depth=2,
        )
        assert event.duration_ms == 12345
        assert event.status == "ok"


# ---------------------------------------------------------------------------
# Session._emit_event tests
# ---------------------------------------------------------------------------


def _make_session(**kwargs):
    """Build a minimal Session with mocked dependencies for testing _emit_event."""
    from strawpot.session import Session

    defaults = {
        "config": MagicMock(),
        "wrapper": MagicMock(),
        "runtime": MagicMock(),
        "isolator": MagicMock(),
        "resolve_role": MagicMock(return_value={}),
        "resolve_role_dirs": MagicMock(return_value=None),
    }
    return Session(**{**defaults, **kwargs})


def _sample_event():
    return ProgressEvent(
        kind="delegate_start",
        role="implementer",
        detail="test task",
        timestamp=_FIXED_TS,
        duration_ms=0,
        status="",
        depth=1,
    )


class TestEmitEvent:
    """Tests for Session._emit_event()."""

    def test_noop_when_no_callback(self):
        """No error when on_event is None (the default)."""
        session = _make_session()
        session._emit_event(_sample_event())  # should not raise

    def test_calls_callback_with_event(self):
        callback = MagicMock()
        session = _make_session(on_event=callback)
        event = _sample_event()
        session._emit_event(event)
        callback.assert_called_once_with(event)

    def test_swallows_callback_exception_and_disables(self, caplog):
        """A raising callback must not crash the session; circuit-breaker disables it."""

        def bad_callback(event):
            raise RuntimeError("renderer exploded")

        session = _make_session(on_event=bad_callback)
        with caplog.at_level(logging.WARNING):
            session._emit_event(_sample_event())  # should not raise
        assert "Event callback failed" in caplog.text
        # Circuit-breaker: callback is now disabled
        assert session._on_event is None

    def test_circuit_breaker_prevents_repeated_failures(self):
        """After one failure, subsequent _emit_event calls are no-ops."""
        call_count = 0

        def bad_callback(event):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("boom")

        session = _make_session(on_event=bad_callback)
        session._emit_event(_sample_event())  # fails, disables
        session._emit_event(_sample_event())  # should be a no-op
        session._emit_event(_sample_event())  # should be a no-op
        assert call_count == 1  # only called once before circuit-breaker

    def test_keyboard_interrupt_propagates(self):
        """BaseException subclasses must not be swallowed."""
        import pytest

        def bad_callback(event):
            raise KeyboardInterrupt()

        session = _make_session(on_event=bad_callback)
        with pytest.raises(KeyboardInterrupt):
            session._emit_event(_sample_event())

    def test_multiple_events(self):
        callback = MagicMock()
        session = _make_session(on_event=callback)
        for _ in range(5):
            session._emit_event(_sample_event())
        assert callback.call_count == 5


# ---------------------------------------------------------------------------
# Event emission integration tests — _handle_delegate, _handle_ask_user,
# start(), stop()
# ---------------------------------------------------------------------------


def _make_delegate_session(tmp_path, on_event):
    """Create a Session wired for delegation testing with on_event."""
    from strawpot.config import StrawPotConfig
    from strawpot.isolation.protocol import IsolatedEnv

    config = StrawPotConfig(memory="")
    session = _make_session(
        config=config,
        on_event=on_event,
    )
    session._env = IsolatedEnv(path=str(tmp_path))
    session._working_dir = str(tmp_path)
    session._run_id = "run_test"
    session._denden_addr = "127.0.0.1:9700"
    session._register_agent("agent_orch", role="orchestrator", parent_id=None)
    return session


def _make_denden_request(
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
    request.WhichOneof.return_value = "delegate"
    return request


class TestDelegateEventEmission:
    """Verify _handle_delegate emits the right ProgressEvents."""

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.ok_response", return_value="ok")
    def test_success_emits_start_and_end_ok(self, _ok, mock_handle, tmp_path):
        from strawpot.delegation import DelegateResult

        mock_handle.return_value = DelegateResult(output="done", exit_code=0)
        events = []
        session = _make_delegate_session(tmp_path, on_event=events.append)
        session._handle_delegate(_make_denden_request())

        kinds = [e.kind for e in events]
        assert kinds == ["delegate_start", "delegate_end"]
        assert events[0].role == "implementer"
        assert events[0].status == ""
        assert events[0].depth == 0  # orchestrator depth is 0
        assert events[1].status == "ok"
        assert events[1].duration_ms >= 0

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.error_response", return_value="error")
    def test_nonzero_exit_emits_start_and_end_error(self, _err, mock_handle, tmp_path):
        from strawpot.delegation import DelegateResult

        mock_handle.return_value = DelegateResult(output="fail", exit_code=1)
        events = []
        session = _make_delegate_session(tmp_path, on_event=events.append)
        session._handle_delegate(_make_denden_request())

        kinds = [e.kind for e in events]
        assert kinds == ["delegate_start", "delegate_end"]
        assert events[1].status == "error"

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.denied_response", return_value="denied")
    def test_policy_denied_emits_start_and_denied(self, _denied, mock_handle, tmp_path):
        from strawpot.delegation import PolicyDenied

        mock_handle.side_effect = PolicyDenied("DENY_ROLE_NOT_ALLOWED")
        events = []
        session = _make_delegate_session(tmp_path, on_event=events.append)
        session._handle_delegate(_make_denden_request())

        kinds = [e.kind for e in events]
        assert kinds == ["delegate_start", "delegate_denied"]
        assert events[1].status == "denied"
        assert events[1].detail == "DENY_ROLE_NOT_ALLOWED"

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.error_response", return_value="error")
    def test_exception_emits_start_and_end_error(self, _err, mock_handle, tmp_path):
        mock_handle.side_effect = RuntimeError("kaboom")
        events = []
        session = _make_delegate_session(tmp_path, on_event=events.append)
        session._handle_delegate(_make_denden_request())

        kinds = [e.kind for e in events]
        assert kinds == ["delegate_start", "delegate_end"]
        assert events[1].status == "error"
        assert "kaboom" in events[1].detail

    def test_max_delegations_emits_denied(self, tmp_path):
        from strawpot.config import StrawPotConfig

        config = StrawPotConfig(memory="", max_num_delegations=1)
        events = []
        session = _make_session(config=config, on_event=events.append)

        from strawpot.isolation.protocol import IsolatedEnv

        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._denden_addr = "127.0.0.1:9700"
        session._register_agent("agent_orch", role="orchestrator", parent_id=None)
        session._delegation_count = 1  # already at limit

        session._handle_delegate(_make_denden_request())

        assert len(events) == 1
        assert events[0].kind == "delegate_denied"
        assert events[0].detail == "DENY_DELEGATIONS_LIMIT"

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.ok_response", return_value="ok")
    def test_cache_hit_emits_cached_only(self, _ok, mock_handle, tmp_path):
        """Cache hits emit delegate_cached, not delegate_start/delegate_end."""
        from strawpot.config import StrawPotConfig
        from strawpot.delegation import DelegateResult
        from strawpot.isolation.protocol import IsolatedEnv

        config = StrawPotConfig(memory="", cache_delegations=True)
        events = []
        session = _make_session(config=config, on_event=events.append)
        session._env = IsolatedEnv(path=str(tmp_path))
        session._working_dir = str(tmp_path)
        session._run_id = "run_test"
        session._denden_addr = "127.0.0.1:9700"
        session._register_agent("agent_orch", role="orchestrator", parent_id=None)

        # First call: real delegation
        mock_handle.return_value = DelegateResult(output="done", exit_code=0)
        session._handle_delegate(_make_denden_request())

        # Second call: should hit cache
        events.clear()
        session._handle_delegate(_make_denden_request())

        kinds = [e.kind for e in events]
        assert "delegate_cached" in kinds
        assert "delegate_start" not in kinds
        assert "delegate_end" not in kinds

    @patch("strawpot.session.handle_delegate")
    @patch("strawpot.session.ok_response", return_value="ok")
    def test_depth_matches_agent_depth(self, _ok, mock_handle, tmp_path):
        from strawpot.delegation import DelegateResult

        mock_handle.return_value = DelegateResult(output="done", exit_code=0)
        events = []
        session = _make_delegate_session(tmp_path, on_event=events.append)
        # Register a sub-agent at depth 2
        session._register_agent(
            "agent_sub", role="implementer", parent_id="agent_orch"
        )
        req = _make_denden_request(agent_id="agent_sub")
        session._handle_delegate(req)

        assert events[0].depth == 1  # sub-agent of orchestrator is depth 1


class TestAskUserEventEmission:
    """Verify _handle_ask_user emits ask_user_start + ask_user_end."""

    def _make_ask_request(self, question="What color?", agent_id="agent_orch"):
        request = MagicMock()
        request.request_id = "req_ask_1"
        request.ask_user.question = question
        request.ask_user.choices = []
        request.ask_user.default_value = ""
        request.ask_user.why = ""
        request.ask_user.response_format = 0
        request.trace.agent_instance_id = agent_id
        request.trace.run_id = "run_test"
        request.WhichOneof.return_value = "ask_user"
        return request

    def test_success_emits_start_and_end(self, tmp_path):
        from strawpot.session import AskUserResponse

        events = []
        handler = MagicMock(return_value=AskUserResponse(text="blue"))
        session = _make_delegate_session(tmp_path, on_event=events.append)
        session._ask_user_handler = handler

        session._handle_ask_user(self._make_ask_request())

        kinds = [e.kind for e in events]
        assert kinds == ["ask_user_start", "ask_user_end"]
        assert events[0].detail == "What color?"
        assert events[1].status == "ok"
        assert events[1].duration_ms >= 0

    def test_error_emits_start_and_end_error(self, tmp_path):
        events = []

        def failing_handler(req):
            raise RuntimeError("handler failed")

        session = _make_delegate_session(tmp_path, on_event=events.append)
        session._ask_user_handler = failing_handler

        session._handle_ask_user(self._make_ask_request())

        kinds = [e.kind for e in events]
        assert kinds == ["ask_user_start", "ask_user_end"]
        assert events[1].status == "error"


class TestSessionLifecycleEvents:
    """Verify start() and stop() emit session_start and session_end."""

    def test_stop_emits_session_end(self, tmp_path):
        """stop() emits session_end with duration."""
        import time

        events = []
        session = _make_delegate_session(tmp_path, on_event=events.append)
        session._session_start_time = time.monotonic() - 1.0  # 1s ago

        session.stop()

        end_events = [e for e in events if e.kind == "session_end"]
        assert len(end_events) == 1
        assert end_events[0].status == "ok"
        assert end_events[0].duration_ms >= 1000
