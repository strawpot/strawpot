"""Tests for strawpot.agents.wrapper."""

import json
import subprocess
from unittest.mock import MagicMock

import pytest

from strawpot.agents.protocol import AgentHandle, AgentResult, AgentRuntime
from strawpot.agents.registry import AgentSpec
from strawpot.agents.wrapper import WrapperRuntime


def _make_spec(**overrides) -> AgentSpec:
    """Build a minimal AgentSpec for testing."""
    defaults = {
        "name": "test-agent",
        "version": "1.0.0",
        "wrapper_cmd": ["/usr/bin/fake-wrapper"],
        "config": {"model": "gpt-4"},
    }
    return AgentSpec(**{**defaults, **overrides})


def _mock_run(stdout: str, returncode: int = 0, stderr: str = ""):
    """Create a mock for subprocess.run that returns the given output."""
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


# --- Protocol conformance ---


def test_wrapper_satisfies_protocol():
    rt = WrapperRuntime(_make_spec())
    assert isinstance(rt, AgentRuntime)


def test_wrapper_name():
    rt = WrapperRuntime(_make_spec(name="my-agent"))
    assert rt.name == "my-agent"


# --- spawn ---


def test_spawn_returns_handle(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _mock_run('{"pid": 42, "metadata": {"session": "s1"}}'),
    )
    rt = WrapperRuntime(_make_spec())
    handle = rt.spawn(
        agent_id="a1",
        working_dir="/work",
        role_prompt="You are a coder.",
        memory_prompt="Previous context.",
        skills_dirs=["/skills/a"],
        roles_dirs=["/roles"],
        task="fix bug",
        env={"DENDEN_ADDR": "127.0.0.1:9700"},
    )
    assert isinstance(handle, AgentHandle)
    assert handle.agent_id == "a1"
    assert handle.runtime_name == "test-agent"
    assert handle.pid == 42
    assert handle.metadata == {"session": "s1"}


