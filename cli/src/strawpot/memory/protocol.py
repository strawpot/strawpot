"""Memory protocol — types shared across all memory provider implementations."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class MemoryKind(str, Enum):
    """Memory type tag for context cards."""

    PM = "PM"
    SM = "SM"
    STM = "STM"
    RM = "RM"
    EM = "EM"


@dataclass
class ContextCard:
    """Single unit of context returned by memory.get."""

    kind: MemoryKind
    content: str
    source: str = ""


@dataclass
class ControlSignal:
    """Advisory signals returned alongside context cards."""

    risk_level: str = "normal"
    suggested_next: str = ""
    policy_flags: dict[str, str] = field(default_factory=dict)


@dataclass
class GetResult:
    """Full output of a memory.get call."""

    context_cards: list[ContextCard] = field(default_factory=list)
    control_signals: ControlSignal = field(default_factory=ControlSignal)
    context_hash: str = ""
    sources_used: list[str] = field(default_factory=list)


@dataclass
class DumpReceipt:
    """Mandatory receipt returned by memory.dump."""

    em_event_ids: list[str] = field(default_factory=list)


@dataclass
class RememberResult:
    """Result returned by memory.remember."""

    status: str = ""  # "accepted" | "duplicate" | "queued"
    entry_id: str = ""


@runtime_checkable
class MemoryProvider(Protocol):
    """Interface that every memory provider must implement."""

    name: str

    def get(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        behavior_ref: str,
        task: str,
        budget: int | None = None,
        parent_agent_id: str | None = None,
    ) -> GetResult:
        """Retrieve context cards and control signals before spawning an agent.

        Args:
            session_id: Session worktree identifier.
            agent_id: Unique agent instance identifier.
            role: Role slug for the agent being spawned.
            behavior_ref: Loaded role description text.
            task: Task text describing what the agent should do.
            budget: Token budget hint for the provider (None if unknown).
            parent_agent_id: Parent agent instance id, if delegated.
        """
        ...

    def dump(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        behavior_ref: str,
        task: str,
        status: str,
        output: str,
        tool_trace: str = "",
        parent_agent_id: str | None = None,
        artifacts: dict[str, str] | None = None,
    ) -> DumpReceipt:
        """Record agent results after completion.

        Args:
            session_id: Session worktree identifier.
            agent_id: Unique agent instance identifier.
            role: Role slug for the completed agent.
            behavior_ref: Loaded role description text.
            task: Task text the agent was given.
            status: Outcome status (success/failure/timeout).
            output: Assistant output text.
            tool_trace: Tool call trace text.
            parent_agent_id: Parent agent instance id, if delegated.
            artifacts: Additional artifacts (commit hash, patch refs, etc.).
        """
        ...

    def remember(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        content: str,
        keywords: list[str] | None = None,
        scope: str = "project",
    ) -> RememberResult:
        """Persist knowledge during agent execution.

        Args:
            session_id: Session worktree identifier.
            agent_id: Unique agent instance identifier.
            role: Role slug for the calling agent.
            content: The knowledge to persist.
            keywords: Optional keywords for retrieval matching.
                Empty or None means always-relevant (SM behavior).
            scope: One of "global", "project", or "role".
        """
        ...
