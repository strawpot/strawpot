"""Global SSE endpoint for cross-session lifecycle notifications."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from strawpot_gui.event_bus import EventBus
from strawpot_gui.sse import format_sse_typed, sse_retry

router = APIRouter(prefix="/api", tags=["sse"])


@router.get("/events")
async def global_events_sse(request: Request):
    """SSE endpoint for cross-session lifecycle notifications.

    Broadcasts named events: session_started, session_completed,
    session_failed, session_stopped.
    """
    bus: EventBus = request.app.state.event_bus

    async def event_stream():
        event_id = 0
        yield sse_retry(3000)

        async for session_event in bus.subscribe():
            if await request.is_disconnected():
                return
            if session_event is None:
                continue
            event_id += 1
            yield format_sse_typed(event_id, session_event.kind, {
                "run_id": session_event.run_id,
                "project_id": session_event.project_id,
                **session_event.data,
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
