"""Agent runtime protocol — types shared across all agent implementations."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class AgentHandle:
    """Reference to a running agent process."""

    agent_id: str
    runtime_name: str
    pid: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    """Outcome returned when an agent completes."""

    summary: str
    output: str = ""
    exit_code: int = 0


@runtime_checkable
class AgentRuntime(Protocol):
    """Interface that every agent runtime must implement."""

    name: str

    def spawn(
        self,
        *,
        agent_id: str,
        working_dir: str,
        agent_workspace_dir: str,
        role_prompt: str,
        memory_prompt: str,
        skills_dirs: list[str],
        roles_dirs: list[str],
        task: str,
        env: dict[str, str],
    ) -> AgentHandle:
        """Start an agent process.

        Args:
            agent_id: Unique identifier for this agent instance.
            working_dir: Session worktree path (shared by all agents).
            agent_workspace_dir: Dedicated temp workspace for this agent
                (prompt files, staged skills, scratch data).
            role_prompt: Role instructions text (body of ROLE.md).
            memory_prompt: Memory context text from memory.get ("" if none).
            skills_dirs: Directories containing resolved SKILL.md files.
            roles_dirs: Directories containing available roles for delegation.
            task: Task text. Empty string means interactive mode.
            env: Additional environment variables (DENDEN_ADDR, etc.).
        """
        ...

    def wait(
        self, handle: AgentHandle, timeout: float | None = None
    ) -> AgentResult:
        """Block until the agent finishes and return its result.

        Args:
            handle: Handle returned by spawn.
            timeout: Max seconds to wait. None means wait forever.
        """
        ...

    def is_alive(self, handle: AgentHandle) -> bool:
        """Check whether the agent process is still running."""
        ...

    def kill(self, handle: AgentHandle) -> None:
        """Forcefully terminate the agent process."""
        ...
