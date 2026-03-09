"""In-process pub/sub event bus for cross-session notifications."""

import asyncio
import json
from dataclasses import dataclass, field
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

    async def subscribe(self) -> AsyncIterator[SessionEvent]:
        """Yield events as they arrive. Clean up on generator close."""
        q: asyncio.Queue[SessionEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            self._subscribers.remove(q)


# Singleton instance, attached to app.state in lifespan
event_bus = EventBus()
