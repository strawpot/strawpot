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
        self, *, run_id: str, role: str, runtime: str, isolation: str,
        task: str = "",
    ) -> str:
        """Emit ``session_start``.  Stores task as artifact.  Returns the root span_id."""
        span_id = self._new_span_id()
        task_ref = self.store_artifact(task)
        self.emit(
            "session_start",
            span_id,
            run_id=run_id,
            role=role,
            runtime=runtime,
            isolation=isolation,
            task_ref=task_ref,
        )
        return span_id

    def session_end(
        self, *, span_id: str, merge_strategy: str, duration_ms: int,
        output: str = "", exit_code: int = 0,
        files_changed: list[str] | None = None,
    ) -> None:
        """Emit ``session_end``.  Stores output as artifact."""
        output_ref = self.store_artifact(output)
        self.emit(
            "session_end",
            span_id,
            merge_strategy=merge_strategy,
            duration_ms=duration_ms,
            output_ref=output_ref,
            exit_code=exit_code,
            files_changed=files_changed or [],
        )

    def delegate_start(
        self,
        *,
        role: str,
        parent_span: str,
        context: str,
        depth: int = 0,
        session_id: str = "",
        parent_agent_id: str | None = None,
        cache_hit: bool = False,
    ) -> str:
        """Emit ``delegate_start``.  Stores context as artifact.  Returns new span_id."""
        span_id = self._new_span_id()
        context_ref = self.store_artifact(context)
        self.emit(
            "delegate_start",
            span_id,
            parent_span=parent_span,
            role=role,
            depth=depth,
            context_ref=context_ref,
            session_id=session_id,
            parent_agent_id=parent_agent_id,
            cache_hit=cache_hit,
        )
        return span_id

    def delegate_end(
        self,
        *,
        span_id: str,
        exit_code: int,
        duration_ms: int,
        output: str = "",
        role: str = "",
        session_id: str = "",
        agent_id: str = "",
        cache_hit: bool = False,
    ) -> None:
        """Emit ``delegate_end``.  Stores output as artifact."""
        output_ref = self.store_artifact(output)
        self.emit(
            "delegate_end",
            span_id,
            exit_code=exit_code,
            duration_ms=duration_ms,
            output_ref=output_ref,
            role=role,
            session_id=session_id,
            agent_id=agent_id,
            cache_hit=cache_hit,
        )

    def delegate_denied(
        self, *, role: str, parent_span: str, reason: str, depth: int = 0
    ) -> None:
        """Emit ``delegate_denied``."""
        span_id = self._new_span_id()
        self.emit(
            "delegate_denied",
            span_id,
            parent_span=parent_span,
            role=role,
            reason=reason,
            depth=depth,
        )

    def memory_get(
        self,
        *,
        span_id: str,
        provider: str,
        session_id: str,
        agent_id: str,
        role: str,
        behavior_ref: str = "",
        task: str = "",
        cards: list,
        card_count: int,
        parent_agent_id: str | None = None,
    ) -> None:
        """Emit ``memory_get``.  Stores serialised cards as artifact."""
        cards_content = json.dumps([str(c) for c in cards]) if cards else ""
        cards_ref = self.store_artifact(cards_content)
        behavior_artifact = self.store_artifact(behavior_ref)
        task_ref = self.store_artifact(task)
        self.emit(
            "memory_get",
            span_id,
            provider=provider,
            session_id=session_id,
            agent_id=agent_id,
            role=role,
            behavior_ref=behavior_artifact,
            task_ref=task_ref,
            cards_ref=cards_ref,
            card_count=card_count,
            parent_agent_id=parent_agent_id,
        )

    def memory_remember(
        self,
        *,
        span_id: str,
        provider: str,
        session_id: str,
        agent_id: str,
        role: str,
        content: str = "",
        keywords: list[str] | None = None,
        scope: str = "",
        status: str = "",
        entry_id: str = "",
        parent_agent_id: str | None = None,
    ) -> None:
        """Emit ``memory_remember``.  Stores content as artifact."""
        content_ref = self.store_artifact(content)
        self.emit(
            "memory_remember",
            span_id,
            provider=provider,
            session_id=session_id,
            agent_id=agent_id,
            role=role,
            content_ref=content_ref,
            keywords=keywords or [],
            scope=scope,
            status=status,
            entry_id=entry_id,
            parent_agent_id=parent_agent_id,
        )

    def memory_recall(
        self,
        *,
        span_id: str,
        provider: str,
        session_id: str,
        agent_id: str,
        role: str,
        query: str = "",
        scope: str = "",
        result_count: int = 0,
        parent_agent_id: str | None = None,
    ) -> None:
        """Emit ``memory_recall``."""
        self.emit(
            "memory_recall",
            span_id,
            provider=provider,
            session_id=session_id,
            agent_id=agent_id,
            role=role,
            query=query,
            scope=scope,
            result_count=result_count,
            parent_agent_id=parent_agent_id,
        )

    def memory_dump(
        self,
        *,
        span_id: str,
        provider: str,
        session_id: str,
        agent_id: str,
        role: str,
        behavior_ref: str = "",
        task: str = "",
        status: str = "",
        output: str = "",
        parent_agent_id: str | None = None,
    ) -> None:
        """Emit ``memory_dump``.  Stores behavior_ref and output as artifacts."""
        behavior_artifact = self.store_artifact(behavior_ref)
        output_ref = self.store_artifact(output)
        task_ref = self.store_artifact(task)
        self.emit(
            "memory_dump",
            span_id,
            provider=provider,
            session_id=session_id,
            agent_id=agent_id,
            role=role,
            behavior_ref=behavior_artifact,
            task_ref=task_ref,
            status=status,
            output_ref=output_ref,
            parent_agent_id=parent_agent_id,
        )

    def agent_spawn(
        self,
        *,
        span_id: str,
        agent_id: str,
        role: str,
        runtime: str,
        pid: int | None,
        working_dir: str = "",
        agent_workspace_dir: str = "",
        skills_dirs: list[str] | None = None,
        roles_dirs: list[str] | None = None,
        files_dirs: list[str] | None = None,
        task: str = "",
        context: str = "",
        depth: int = 0,
    ) -> None:
        """Emit ``agent_spawn``.  Stores context and task as artifacts."""
        context_ref = self.store_artifact(context)
        task_ref = self.store_artifact(task)
        self.emit(
            "agent_spawn",
            span_id,
            agent_id=agent_id,
            role=role,
            runtime=runtime,
            pid=pid,
            working_dir=working_dir,
            agent_workspace_dir=agent_workspace_dir,
            skills_dirs=skills_dirs or [],
            roles_dirs=roles_dirs or [],
            files_dirs=files_dirs or [],
            task_ref=task_ref,
            context_ref=context_ref,
            depth=depth,
        )

    def agent_end(
        self,
        *,
        span_id: str,
        exit_code: int,
        output: str,
        duration_ms: int,
        agent_id: str = "",
        role: str = "",
        session_id: str = "",
    ) -> None:
        """Emit ``agent_end``.  Stores output as artifact."""
        output_ref = self.store_artifact(output)
        self.emit(
            "agent_end",
            span_id,
            exit_code=exit_code,
            output_ref=output_ref,
            duration_ms=duration_ms,
            agent_id=agent_id,
            role=role,
            session_id=session_id,
        )

    def ask_user_start(
        self,
        *,
        parent_span: str,
        request_id: str,
        question: str = "",
        agent_id: str = "",
        role: str = "",
        session_id: str = "",
    ) -> str:
        """Emit ``ask_user_start``.  Stores question as artifact.  Returns new span_id."""
        span_id = self._new_span_id()
        question_ref = self.store_artifact(question)
        self.emit(
            "ask_user_start",
            span_id,
            parent_span=parent_span,
            request_id=request_id,
            question_ref=question_ref,
            agent_id=agent_id,
            role=role,
            session_id=session_id,
        )
        return span_id

    def ask_user_end(
        self,
        *,
        span_id: str,
        request_id: str,
        answer: str = "",
        duration_ms: int = 0,
        agent_id: str = "",
        role: str = "",
        session_id: str = "",
    ) -> None:
        """Emit ``ask_user_end``.  Stores answer as artifact."""
        answer_ref = self.store_artifact(answer)
        self.emit(
            "ask_user_end",
            span_id,
            request_id=request_id,
            answer_ref=answer_ref,
            duration_ms=duration_ms,
            agent_id=agent_id,
            role=role,
            session_id=session_id,
        )
