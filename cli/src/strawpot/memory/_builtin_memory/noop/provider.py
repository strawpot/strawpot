"""Noop memory provider — returns empty context and discards dumps."""

from strawpot_memory.memory_protocol import DumpReceipt, GetResult, RememberResult


class NoopMemoryProvider:
    """No-op provider used when no memory provider is configured."""

    name = "noop"

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
        return GetResult()

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
        return DumpReceipt()

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
        return RememberResult(status="accepted")
