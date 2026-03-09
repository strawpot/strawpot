"""SSE utilities and agent tree state builder."""

import json
from dataclasses import dataclass, field


def format_sse(event_id: int, data: dict) -> str:
    """Format a single SSE event string."""
    payload = json.dumps(data, separators=(",", ":"))
    return f"id: {event_id}\ndata: {payload}\n\n"


def sse_retry(ms: int = 3000) -> str:
    """Format an SSE retry directive."""
    return f"retry: {ms}\n\n"


@dataclass
class TreeNode:
    agent_id: str
    role: str
    runtime: str
    status: str  # "running" | "completed" | "failed"
    exit_code: int | None = None
    started_at: str | None = None
    duration_ms: int | None = None
    parent: str | None = None


@dataclass
class PendingDelegation:
    role: str
    requested_by: str | None
    span_id: str


@dataclass
class DeniedDelegation:
    role: str
    reason: str
    span_id: str


class TreeState:
    """Accumulates agent tree state from session.json + trace.jsonl."""

    def __init__(self) -> None:
        self.nodes: dict[str, TreeNode] = {}
        self.pending: dict[str, PendingDelegation] = {}
        self.denied: list[DeniedDelegation] = []
        # Correlation maps
        self._span_to_agent: dict[str, str] = {}
        self._span_to_parent_agent: dict[str, str | None] = {}
        self._session_span: str | None = None
        self._session_ended: bool = False

    def load_session_json(self, data: dict) -> None:
        """Merge root agent info from session.json."""
        for agent_id, info in data.get("agents", {}).items():
            if agent_id not in self.nodes:
                self.nodes[agent_id] = TreeNode(
                    agent_id=agent_id,
                    role=info.get("role", "unknown"),
                    runtime=info.get("runtime", "unknown"),
                    status="running",
                    started_at=info.get("started_at"),
                    parent=info.get("parent"),
                )

    def process_event(self, event: dict) -> None:
        """Process a single trace event and update state."""
        etype = event.get("event")
        data = event.get("data", {})
        span_id = event.get("span_id")
        parent_span = event.get("parent_span")

        if etype == "session_start":
            self._session_span = span_id

        elif etype == "delegate_start":
            parent_agent_id = self._find_agent_for_span(parent_span)
            self.pending[span_id] = PendingDelegation(
                role=data.get("role", "unknown"),
                requested_by=parent_agent_id,
                span_id=span_id,
            )
            self._span_to_parent_agent[span_id] = parent_agent_id

        elif etype == "agent_spawn":
            agent_id = data.get("agent_id", "")
            runtime = data.get("runtime", "unknown")
            parent_agent_id = self._span_to_parent_agent.get(span_id)
            pending = self.pending.pop(span_id, None)
            role = pending.role if pending else data.get("role", "unknown")
            self.nodes[agent_id] = TreeNode(
                agent_id=agent_id,
                role=role,
                runtime=runtime,
                status="running",
                started_at=event.get("ts"),
                parent=parent_agent_id,
            )
            self._span_to_agent[span_id] = agent_id

        elif etype == "agent_end":
            agent_id = self._span_to_agent.get(span_id)
            if agent_id and agent_id in self.nodes:
                node = self.nodes[agent_id]
                exit_code = data.get("exit_code", 1)
                node.exit_code = exit_code
                node.duration_ms = data.get("duration_ms")
                node.status = "completed" if exit_code == 0 else "failed"

        elif etype == "delegate_end":
            agent_id = self._span_to_agent.get(span_id)
            if agent_id and agent_id in self.nodes:
                node = self.nodes[agent_id]
                exit_code = data.get("exit_code", 1)
                node.exit_code = exit_code
                node.duration_ms = data.get("duration_ms")
                node.status = "completed" if exit_code == 0 else "failed"
            self.pending.pop(span_id, None)

        elif etype == "delegate_denied":
            self.denied.append(DeniedDelegation(
                role=data.get("role", "unknown"),
                reason=data.get("reason", "unknown"),
                span_id=span_id or "",
            ))

        elif etype == "session_end":
            self._session_ended = True
            for node in self.nodes.values():
                if node.parent is None and node.status == "running":
                    node.status = "completed"
                    node.duration_ms = data.get("duration_ms")

    def _find_agent_for_span(self, span_id: str | None) -> str | None:
        """Find the agent_id that owns a given span_id."""
        if span_id is None:
            return None
        agent_id = self._span_to_agent.get(span_id)
        if agent_id:
            return agent_id
        if span_id == self._session_span:
            for aid, node in self.nodes.items():
                if node.parent is None:
                    return aid
        return None

    @property
    def is_terminal(self) -> bool:
        """Whether the session has ended."""
        return self._session_ended

    def to_dict(self) -> dict:
        """Serialize to the SSE payload format."""
        return {
            "nodes": [
                {
                    "agent_id": n.agent_id,
                    "role": n.role,
                    "runtime": n.runtime,
                    "status": n.status,
                    "exit_code": n.exit_code,
                    "started_at": n.started_at,
                    "duration_ms": n.duration_ms,
                    "parent": n.parent,
                }
                for n in self.nodes.values()
            ],
            "pending_delegations": [
                {
                    "role": p.role,
                    "requested_by": p.requested_by,
                    "span_id": p.span_id,
                }
                for p in self.pending.values()
            ],
            "denied_delegations": [
                {
                    "role": d.role,
                    "reason": d.reason,
                    "span_id": d.span_id,
                }
                for d in self.denied
            ],
        }
