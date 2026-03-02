"""Tests for strawpot.agents.protocol."""

from strawpot.agents.protocol import AgentHandle, AgentResult, AgentRuntime


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


def test_agent_result_with_all_fields():
    result = AgentResult(summary="failed", output="error log", exit_code=1)
    assert result.output == "error log"
    assert result.exit_code == 1


def test_agent_runtime_protocol():
    """A class implementing all methods satisfies the runtime_checkable protocol."""

    class FakeRuntime:
        name = "fake"

        def spawn(self, *, agent_id, working_dir, role_prompt, memory_prompt, skills_dir, roles_dirs, task, env):
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
