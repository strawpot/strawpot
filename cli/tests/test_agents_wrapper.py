"""Tests for strawpot.agents.wrapper (WrapperRuntime with internal PID management)."""

import json
import os
import signal
import subprocess
import sys
from unittest.mock import MagicMock, mock_open, patch

import pytest

_skip_win = pytest.mark.skipif(
    sys.platform == "win32", reason="Unix signal semantics"
)

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


# --- PID helpers ---


def test_pid_file(tmp_path):
    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    assert rt._pid_file("abc123") == str(
        tmp_path / "agents" / "abc123" / ".pid"
    )


def test_log_file(tmp_path):
    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    assert rt._log_file("abc123") == str(
        tmp_path / "agents" / "abc123" / ".log"
    )


def test_write_and_read_pid(tmp_path):
    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    rt._write_pid("agent01", 42)
    assert rt._read_pid("agent01") == 42


def test_read_pid_missing(tmp_path):
    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    assert rt._read_pid("nonexistent") is None


def test_read_pid_invalid(tmp_path):
    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    pid_dir = tmp_path / "agents" / "bad"
    pid_dir.mkdir(parents=True, exist_ok=True)
    (pid_dir / ".pid").write_text("not-a-number")
    assert rt._read_pid("bad") is None


@_skip_win
def test_is_process_alive_true(monkeypatch):
    monkeypatch.setattr("strawpot._process.sys.platform", "linux")
    monkeypatch.setattr("os.kill", lambda pid, sig: None)
    assert WrapperRuntime._is_process_alive(12345) is True


