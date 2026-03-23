"""Tests for strawpot.agents.protocol."""

from strawpot.agents.protocol import AgentHandle, AgentResult, AgentRuntime, TokenUsage


def test_agent_handle_defaults():
    handle = AgentHandle(agent_id="a1", runtime_name="test")
    assert handle.agent_id == "a1"
    assert handle.runtime_name == "test"
    assert handle.pid is None
    assert handle.metadata == {}


def test_agent_handle_with_all_fields():
    handle = AgentHandle(
        agent_id="a2", runtime_name="wrapper", pid=1234, metadata={"session": "s1"}
    )
    assert handle.pid == 1234
    assert handle.metadata == {"session": "s1"}


def test_agent_result_defaults():
    result = AgentResult(summary="done")
    assert result.summary == "done"
    assert result.output == ""
    assert result.exit_code == 0
    assert result.usage is None


def test_agent_result_with_all_fields():
    result = AgentResult(summary="failed", output="error log", exit_code=1)
    assert result.output == "error log"
    assert result.exit_code == 1


def test_agent_result_with_usage():
    usage = TokenUsage(
        input_tokens=5000,
        output_tokens=2000,
        cache_read_input_tokens=1500,
        cost_usd=0.05,
        model="claude-sonnet-4-20250514",
    )
    result = AgentResult(summary="done", usage=usage)
    assert result.usage is not None
    assert result.usage.input_tokens == 5000
    assert result.usage.output_tokens == 2000
    assert result.usage.cache_read_input_tokens == 1500
    assert result.usage.cache_creation_input_tokens == 0
    assert result.usage.cost_usd == 0.05
    assert result.usage.model == "claude-sonnet-4-20250514"


def test_token_usage_defaults():
    usage = TokenUsage()
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.cache_read_input_tokens == 0
    assert usage.cache_creation_input_tokens == 0
    assert usage.cost_usd is None
    assert usage.model == ""


def test_agent_runtime_protocol():
    """A class implementing all methods satisfies the runtime_checkable protocol."""

    class FakeRuntime:
        name = "fake"

        def spawn(self, *, agent_id, working_dir, role_prompt, memory_prompt, skills_dirs, roles_dirs, files_dirs, task, env):
            return AgentHandle(agent_id=agent_id, runtime_name=self.name)

        def wait(self, handle, timeout=None):
            return AgentResult(summary="ok")

        def is_alive(self, handle):
            return False

        def kill(self, handle):
            pass

        def interrupt(self, handle):
            pass

    assert isinstance(FakeRuntime(), AgentRuntime)


def test_non_runtime_fails_protocol():
    """A class missing methods does not satisfy the protocol."""

    class Incomplete:
        name = "broken"

    assert not isinstance(Incomplete(), AgentRuntime)
