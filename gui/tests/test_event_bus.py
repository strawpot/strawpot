"""Unit tests for the in-process event bus."""

import asyncio

import pytest

from strawpot_gui.event_bus import EventBus, SessionEvent


@pytest.fixture
def bus():
    return EventBus()


class TestEventBus:
    def test_publish_without_subscribers(self, bus):
        """Publishing with no subscribers should not raise."""
        bus.publish(SessionEvent(kind="session_started", run_id="run_1"))

    def test_subscribe_receives_events(self, bus):
        """Subscriber receives published events."""

        async def _run():
            received = []

            async def consumer():
                async for event in bus.subscribe():
                    received.append(event)
                    if len(received) >= 2:
                        break

            task = asyncio.create_task(consumer())
            await asyncio.sleep(0.01)

            bus.publish(SessionEvent(kind="session_started", run_id="run_1"))
            bus.publish(SessionEvent(kind="session_completed", run_id="run_1"))

            await asyncio.wait_for(task, timeout=2.0)

            assert len(received) == 2
            assert received[0].kind == "session_started"
            assert received[1].kind == "session_completed"

        asyncio.run(_run())

    def test_multiple_subscribers(self, bus):
        """Multiple subscribers each receive all events."""

        async def _run():
            received_1 = []
            received_2 = []

            async def consumer(target):
                async for event in bus.subscribe():
                    target.append(event)
                    if len(target) >= 1:
                        break

            t1 = asyncio.create_task(consumer(received_1))
            t2 = asyncio.create_task(consumer(received_2))

            await asyncio.sleep(0.01)

            bus.publish(SessionEvent(kind="session_started", run_id="run_1"))

            await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2.0)

            assert len(received_1) == 1
            assert len(received_2) == 1

        asyncio.run(_run())

    def test_subscriber_cleanup_on_close(self, bus):
        """Subscriber is removed from bus when generator is closed."""

        async def _run():
            gen = bus.subscribe()
            # Start iterating to register the subscriber
            task = asyncio.ensure_future(gen.__anext__())
            await asyncio.sleep(0.01)
            assert len(bus._subscribers) == 1

            # Cancel the pending __anext__ first, then close the generator
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await gen.aclose()
            assert len(bus._subscribers) == 0

        asyncio.run(_run())

    def test_full_queue_drops_event(self, bus):
        """Events are dropped when a subscriber's queue is full."""
        q = asyncio.Queue(maxsize=2)
        bus._subscribers.append(q)

        # Fill the queue
        bus.publish(SessionEvent(kind="session_started", run_id="run_1"))
        bus.publish(SessionEvent(kind="session_started", run_id="run_2"))
        # This should be silently dropped
        bus.publish(SessionEvent(kind="session_started", run_id="run_3"))

        assert q.qsize() == 2


# ---------------------------------------------------------------------------
# ProgressEventAdapter tests
# ---------------------------------------------------------------------------


class TestProgressEventAdapter:
    """Tests for the ProgressEventAdapter bridge."""

    def _make_progress_event(self, kind="delegate_start", role="implementer",
                             detail="", duration_ms=0, status="", depth=0):
        """Create a mock ProgressEvent-like dataclass."""
        from dataclasses import dataclass

        @dataclass
        class FakeProgressEvent:
            kind: str
            role: str
            detail: str
            timestamp: str
            duration_ms: int
            status: str
            depth: int

        return FakeProgressEvent(
            kind=kind, role=role, detail=detail,
            timestamp="2026-03-24T10:00:00+00:00",
            duration_ms=duration_ms, status=status, depth=depth,
        )

    def test_publishes_session_event_with_progress_prefix(self, bus):
        from strawpot_gui.event_bus import ProgressEventAdapter

        published = []
        bus.publish = lambda e: published.append(e)

        adapter = ProgressEventAdapter(bus, run_id="run_42", project_id=7)
        adapter.handle_event(self._make_progress_event("delegate_start"))

        assert len(published) == 1
        event = published[0]
        assert event.kind == "progress_delegate_start"
        assert event.run_id == "run_42"
        assert event.project_id == 7

    def test_data_contains_all_progress_fields(self, bus):
        from strawpot_gui.event_bus import ProgressEventAdapter

        published = []
        bus.publish = lambda e: published.append(e)

        adapter = ProgressEventAdapter(bus, run_id="run_1")
        adapter.handle_event(self._make_progress_event(
            kind="delegate_end", role="code-reviewer",
            detail="done", duration_ms=5000, status="ok", depth=2,
        ))

        data = published[0].data
        assert data["kind"] == "delegate_end"
        assert data["role"] == "code-reviewer"
        assert data["detail"] == "done"
        assert data["duration_ms"] == 5000
        assert data["status"] == "ok"
        assert data["depth"] == 2
        assert "timestamp" in data

    def test_project_id_defaults_to_none(self, bus):
        from strawpot_gui.event_bus import ProgressEventAdapter

        published = []
        bus.publish = lambda e: published.append(e)

        adapter = ProgressEventAdapter(bus, run_id="run_1")
        adapter.handle_event(self._make_progress_event())

        assert published[0].project_id is None

    def test_multiple_events_published(self, bus):
        from strawpot_gui.event_bus import ProgressEventAdapter

        published = []
        bus.publish = lambda e: published.append(e)

        adapter = ProgressEventAdapter(bus, run_id="run_1")
        adapter.handle_event(self._make_progress_event("session_start"))
        adapter.handle_event(self._make_progress_event("delegate_start"))
        adapter.handle_event(self._make_progress_event("session_end"))

        assert len(published) == 3
        kinds = [e.kind for e in published]
        assert kinds == [
            "progress_session_start",
            "progress_delegate_start",
            "progress_session_end",
        ]

    def test_full_sequence_publishes_to_real_bus(self, bus):
        """Integration: adapter publishes to real EventBus, subscriber receives."""
        from strawpot_gui.event_bus import ProgressEventAdapter

        adapter = ProgressEventAdapter(bus, run_id="run_1", project_id=3)

        async def _run():
            received = []

            async def consumer():
                async for event in bus.subscribe():
                    if event is not None:
                        received.append(event)
                        if len(received) >= 3:
                            break

            task = asyncio.create_task(consumer())
            await asyncio.sleep(0.01)

            adapter.handle_event(self._make_progress_event("session_start"))
            adapter.handle_event(self._make_progress_event("delegate_start"))
            adapter.handle_event(self._make_progress_event("session_end"))

            await asyncio.wait_for(task, timeout=2.0)

            assert len(received) == 3
            assert received[0].kind == "progress_session_start"
            assert received[0].run_id == "run_1"
            assert received[0].project_id == 3

        asyncio.run(_run())
