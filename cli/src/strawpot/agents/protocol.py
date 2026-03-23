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
class TokenUsage:
    """Token usage from an agent run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float | None = None
    model: str = ""


@dataclass
class AgentResult:
    """Outcome returned when an agent completes."""

    summary: str
    output: str = ""
    exit_code: int = 0
    usage: TokenUsage | None = None


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
        files_dirs: list[str],
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
            skills_dirs: Directories containing staged skill subdirectories.
            roles_dirs: Directories containing staged role subdirectories.
                Typically includes the role's own deps dir and optionally
                the requester role dir.
            files_dirs: Project files directories
                (e.g. ``<project>/.strawpot/files/``). Empty list if none.
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

    def interrupt(self, handle: AgentHandle) -> bool:
        """Send a soft interrupt to cancel the agent's current task.

        Returns ``True`` if the interrupt was explicitly forwarded to the
        agent (e.g. via ``tmux send-keys``).  Returns ``False`` if the
        agent already received the signal from the OS (direct mode) or
        does not support interrupt (non-interactive).

        The session layer uses the return value to decide whether to
        stay at the interrupt level or escalate directly to shutdown.
        """
        ...
