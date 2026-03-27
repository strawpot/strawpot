"""Tests for progress event types and Session event emission."""

import io
import json
import logging
import threading
from unittest.mock import MagicMock, patch

from strawpot.progress import (
    JsonProgressRenderer,
    ProgressEvent,
    TerminalProgressRenderer,
    _format_duration,
)


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


# ---------------------------------------------------------------------------
# _format_duration tests
# ---------------------------------------------------------------------------


class TestFormatDuration:
    def test_zero(self):
        assert _format_duration(0) == "0s"

    def test_seconds(self):
        assert _format_duration(5000) == "5s"

    def test_under_one_minute(self):
        assert _format_duration(59000) == "59s"

    def test_exactly_one_minute(self):
        assert _format_duration(60000) == "1m 0s"

    def test_minutes_and_seconds(self):
        assert _format_duration(125000) == "2m 5s"

    def test_large_duration(self):
        assert _format_duration(3661000) == "61m 1s"


# ---------------------------------------------------------------------------
# TerminalProgressRenderer tests
# ---------------------------------------------------------------------------


def _make_event(kind, role="implementer", detail="", duration_ms=0,
                status="", depth=0):
    return ProgressEvent(
        kind=kind, role=role, detail=detail,
        timestamp=_FIXED_TS, duration_ms=duration_ms,
        status=status, depth=depth,
    )