@_skip_win
def test_is_process_alive_false(monkeypatch):
    def fake_kill(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr("strawpot._process.sys.platform", "linux")
    monkeypatch.setattr("os.kill", fake_kill)
    assert WrapperRuntime._is_process_alive(12345) is False


@_skip_win
def test_is_process_alive_permission_error(monkeypatch):
    def fake_kill(pid, sig):
        raise PermissionError()

    monkeypatch.setattr("strawpot._process.sys.platform", "linux")
    monkeypatch.setattr("os.kill", fake_kill)
    assert WrapperRuntime._is_process_alive(12345) is True


# --- _run_subcommand ---


def test_run_subcommand_success(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _mock_run('{"key": "value"}'),
    )
    rt = WrapperRuntime(_make_spec())
    result = rt._run_subcommand(["build", "--flag", "val"])
    assert result == {"key": "value"}


def test_run_subcommand_failure(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _mock_run("", returncode=1, stderr="wrapper crashed"),
    )
    rt = WrapperRuntime(_make_spec())
    with pytest.raises(RuntimeError, match="failed.*exit 1"):
        rt._run_subcommand(["build"])


def test_run_subcommand_invalid_json(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _mock_run("not json at all"),
    )
    rt = WrapperRuntime(_make_spec())
    with pytest.raises(RuntimeError, match="invalid JSON"):
        rt._run_subcommand(["build"])


def test_run_subcommand_passes_env(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return _mock_run('{}')

    monkeypatch.setattr("subprocess.run", fake_run)
    rt = WrapperRuntime(_make_spec())
    rt._run_subcommand(["build"], extra_env={"MY_VAR": "hello"})
    assert captured["env"]["MY_VAR"] == "hello"


# --- spawn ---


def test_spawn_calls_build_and_popen(tmp_path, monkeypatch):
    """spawn calls <wrapper> build, then launches via Popen."""
    build_captured = {}
    popen_captured = {}

    def fake_run(cmd, **kwargs):
        build_captured["cmd"] = cmd
        build_captured["env"] = kwargs.get("env")
        return _mock_run(json.dumps({
            "cmd": ["claude", "-p", "fix bug"],
            "cwd": str(tmp_path),
        }))

    mock_proc = MagicMock()
    mock_proc.pid = 54321

    def fake_popen(cmd, **kwargs):
        popen_captured["cmd"] = cmd
        popen_captured["cwd"] = kwargs.get("cwd")
        return mock_proc

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    handle = rt.spawn(
        agent_id="a1",
        working_dir=str(tmp_path),
        agent_workspace_dir=str(tmp_path / "workspace"),
        role_prompt="You are a coder.",
        memory_prompt="Previous context.",
        skills_dir="/skills",
        roles_dirs=["/roles"],
        task="fix bug",
        env={"DENDEN_ADDR": "127.0.0.1:9700"},
    )

    # Handle
    assert isinstance(handle, AgentHandle)
    assert handle.agent_id == "a1"
    assert handle.runtime_name == "test-agent"
    assert handle.pid == 54321

    # Build was called with correct args
    cmd = build_captured["cmd"]
    assert cmd[0] == "/usr/bin/fake-wrapper"
    assert cmd[1] == "build"
    assert "--agent-id" in cmd
    assert cmd[cmd.index("--agent-id") + 1] == "a1"
    assert cmd[cmd.index("--task") + 1] == "fix bug"

    # Env was passed to build
    assert build_captured["env"]["DENDEN_ADDR"] == "127.0.0.1:9700"

    # Popen was called with the translated command
    assert popen_captured["cmd"] == ["claude", "-p", "fix bug"]
    assert popen_captured["cwd"] == str(tmp_path)

    # PID file was written
    assert rt._read_pid("a1") == 54321


def test_spawn_builds_correct_protocol_args(tmp_path, monkeypatch):
    """spawn passes all protocol args to <wrapper> build."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_run(json.dumps({"cmd": ["agent"], "cwd": "/w"}))

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "subprocess.Popen", lambda cmd, **kw: MagicMock(pid=1)
    )

    spec = _make_spec(
        wrapper_cmd=["/bin/wrap", "--verbose"],
        config={"model": "claude-sonnet-4-6", "temperature": 0.5},
    )
    rt = WrapperRuntime(spec, session_dir=str(tmp_path))
    rt.spawn(
        agent_id="a1",
        working_dir="/w",
        agent_workspace_dir="/tmp/workspace",
        role_prompt="role text",
        memory_prompt="memory text",
        skills_dir="/s1",
        roles_dirs=["/r1"],
        task="do stuff",
        env={"K1": "V1"},
    )

    cmd = captured["cmd"]
    # Wrapper command prefix
    assert cmd[0] == "/bin/wrap"
    assert cmd[1] == "--verbose"
    # Subcommand
    assert cmd[2] == "build"
    # Protocol args
    assert cmd[cmd.index("--agent-id") + 1] == "a1"
    assert cmd[cmd.index("--working-dir") + 1] == "/w"
    assert cmd[cmd.index("--agent-workspace-dir") + 1] == "/tmp/workspace"
    assert cmd[cmd.index("--role-prompt") + 1] == "role text"
    assert cmd[cmd.index("--memory-prompt") + 1] == "memory text"
    assert cmd[cmd.index("--task") + 1] == "do stuff"
    # Config as JSON
    config_json = cmd[cmd.index("--config") + 1]
    assert json.loads(config_json) == {"model": "claude-sonnet-4-6", "temperature": 0.5}
    # --skills-dir and --roles-dir flags
    assert cmd[cmd.index("--skills-dir") + 1] == "/s1"
    assert cmd[cmd.index("--roles-dir") + 1] == "/r1"


def test_spawn_passes_dir_flags(tmp_path, monkeypatch):
    """spawn always passes --skills-dir and --roles-dir flags."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_run(json.dumps({"cmd": ["agent"], "cwd": "/w"}))

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "subprocess.Popen", lambda cmd, **kw: MagicMock(pid=1)
    )

    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    rt.spawn(
        agent_id="a1",
        working_dir="/w",
        agent_workspace_dir="/tmp/workspace",
        role_prompt="",
        memory_prompt="",
        skills_dir="/session/roles/impl/skills",
        roles_dirs=["/session/roles/impl/roles"],
        task="",
        env={},
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--skills-dir") + 1] == "/session/roles/impl/skills"
    assert cmd[cmd.index("--roles-dir") + 1] == "/session/roles/impl/roles"


def test_spawn_build_failure(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _mock_run("", returncode=1, stderr="wrapper crashed"),
    )
    rt = WrapperRuntime(_make_spec())
    with pytest.raises(RuntimeError, match="failed.*exit 1"):
        rt.spawn(
            agent_id="a1",
            working_dir="/w",
            agent_workspace_dir="/tmp/workspace",
            role_prompt="",
            memory_prompt="",
            skills_dir="",
            roles_dirs=[],
            task="",
            env={},
        )


def test_spawn_build_invalid_json(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _mock_run("not json at all"),
    )
    rt = WrapperRuntime(_make_spec())
    with pytest.raises(RuntimeError, match="invalid JSON"):
        rt.spawn(
            agent_id="a1",
            working_dir="/w",
            agent_workspace_dir="/tmp/workspace",
            role_prompt="",
            memory_prompt="",
            skills_dir="",
            roles_dirs=[],
            task="",
            env={},
        )


# --- wait ---


def test_wait_polls_until_exit(tmp_path, monkeypatch):
    """wait polls PID until process exits, then reads log file."""
    poll_count = 0

    def fake_is_alive(pid):
        nonlocal poll_count
        poll_count += 1
        return poll_count < 3  # alive for 2 polls, then dead

    monkeypatch.setattr(
        WrapperRuntime, "_is_process_alive", staticmethod(fake_is_alive)
    )
    monkeypatch.setattr("time.sleep", lambda _: None)

    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    # Write a log file at the expected path
    log_dir = tmp_path / "agents" / "wait01"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / ".log").write_text("captured output")

    handle = AgentHandle(agent_id="wait01", runtime_name="test-agent", pid=999)
    result = rt.wait(handle)

    assert isinstance(result, AgentResult)
    assert result.summary == "Agent completed"
    assert result.output == "captured output"
    assert result.exit_code == 0
    assert poll_count == 3


def test_wait_with_timeout(tmp_path, monkeypatch):
    """wait respects timeout and stops polling."""
    monkeypatch.setattr(
        WrapperRuntime, "_is_process_alive", staticmethod(lambda pid: True)
    )

    elapsed = {"value": 0.0}

    def fake_sleep(secs):
        elapsed["value"] += secs

    monkeypatch.setattr("time.sleep", fake_sleep)

    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    log_dir = tmp_path / "agents" / "tmout01"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / ".log").write_text("")

    handle = AgentHandle(agent_id="tmout01", runtime_name="test-agent", pid=999)
    result = rt.wait(handle, timeout=2.0)

    assert result.summary == "Agent completed"
    # Should have stopped after timeout
    assert elapsed["value"] >= 2.0


