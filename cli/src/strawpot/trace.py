"""Session tracing — JSONL event stream with content-addressed artifact storage."""

import hashlib
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class TraceEvent:
    """Single trace event written to trace.jsonl."""

    ts: str
    event: str
    trace_id: str
    span_id: str
    parent_span: str | None = None
    data: dict = field(default_factory=dict)


class Tracer:
    """Lightweight JSONL tracer with content-addressed artifact storage.

    Created once per session.  Writes events to
    ``<session_dir>/trace.jsonl`` and stores large payloads under
    ``<session_dir>/artifacts/<sha256[:12]>``.
    """

    def __init__(self, session_dir: str, trace_id: str) -> None:
        self._session_dir = session_dir
        self._trace_id = trace_id
        self._trace_path = os.path.join(session_dir, "trace.jsonl")
        self._artifacts_dir = os.path.join(session_dir, "artifacts")
        os.makedirs(self._artifacts_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Artifact storage
    # ------------------------------------------------------------------

    def store_artifact(self, content: str) -> str | None:
        """Write *content* to ``artifacts/<sha256[:12]>`` and return the ref.

        Returns ``None`` if *content* is empty.  Deduplicates: if the
        artifact already exists on disk the write is skipped.
        """
        if not content:
            return None
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
        artifact_path = os.path.join(self._artifacts_dir, content_hash)
        if not os.path.exists(artifact_path):
            try:
                with open(artifact_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except OSError:
                logger.debug(
                    "Failed to write artifact %s", content_hash, exc_info=True
                )
        return content_hash

    # ------------------------------------------------------------------
    # Low-level event emit
    # ------------------------------------------------------------------

    def emit(
        self,
        event: str,
        span_id: str,
        parent_span: str | None = None,
        **data,
    ) -> None:
        """Append a single :class:`TraceEvent` to ``trace.jsonl``."""
        te = TraceEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            event=event,
            trace_id=self._trace_id,
            span_id=span_id,
            parent_span=parent_span,
            data=data,
        )
        try:
            line = json.dumps(asdict(te), separators=(",", ":"))
            with open(self._trace_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            logger.debug("Failed to write trace event: %s", event, exc_info=True)

    # ------------------------------------------------------------------
    # Span ID generation
    # ------------------------------------------------------------------

    @staticmethod
    def _new_span_id() -> str:
        return uuid.uuid4().hex[:12]

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def session_start(
        self, *, run_id: str, role: str, runtime: str, isolation: str
    ) -> str:
        """Emit ``session_start``.  Returns the root span_id."""
        span_id = self._new_span_id()
        self.emit(
            "session_start",
            span_id,
            run_id=run_id,
            role=role,
            runtime=runtime,
            isolation=isolation,
        )
        return span_id

    def session_end(
        self, *, span_id: str, merge_strategy: str, duration_ms: int
    ) -> None:
        """Emit ``session_end``."""
        self.emit(
            "session_end",
            span_id,
            merge_strategy=merge_strategy,
            duration_ms=duration_ms,
        )

    def delegate_start(
        self, *, role: str, parent_span: str, context: str
    ) -> str:
        """Emit ``delegate_start``.  Stores context as artifact.  Returns new span_id."""
        span_id = self._new_span_id()
        context_ref = self.store_artifact(context)
        self.emit(
            "delegate_start",
            span_id,
            parent_span=parent_span,
            role=role,
            context_ref=context_ref,
        )
        return span_id

    def delegate_end(
        self,
        *,
        span_id: str,
        exit_code: int,
        summary: str,
        duration_ms: int,
    ) -> None:
        """Emit ``delegate_end``."""
        self.emit(
            "delegate_end",
            span_id,
            exit_code=exit_code,
            summary=summary,
            duration_ms=duration_ms,
        )

    def delegate_denied(
        self, *, role: str, parent_span: str, reason: str
    ) -> None:
        """Emit ``delegate_denied``."""
        span_id = self._new_span_id()
        self.emit(
            "delegate_denied",
            span_id,
            parent_span=parent_span,
            role=role,
            reason=reason,
        )

    def memory_get(
        self,
        *,
        span_id: str,
        provider: str,
        cards: list,
        card_count: int,
    ) -> None:
        """Emit ``memory_get``.  Stores serialised cards as artifact."""
        cards_content = json.dumps([str(c) for c in cards]) if cards else ""
        cards_ref = self.store_artifact(cards_content)
        self.emit(
            "memory_get",
            span_id,
            provider=provider,
            cards_ref=cards_ref,
            card_count=card_count,
        )

    def memory_dump(
        self,
        *,
        span_id: str,
        provider: str,
        entries: str,
        entry_count: int,
    ) -> None:
        """Emit ``memory_dump``.  Stores entries as artifact."""
        entries_ref = self.store_artifact(entries)
        self.emit(
            "memory_dump",
            span_id,
            provider=provider,
            entries_ref=entries_ref,
            entry_count=entry_count,
        )

    def agent_spawn(
        self,
        *,
        span_id: str,
        agent_id: str,
        role: str,
        runtime: str,
        pid: int | None,
    ) -> None:
        """Emit ``agent_spawn``."""
        self.emit(
            "agent_spawn",
            span_id,
            agent_id=agent_id,
            role=role,
            runtime=runtime,
            pid=pid,
        )

    def agent_end(
        self,
        *,
        span_id: str,
        exit_code: int,
        output: str,
        duration_ms: int,
    ) -> None:
        """Emit ``agent_end``.  Stores output as artifact."""
        output_ref = self.store_artifact(output)
        self.emit(
            "agent_end",
            span_id,
            exit_code=exit_code,
            output_ref=output_ref,
            duration_ms=duration_ms,
        )
