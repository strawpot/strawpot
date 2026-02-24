from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Union

from .provider import AgentProvider, AgentSessionProvider
from .types import AgentResponse, Charter, Message

if TYPE_CHECKING:
    from .context import SessionContext
    from .session import AgentSession


class Agent:
    """An agent that delegates to either a completion provider or a session provider.

    Completion mode (``AgentProvider``)
        Call ``run()`` / ``stream()`` for programmatic back-and-forth.
        History is managed in-process.

    Session mode (``AgentSessionProvider``)
        Call ``spawn()`` to start an interactive tmux session where Claude
        runs with full tool access. Context is injected at startup via the
        ``lt prime --hook`` SessionStart hook.
    """

    def __init__(
        self,
        charter: Charter,
        provider: Union[AgentProvider, AgentSessionProvider],
    ) -> None:
        self.charter = charter
        self.provider = provider
        self._history: list[Message] = []

    # ------------------------------------------------------------------
    # Completion interface (AgentProvider)
    # ------------------------------------------------------------------

    async def run(self, message: str, *, reset: bool = False) -> AgentResponse:
        """Send a message, get a complete response, and update history."""
        self._assert_completion_provider()
        if reset:
            self._history.clear()

        self._history.append({"role": "user", "content": message})
        response = await self.provider.complete(  # type: ignore[union-attr]
            self._history,
            system=self.charter.instructions or None,
            model=self.charter.model_id,
            max_tokens=self.charter.max_tokens,
        )
        self._history.append({"role": "assistant", "content": response.content})
        return response

    async def stream(self, message: str, *, reset: bool = False) -> AsyncIterator[str]:
        """Send a message and yield response chunks; history is updated when done."""
        self._assert_completion_provider()
        if reset:
            self._history.clear()

        self._history.append({"role": "user", "content": message})
        chunks: list[str] = []
        async for chunk in self.provider.stream(  # type: ignore[union-attr]
            self._history,
            system=self.charter.instructions or None,
            model=self.charter.model_id,
            max_tokens=self.charter.max_tokens,
        ):
            chunks.append(chunk)
            yield chunk

        self._history.append({"role": "assistant", "content": "".join(chunks)})

    def reset(self) -> None:
        """Clear conversation history."""
        self._history.clear()

    @property
    def history(self) -> list[Message]:
        return list(self._history)

    # ------------------------------------------------------------------
    # Session interface (AgentSessionProvider)
    # ------------------------------------------------------------------

    async def spawn(
        self,
        workdir: Path,
        context: SessionContext,
    ) -> AgentSession:
        """Start an interactive agent session in *workdir*.

        Writes ``.loguetown/runtime/`` identity files and ``.claude/settings.json``
        (with the SessionStart hook), then launches the agent in a tmux session.

        The ``lt prime --hook`` command runs at session start and injects:
        - Charter identity and role instructions
        - All skills for this role (global → shared → role-specific)
        - The current work item (if any)
        """
        self._assert_session_provider()
        return await self.provider.spawn(  # type: ignore[union-attr]
            self.charter, workdir, context
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _assert_completion_provider(self) -> None:
        if not isinstance(self.provider, AgentProvider):
            raise TypeError(
                f"{self.charter.name!r} uses provider {self.provider.name!r} which does not "
                "support completion. Use spawn() for session-based providers."
            )

    def _assert_session_provider(self) -> None:
        if not isinstance(self.provider, AgentSessionProvider):
            raise TypeError(
                f"{self.charter.name!r} uses provider {self.provider.name!r} which does not "
                "support sessions. Use run() / stream() for completion-based providers."
            )

    def __repr__(self) -> str:
        return (
            f"Agent(name={self.charter.name!r}, "
            f"role={self.charter.role!r}, "
            f"provider={self.provider.name!r})"
        )
