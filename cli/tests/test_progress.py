"""Tests for progress event types and Session event emission."""

import logging
from unittest.mock import MagicMock

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