def test_wait_reads_pid_from_file(tmp_path, monkeypatch):
    """wait can read PID from file if not in handle."""
    monkeypatch.setattr(
        WrapperRuntime, "_is_process_alive", staticmethod(lambda pid: False)
    )

    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    rt._write_pid("wait02", 888)
    log_dir = tmp_path / "agents" / "wait02"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / ".log").write_text("some output")

    handle = AgentHandle(agent_id="wait02", runtime_name="test-agent")  # no pid
    result = rt.wait(handle)

    assert result.output == "some output"


def test_wait_no_pid(tmp_path):
    """wait without PID still returns output if log exists."""
    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    log_dir = tmp_path / "agents" / "nopid"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / ".log").write_text("some output")

    handle = AgentHandle(agent_id="nopid", runtime_name="test-agent")
    result = rt.wait(handle)

    assert result.output == "some output"


# --- is_alive ---


def test_is_alive_true(tmp_path, monkeypatch):
    monkeypatch.setattr(
        WrapperRuntime, "_is_process_alive", staticmethod(lambda pid: True)
    )
    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    handle = AgentHandle(agent_id="a1", runtime_name="test-agent", pid=123)
    assert rt.is_alive(handle) is True


def test_is_alive_false(tmp_path, monkeypatch):
    monkeypatch.setattr(
        WrapperRuntime, "_is_process_alive", staticmethod(lambda pid: False)
    )
    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    handle = AgentHandle(agent_id="a1", runtime_name="test-agent", pid=123)
    assert rt.is_alive(handle) is False


def test_is_alive_reads_pid_from_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        WrapperRuntime, "_is_process_alive", staticmethod(lambda pid: True)
    )
    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    rt._write_pid("a2", 456)
    handle = AgentHandle(agent_id="a2", runtime_name="test-agent")  # no pid
    assert rt.is_alive(handle) is True


def test_is_alive_no_pid(tmp_path):
    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    handle = AgentHandle(agent_id="missing", runtime_name="test-agent")
    assert rt.is_alive(handle) is False


# --- kill ---


@_skip_win
def test_kill_sends_sigterm(tmp_path, monkeypatch):
    killed_pids = []

    def fake_kill(pid, sig):
        killed_pids.append((pid, sig))

    monkeypatch.setattr("os.kill", fake_kill)

    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    handle = AgentHandle(agent_id="k1", runtime_name="test-agent", pid=777)
    rt.kill(handle)

    assert killed_pids == [(777, signal.SIGTERM)]


@_skip_win
def test_kill_reads_pid_from_file(tmp_path, monkeypatch):
    killed_pids = []

    def fake_kill(pid, sig):
        killed_pids.append((pid, sig))

    monkeypatch.setattr("os.kill", fake_kill)

    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    rt._write_pid("k2", 888)
    handle = AgentHandle(agent_id="k2", runtime_name="test-agent")  # no pid
    rt.kill(handle)

    assert killed_pids == [(888, signal.SIGTERM)]


def test_kill_no_pid(tmp_path):
    """kill with no PID does nothing (no error)."""
    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    handle = AgentHandle(agent_id="missing", runtime_name="test-agent")
    rt.kill(handle)  # should not raise


@_skip_win
def test_kill_process_already_gone(tmp_path, monkeypatch):
    def fake_kill(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr("os.kill", fake_kill)

    rt = WrapperRuntime(_make_spec(), session_dir=str(tmp_path))
    handle = AgentHandle(agent_id="k3", runtime_name="test-agent", pid=999)
    rt.kill(handle)  # should not raise


# --- setup ---


def test_setup_success(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        r = _mock_run("")
        r.returncode = 0
        return r

    monkeypatch.setattr("subprocess.run", fake_run)
    rt = WrapperRuntime(_make_spec())
    assert rt.setup() is True
    assert captured["cmd"] == ["/usr/bin/fake-wrapper", "setup"]
    # setup runs interactively — no capture_output
    assert "capture_output" not in captured["kwargs"]


def test_setup_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        r = _mock_run("")
        r.returncode = 1
        return r

    monkeypatch.setattr("subprocess.run", fake_run)
    rt = WrapperRuntime(_make_spec())
    assert rt.setup() is False
