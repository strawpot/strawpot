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

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self, bus):
        """Subscriber receives published events."""
        received = []

        async def consumer():
            async for event in bus.subscribe():
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(consumer())

        # Give subscriber time to register
        await asyncio.sleep(0.01)

        bus.publish(SessionEvent(kind="session_started", run_id="run_1"))
        bus.publish(SessionEvent(kind="session_completed", run_id="run_1"))

        await asyncio.wait_for(task, timeout=2.0)

        assert len(received) == 2
        assert received[0].kind == "session_started"
        assert received[1].kind == "session_completed"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, bus):
        """Multiple subscribers each receive all events."""
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

    @pytest.mark.asyncio
    async def test_subscriber_cleanup_on_break(self, bus):
        """Subscriber is removed from bus when generator is closed."""

        async def consume_one():
            async for event in bus.subscribe():
                break  # immediately exit after first event

        task = asyncio.create_task(consume_one())
        await asyncio.sleep(0.01)
        bus.publish(SessionEvent(kind="session_started", run_id="run_1"))
        await asyncio.wait_for(task, timeout=2.0)
        assert len(bus._subscribers) == 0

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
