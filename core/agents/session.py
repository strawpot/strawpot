from __future__ import annotations

import asyncio
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .types import Charter


class SessionStatus(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


@dataclass
class SessionResult:
    status: SessionStatus
    exit_code: int | None = None
    duration_seconds: float | None = None


class AgentSession:
    """A live (or recently exited) interactive agent session backed by tmux.

    Returned by :class:`~core.agents.providers.claude_session.ClaudeSessionProvider`
    when an agent is spawned. Callers can:

    - ``await session.wait()`` — block until the session exits
    - ``session.attach()`` — hand the current terminal to the tmux session
    - ``await session.terminate()`` — forcibly kill the session
    """

    def __init__(
        self,
        session_name: str,
        workdir: Path,
        charter: Charter,
    ) -> None:
        self.session_name = session_name
        self.workdir = workdir
        self.charter = charter
        self._started_at: float = time.monotonic()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        """Return True if the tmux session still exists."""
        result = subprocess.run(
            ["tmux", "has-session", "-t", self.session_name],
            capture_output=True,
        )
        return result.returncode == 0

    @property
    def status(self) -> SessionStatus:
        return SessionStatus.RUNNING if self.is_alive else SessionStatus.COMPLETED

    async def wait(self, poll_interval: float = 2.0) -> SessionResult:
        """Poll until the tmux session disappears, then return a result."""
        while self.is_alive:
            await asyncio.sleep(poll_interval)
        duration = time.monotonic() - self._started_at
        return SessionResult(
            status=SessionStatus.COMPLETED,
            duration_seconds=duration,
        )

    def attach(self) -> None:
        """Replace the current process with a tmux attach call.

        This is a terminal operation — it hands the TTY to the agent session.
        The current Python process is replaced (exec, not fork).
        """
        import os
        os.execvp("tmux", ["tmux", "attach-session", "-t", self.session_name])

    async def terminate(self) -> None:
        """Kill the tmux session immediately."""
        proc = await asyncio.create_subprocess_exec(
            "tmux", "kill-session", "-t", self.session_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    def __repr__(self) -> str:
        alive = "alive" if self.is_alive else "exited"
        return (
            f"AgentSession(name={self.session_name!r}, "
            f"agent={self.charter.name!r}, status={alive})"
        )