def test_spawn_builds_correct_args(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _mock_run('{"pid": 1}')

    monkeypatch.setattr("subprocess.run", fake_run)
    spec = _make_spec(
        wrapper_cmd=["/bin/wrap", "--verbose"],
        config={"model": "claude-sonnet-4-6", "temperature": 0.5},
    )
    rt = WrapperRuntime(spec)
    rt.spawn(
        agent_id="a1",
        working_dir="/w",
        role_prompt="role text",
        memory_prompt="memory text",
        skills_dirs=["/s1", "/s2"],
        roles_dirs=["/r1"],
        task="do stuff",
        env={"K1": "V1", "K2": "V2"},
    )
    cmd = captured["cmd"]
    # Wrapper command prefix
    assert cmd[0] == "/bin/wrap"
    assert cmd[1] == "--verbose"
    # Subcommand
    assert cmd[2] == "spawn"
    # Protocol args
    assert "--agent-id" in cmd
    assert cmd[cmd.index("--agent-id") + 1] == "a1"
    assert cmd[cmd.index("--working-dir") + 1] == "/w"
    assert cmd[cmd.index("--role-prompt") + 1] == "role text"
    assert cmd[cmd.index("--memory-prompt") + 1] == "memory text"
    assert cmd[cmd.index("--task") + 1] == "do stuff"
    # Config as JSON
    config_json = cmd[cmd.index("--config") + 1]
    assert json.loads(config_json) == {"model": "claude-sonnet-4-6", "temperature": 0.5}
    # Multiple --skills-dir
    skills_indices = [i for i, v in enumerate(cmd) if v == "--skills-dir"]
    assert len(skills_indices) == 2
    assert cmd[skills_indices[0] + 1] == "/s1"
    assert cmd[skills_indices[1] + 1] == "/s2"
    # Single --roles-dir
    roles_indices = [i for i, v in enumerate(cmd) if v == "--roles-dir"]
    assert len(roles_indices) == 1
    assert cmd[roles_indices[0] + 1] == "/r1"
    # Env vars passed via subprocess env, not CLI args
    assert "--env" not in cmd
    sub_env = captured["kwargs"]["env"]
    assert sub_env["K1"] == "V1"
    assert sub_env["K2"] == "V2"


def test_spawn_no_skills_or_roles(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_run('{"pid": 1}')

    monkeypatch.setattr("subprocess.run", fake_run)
    rt = WrapperRuntime(_make_spec())
    rt.spawn(
        agent_id="a1",
        working_dir="/w",
        role_prompt="",
        memory_prompt="",
        skills_dirs=[],
        roles_dirs=[],
        task="",
        env={},
    )
    cmd = captured["cmd"]
    assert "--skills-dir" not in cmd
    assert "--roles-dir" not in cmd


def test_spawn_failure(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _mock_run("", returncode=1, stderr="wrapper crashed"),
    )
    rt = WrapperRuntime(_make_spec())
    with pytest.raises(RuntimeError, match="failed.*exit 1"):
        rt.spawn(
            agent_id="a1",
            working_dir="/w",
            role_prompt="",
            memory_prompt="",
            skills_dirs=[],
            roles_dirs=[],
            task="",
            env={},
        )


def test_spawn_invalid_json(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _mock_run("not json at all"),
    )
    rt = WrapperRuntime(_make_spec())
    with pytest.raises(RuntimeError, match="invalid JSON"):
        rt.spawn(
            agent_id="a1",
            working_dir="/w",
            role_prompt="",
            memory_prompt="",
            skills_dirs=[],
            roles_dirs=[],
            task="",
            env={},
        )


# --- wait ---


def test_wait_returns_result(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _mock_run(
            '{"summary": "done", "output": "log output", "exit_code": 0}'
        ),
    )
    rt = WrapperRuntime(_make_spec())
    handle = AgentHandle(agent_id="a1", runtime_name="test-agent", pid=42)
    result = rt.wait(handle)
    assert isinstance(result, AgentResult)
    assert result.summary == "done"
    assert result.output == "log output"
    assert result.exit_code == 0


def test_wait_with_timeout(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _mock_run('{"summary": "done", "output": "", "exit_code": 0}')

    monkeypatch.setattr("subprocess.run", fake_run)
    rt = WrapperRuntime(_make_spec())
    handle = AgentHandle(agent_id="a1", runtime_name="test-agent")
    rt.wait(handle, timeout=60.0)
    assert "--timeout" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--timeout") + 1] == "60.0"
    # subprocess.run itself should have timeout=None (wrapper handles it)
    assert captured["kwargs"]["timeout"] is None


def test_wait_without_timeout(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_run('{"summary": "ok", "output": "", "exit_code": 0}')

    monkeypatch.setattr("subprocess.run", fake_run)
    rt = WrapperRuntime(_make_spec())
    handle = AgentHandle(agent_id="a1", runtime_name="test-agent")
    rt.wait(handle)
    assert "--timeout" not in captured["cmd"]


# --- is_alive ---


def test_is_alive_true(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _mock_run('{"alive": true}'),
    )
    rt = WrapperRuntime(_make_spec())
    handle = AgentHandle(agent_id="a1", runtime_name="test-agent")
    assert rt.is_alive(handle) is True


def test_is_alive_false(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _mock_run('{"alive": false}'),
    )
    rt = WrapperRuntime(_make_spec())
    handle = AgentHandle(agent_id="a1", runtime_name="test-agent")
    assert rt.is_alive(handle) is False


# --- kill ---


def test_kill(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_run('{"killed": true}')

    monkeypatch.setattr("subprocess.run", fake_run)
    rt = WrapperRuntime(_make_spec())
    handle = AgentHandle(agent_id="a1", runtime_name="test-agent")
    rt.kill(handle)  # should not raise
    assert "kill" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--agent-id") + 1] == "a1"
