"""Isolation protocol — environment setup shared across all isolator implementations."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class IsolatedEnv:
    """An isolated working environment for a session.

    All agents in a session share the same IsolatedEnv.
    """

    path: str
    branch: str | None = None


@runtime_checkable
class Isolator(Protocol):
    """Creates one isolated environment per session."""

    def create(self, *, session_id: str, base_dir: str) -> IsolatedEnv:
        """Create an isolated environment for a session.

        Args:
            session_id: Unique session identifier (used for branch/dir naming).
            base_dir: The project directory to isolate from.
        """
        ...

    def cleanup(self, env: IsolatedEnv, *, base_dir: str) -> None:
        """Remove the isolated environment and clean up resources."""
        ...


class NoneIsolator:
    """No isolation — agents work directly in the project directory."""

    def create(self, *, session_id: str, base_dir: str) -> IsolatedEnv:
        """Return base_dir as-is. No isolation setup."""
        return IsolatedEnv(path=base_dir)

    def cleanup(self, env: IsolatedEnv, *, base_dir: str) -> None:
        """No-op — nothing to clean up."""
