"""In-process pub/sub event bus for cross-session notifications."""

import asyncio
import json
from dataclasses import asdict, dataclass, field
from typing import AsyncIterator


@dataclass
class SessionEvent:
    """A global lifecycle event."""

    kind: str  # "session_started" | "session_completed" | "session_failed" | "session_stopped"
    run_id: str
    project_id: int | None = None
    data: dict = field(default_factory=dict)


class EventBus:
    """Simple broadcast pub/sub using asyncio.Queue per subscriber."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[SessionEvent]] = []

    def publish(self, event: SessionEvent) -> None:
        """Publish an event to all subscribers (non-blocking)."""
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # drop if subscriber is too slow

    async def subscribe(self, poll_interval: float = 5.0) -> AsyncIterator[SessionEvent | None]:
        """Yield events as they arrive. Clean up on generator close.

        Yields ``None`` every *poll_interval* seconds when no event arrives,
        giving callers a chance to check for client disconnection.
        """
        q: asyncio.Queue[SessionEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=poll_interval)
                    yield event
                except asyncio.TimeoutError:
                    yield None
        finally:
            self._subscribers.remove(q)


class ProgressEventAdapter:
    """Bridges CLI ProgressEvent to GUI EventBus.

    Maps ProgressEvent kinds to SessionEvent, preserving data
    for the GUI frontend to consume when ready.
    """

    def __init__(self, event_bus: EventBus, run_id: str, project_id: int | None = None) -> None:
        self._event_bus = event_bus
        self._run_id = run_id
        self._project_id = project_id

    def handle_event(self, event) -> None:
        """Callback for ``Session.on_event``."""
        self._event_bus.publish(SessionEvent(
            kind=f"progress_{event.kind}",
            run_id=self._run_id,
            project_id=self._project_id,
            data=asdict(event),
        ))


# Singleton instance, attached to app.state in lifespan
event_bus = EventBus()
