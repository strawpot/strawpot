from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Protocol, runtime_checkable

from .types import AgentResponse, Charter, Message

if TYPE_CHECKING:
    from .context import SessionContext
    from .session import AgentSession


@runtime_checkable
class AgentProvider(Protocol):
    """Programmatic completion provider (API / non-interactive).

    Used for background tasks, context building, and batch completions.
    Implementations: ClaudeAPIProvider.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this provider (e.g. 'claude_api')."""
        ...

    async def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 8096,
        **kwargs,
    ) -> AgentResponse:
        """Return a single completed response for the given messages."""
        ...

    def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 8096,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Yield response text chunks as they arrive."""
        ...


@runtime_checkable
class AgentSessionProvider(Protocol):
    """Interactive session provider (tmux + agentic CLI).

    Agents run with full tool access. Context is injected at session start
    via the SessionStart hook calling ``lt prime --hook``.
    Implementations: ClaudeSessionProvider.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this provider (e.g. 'claude_session')."""
        ...

    async def spawn(
        self,
        charter: Charter,
        workdir: Path,
        context: SessionContext,
    ) -> AgentSession:
        """Start a new interactive agent session.

        Writes ``.claude/settings.json`` with the SessionStart hook,
        stores runtime identity, then launches the agent process in tmux.
        """
        ...

    async def resume(
        self,
        session_name: str,
        workdir: Path,
    ) -> AgentSession:
        """Re-attach to an existing (paused/crashed) session by name."""
        ...