class TestTerminalProgressRenderer:
    """Tests for TerminalProgressRenderer."""

    def _capture_stderr(self, renderer, event):
        """Render an event and return what was written to stderr."""
        buf = io.StringIO()
        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr = buf
            mock_sys.stderr.isatty = lambda: False
            renderer._is_tty = False
            renderer.handle_event(event)
        return buf.getvalue()

    def test_delegate_start_renders(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(r, _make_event("delegate_start", depth=1))
        assert "> Delegating to implementer..." in output

    def test_delegate_end_ok_renders(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(
            r, _make_event("delegate_end", status="ok", duration_ms=12000)
        )
        assert "[ok] implementer completed (12s)" in output

    def test_delegate_end_error_renders(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(
            r, _make_event("delegate_end", status="error", duration_ms=5000)
        )
        assert "[FAIL] implementer failed (5s)" in output

    def test_delegate_denied_renders(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(
            r, _make_event("delegate_denied", detail="DENY_ROLE_NOT_ALLOWED")
        )
        assert "[FAIL] implementer denied: DENY_ROLE_NOT_ALLOWED" in output

    def test_delegate_cached_renders(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(r, _make_event("delegate_cached"))
        assert "[ok] implementer (cached)" in output

    def test_session_start_renders(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(
            r, _make_event("session_start", role="ai-ceo")
        )
        assert "Session started (orchestrator: ai-ceo)" in output

    def test_session_end_renders(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(
            r, _make_event("session_end", role="ai-ceo", detail="3 files changed",
                           duration_ms=125000, status="ok")
        )
        assert "[ok] Session complete (2m 5s) - 3 files changed" in output

    def test_ask_user_start_renders(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(r, _make_event("ask_user_start"))
        assert "? Waiting for user input" in output

    def test_ask_user_end_renders(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(
            r, _make_event("ask_user_end", status="ok", duration_ms=3000)
        )
        assert "[ok] User responded (3s)" in output

    def test_cancel_start_renders(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(
            r, _make_event("cancel_start", detail="agent_a + 3 descendants")
        )
        assert "[X] Cancelling implementer agent_a + 3 descendants..." in output

    def test_cancel_complete_renders(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(
            r, _make_event("cancel_complete", detail="4 agents", duration_ms=2100)
        )
        assert "[X] Cancelled 4 agents (2s)" in output

    def test_indentation_by_depth(self):
        r = TerminalProgressRenderer()
        # depth=0 → 2 spaces base
        out0 = self._capture_stderr(
            r, _make_event("delegate_cached", depth=0)
        )
        # depth=2 → 2 + 4 = 6 spaces
        out2 = self._capture_stderr(
            r, _make_event("delegate_cached", depth=2)
        )
        # depth=2 should have more leading spaces than depth=0
        leading0 = len(out0) - len(out0.lstrip())
        leading2 = len(out2) - len(out2.lstrip())
        assert leading2 > leading0

    def test_unicode_symbols_when_tty(self):
        """When isatty, uses Unicode checkmarks."""
        r = TerminalProgressRenderer()
        buf = io.StringIO()
        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr = buf
            mock_sys.stderr.isatty = lambda: True
            r._is_tty = True
            r.handle_event(_make_event("delegate_cached"))
        output = buf.getvalue()
        assert "\u2713" in output  # ✓

    def test_ascii_fallback_when_not_tty(self):
        r = TerminalProgressRenderer()
        output = self._capture_stderr(r, _make_event("delegate_cached"))
        assert "[ok]" in output
        assert "\u2713" not in output

    def test_terminal_title_set_on_delegate_start(self):
        """delegate_start sets terminal title when TTY."""
        r = TerminalProgressRenderer()
        buf = io.StringIO()
        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr = buf
            mock_sys.stderr.isatty = lambda: True
            r._is_tty = True
            r.handle_event(_make_event("delegate_start"))
        output = buf.getvalue()
        assert "\033]0;StrawPot: implementer\007" in output

    def test_terminal_title_cleared_on_session_end(self):
        """session_end clears terminal title when TTY."""
        r = TerminalProgressRenderer()
        buf = io.StringIO()
        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr = buf
            mock_sys.stderr.isatty = lambda: True
            r._is_tty = True
            r.handle_event(_make_event("session_end", role="ai-ceo",
                                       duration_ms=1000, status="ok"))
        output = buf.getvalue()
        assert "\033]0;\007" in output

    def test_broken_pipe_disables(self):
        """BrokenPipeError disables renderer without crash."""
        r = TerminalProgressRenderer()
        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr.write.side_effect = BrokenPipeError()
            mock_sys.stderr.isatty.return_value = False
            r._is_tty = False
            r.handle_event(_make_event("delegate_start"))
        assert r._disabled is True

    def test_oserror_disables(self):
        """OSError disables renderer without crash."""
        r = TerminalProgressRenderer()
        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr.write.side_effect = OSError("pipe gone")
            mock_sys.stderr.isatty.return_value = False
            r._is_tty = False
            r.handle_event(_make_event("delegate_start"))
        assert r._disabled is True

    def test_thread_safety(self):
        """Concurrent events don't crash or garble (smoke test)."""
        r = TerminalProgressRenderer()
        buf = io.StringIO()
        errors = []

        def fire(n):
            try:
                for _ in range(10):
                    with patch("strawpot.progress.sys") as mock_sys:
                        mock_sys.stderr = buf
                        mock_sys.stderr.isatty = lambda: False
                        r._is_tty = False
                        r.handle_event(_make_event("delegate_cached", depth=n))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=fire, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ---------------------------------------------------------------------------
# JsonProgressRenderer tests
# ---------------------------------------------------------------------------


class TestJsonProgressRenderer:
    """Tests for JsonProgressRenderer."""

    def _capture_stderr(self, renderer, event):
        buf = io.StringIO()
        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr = buf
            renderer.handle_event(event)
        return buf.getvalue()

    def test_outputs_valid_json(self):
        r = JsonProgressRenderer()
        output = self._capture_stderr(r, _make_event("delegate_start"))
        parsed = json.loads(output.strip())
        assert parsed["kind"] == "delegate_start"

    def test_contains_all_fields(self):
        r = JsonProgressRenderer()
        event = _make_event(
            "delegate_end", role="code-reviewer", detail="done",
            duration_ms=5000, status="ok", depth=2,
        )
        output = self._capture_stderr(r, event)
        parsed = json.loads(output.strip())
        assert parsed == {
            "kind": "delegate_end",
            "role": "code-reviewer",
            "detail": "done",
            "timestamp": _FIXED_TS,
            "duration_ms": 5000,
            "status": "ok",
            "depth": 2,
        }

    def test_compact_separators(self):
        """Output uses compact JSON separators (no spaces after : or ,)."""
        r = JsonProgressRenderer()
        event = _make_event("session_start")
        output = self._capture_stderr(r, event)
        line = output.strip()
        expected = json.dumps(
            {"kind": "session_start", "role": "implementer", "detail": "",
             "timestamp": _FIXED_TS, "duration_ms": 0, "status": "", "depth": 0},
            separators=(",", ":"),
        )
        assert line == expected

    def test_one_line_per_event(self):
        r = JsonProgressRenderer()
        buf = io.StringIO()
        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr = buf
            r.handle_event(_make_event("session_start"))
            r.handle_event(_make_event("delegate_start"))
            r.handle_event(_make_event("session_end"))
        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            json.loads(line)  # each line is valid JSON

    def test_flushes_after_each_write(self):
        r = JsonProgressRenderer()
        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr = MagicMock()
            r.handle_event(_make_event("delegate_start"))
            mock_sys.stderr.flush.assert_called()

    def test_broken_pipe_disables(self):
        r = JsonProgressRenderer()
        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr.write.side_effect = BrokenPipeError()
            r.handle_event(_make_event("delegate_start"))
        assert r._disabled is True

    def test_oserror_disables(self):
        r = JsonProgressRenderer()
        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr.write.side_effect = OSError("pipe gone")
            r.handle_event(_make_event("delegate_start"))
        assert r._disabled is True

    def test_thread_safe(self):
        r = JsonProgressRenderer()
        buf = io.StringIO()
        errors = []

        def fire():
            try:
                for _ in range(10):
                    with patch("strawpot.progress.sys") as mock_sys:
                        mock_sys.stderr = buf
                        r.handle_event(_make_event("delegate_cached"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=fire) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ---------------------------------------------------------------------------
# CLI --progress flag wiring tests
# ---------------------------------------------------------------------------


class TestProgressFlagWiring:
    """Verify _resolve_progress_renderer selects the correct renderer."""

    def test_auto_with_task_uses_terminal_renderer(self):
        from strawpot.cli import _resolve_progress_renderer

        on_event = _resolve_progress_renderer("auto", task="Do something")
        assert on_event is not None
        assert isinstance(on_event.__self__, TerminalProgressRenderer)

    def test_auto_without_task_uses_no_renderer(self):
        from strawpot.cli import _resolve_progress_renderer

        assert _resolve_progress_renderer("auto", task=None) is None

    def test_auto_with_empty_task_uses_no_renderer(self):
        from strawpot.cli import _resolve_progress_renderer

        assert _resolve_progress_renderer("auto", task="") is None

    def test_json_uses_json_renderer(self):
        from strawpot.cli import _resolve_progress_renderer

        on_event = _resolve_progress_renderer("json", task=None)
        assert on_event is not None
        assert isinstance(on_event.__self__, JsonProgressRenderer)

    def test_json_with_task_uses_json_renderer(self):
        from strawpot.cli import _resolve_progress_renderer

        on_event = _resolve_progress_renderer("json", task="Do something")
        assert on_event is not None
        assert isinstance(on_event.__self__, JsonProgressRenderer)

    def test_off_uses_no_renderer(self):
        from strawpot.cli import _resolve_progress_renderer

        assert _resolve_progress_renderer("off", task="Do something") is None

    def test_off_without_task_uses_no_renderer(self):
        from strawpot.cli import _resolve_progress_renderer

        assert _resolve_progress_renderer("off", task=None) is None

    def test_construction_failure_returns_none(self):
        """Renderer construction failures degrade gracefully to no progress."""
        from strawpot.cli import _resolve_progress_renderer

        with patch("strawpot.progress.TerminalProgressRenderer.__init__",
                   side_effect=OSError("broken stderr")):
            assert _resolve_progress_renderer("auto", task="foo") is None


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def _session_sequence():
    """A typical session event sequence for integration tests."""
    return [
        _make_event("session_start", role="ai-ceo"),
        _make_event("delegate_start", role="implementer", depth=1),
        _make_event("delegate_end", role="implementer", status="ok",
                    duration_ms=5000, depth=1),
        _make_event("session_end", role="ai-ceo", status="ok",
                    duration_ms=10000),
    ]


class TestProgressFlagIntegration:
    """Integration test: full event sequence through a renderer."""

    def test_full_sequence_through_terminal_renderer(self):
        r = TerminalProgressRenderer()
        buf = io.StringIO()

        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr = buf
            mock_sys.stderr.isatty = lambda: False
            r._is_tty = False
            for event in _session_sequence():
                r.handle_event(event)

        output = buf.getvalue()
        assert "Session started" in output
        assert "implementer" in output
        assert "Session complete" in output

    def test_full_sequence_through_json_renderer(self):
        r = JsonProgressRenderer()
        buf = io.StringIO()

        with patch("strawpot.progress.sys") as mock_sys:
            mock_sys.stderr = buf
            for event in _session_sequence():
                r.handle_event(event)

        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 4
        kinds = [json.loads(line)["kind"] for line in lines]
        assert kinds == ["session_start", "delegate_start", "delegate_end", "session_end"]
