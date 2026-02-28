"""Tests for strawpot.agents.interactive (InteractiveWrapperRuntime)."""

import json
import subprocess
import sys
from unittest.mock import MagicMock, call, patch

import pytest

from strawpot.agents.interactive import (
    InteractiveWrapperRuntime,
    _session_name,
    _tmux,
)
from strawpot.agents.protocol import AgentHandle, AgentResult
from strawpot.agents.wrapper import WrapperRuntime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_completed(stdout="", returncode=0):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.stderr = ""
    r.returncode = returncode
    return r


def _make_inner():
    """Create a mock WrapperRuntime."""
    inner = MagicMock(spec=WrapperRuntime)
    inner.name = "claude-code"
    inner.spec = MagicMock()
    inner.spec.config = {"model": "claude-sonnet-4-6"}
    return inner


# ---------------------------------------------------------------------------
# _session_name
# ---------------------------------------------------------------------------


def test_session_name_long():
    assert _session_name("abcdef1234567890") == "strawpot-abcdef12"


def test_session_name_short():
    assert _session_name("short") == "strawpot-short"


# ---------------------------------------------------------------------------
# spawn
# ---------------------------------------------------------------------------


def test_spawn_calls_build_then_tmux(monkeypatch):
    """spawn calls <wrapper> build, then launches tmux new-session."""
    inner = _make_inner()
    inner._run_subcommand.return_value = {
        "cmd": ["claude", "-p", "fix bug"],
        "cwd": "/project",
    }

    tmux_calls = []

    def fake_run(cmd, **kwargs):
        tmux_calls.append(cmd)
        if "display-message" in cmd:
            return _mock_completed(stdout="12345")
        return _mock_completed()

    monkeypatch.setattr("subprocess.run", fake_run)

    runtime = InteractiveWrapperRuntime(inner)
    handle = runtime.spawn(
        agent_id="abc12345",
        working_dir="/project",
        agent_workspace_dir="/tmp/workspace",
        role_prompt="You are a coder.",
        memory_prompt="Context.",
        skills_dirs=[],
        roles_dirs=[],
        task="fix bug",
        env={},
    )

    # Verify build was called
    build_call = inner._run_subcommand.call_args
    args = build_call[0][0]
    assert args[0] == "build"
    assert "--agent-id" in args
    assert "--task" in args

    # Verify tmux new-session
    tmux_cmd = tmux_calls[0]
    assert tmux_cmd[0] == "tmux"
    assert tmux_cmd[1] == "new-session"
    assert "-d" in tmux_cmd
    assert "-s" in tmux_cmd
    session_idx = tmux_cmd.index("-s") + 1
    assert tmux_cmd[session_idx] == "strawpot-abc12345"

    # After "--", the claude command from build
    sep_idx = tmux_cmd.index("--")
    claude_args = tmux_cmd[sep_idx + 1:]
    assert claude_args == ["claude", "-p", "fix bug"]

    # Handle
    assert handle.agent_id == "abc12345"
    assert handle.metadata["session"] == "strawpot-abc12345"


def test_spawn_uses_cwd_from_build(monkeypatch):
    """spawn passes cwd from build response to tmux -c."""
    inner = _make_inner()
    inner._run_subcommand.return_value = {
        "cmd": ["claude"],
        "cwd": "/custom/path",
    }

    tmux_calls = []

    def fake_run(cmd, **kwargs):
        tmux_calls.append(cmd)
        return _mock_completed(stdout="1")

    monkeypatch.setattr("subprocess.run", fake_run)

    runtime = InteractiveWrapperRuntime(inner)
    runtime.spawn(
        agent_id="cwd001",
        working_dir="/project",
        agent_workspace_dir="/tmp/workspace",
        role_prompt="",
        memory_prompt="",
        skills_dirs=[],
        roles_dirs=[],
        task="",
        env={},
    )

    tmux_cmd = tmux_calls[0]
    cwd_idx = tmux_cmd.index("-c") + 1
    assert tmux_cmd[cwd_idx] == "/custom/path"


def test_spawn_falls_back_to_working_dir(monkeypatch):
    """When build doesn't return cwd, uses working_dir."""
    inner = _make_inner()
    inner._run_subcommand.return_value = {
        "cmd": ["claude"],
    }

    tmux_calls = []

    def fake_run(cmd, **kwargs):
        tmux_calls.append(cmd)
        return _mock_completed(stdout="1")

    monkeypatch.setattr("subprocess.run", fake_run)

    runtime = InteractiveWrapperRuntime(inner)
    runtime.spawn(
        agent_id="fb001",
        working_dir="/fallback",
        agent_workspace_dir="/tmp/workspace",
        role_prompt="",
        memory_prompt="",
        skills_dirs=[],
        roles_dirs=[],
        task="",
        env={},
    )

    tmux_cmd = tmux_calls[0]
    cwd_idx = tmux_cmd.index("-c") + 1
    assert tmux_cmd[cwd_idx] == "/fallback"


def test_spawn_tmux_failure_raises(monkeypatch):
    """spawn raises RuntimeError if tmux new-session fails."""
    inner = _make_inner()
    inner._run_subcommand.return_value = {"cmd": ["claude"], "cwd": "/p"}

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: _mock_completed(returncode=1, stdout="error"),
    )

    runtime = InteractiveWrapperRuntime(inner)
    with pytest.raises(RuntimeError, match="tmux new-session failed"):
        runtime.spawn(
            agent_id="fail01",
            working_dir="/p",
            agent_workspace_dir="/tmp/workspace",
            role_prompt="",
            memory_prompt="",
            skills_dirs=[],
            roles_dirs=[],
            task="",
            env={},
        )


def test_spawn_passes_env(monkeypatch):
    """spawn merges env into subprocess environment."""
    inner = _make_inner()
    inner._run_subcommand.return_value = {"cmd": ["claude"], "cwd": "/p"}

    captured_env = {}

    def fake_run(cmd, **kwargs):
        if "env" in kwargs and kwargs["env"] is not None:
            captured_env.update(kwargs["env"])
        return _mock_completed(stdout="1")

    monkeypatch.setattr("subprocess.run", fake_run)

    runtime = InteractiveWrapperRuntime(inner)
    runtime.spawn(
        agent_id="env001",
        working_dir="/p",
        agent_workspace_dir="/tmp/workspace",
        role_prompt="",
        memory_prompt="",
        skills_dirs=[],
        roles_dirs=[],
        task="",
        env={"ANTHROPIC_API_KEY": "sk-test"},
    )

    assert captured_env.get("ANTHROPIC_API_KEY") == "sk-test"


# ---------------------------------------------------------------------------
# wait
# ---------------------------------------------------------------------------


def test_wait_polls_until_session_exits(monkeypatch):
    """wait polls tmux has-session until it returns non-zero."""
    poll_count = 0

    def fake_run(cmd, **kwargs):
        nonlocal poll_count
        if "has-session" in cmd:
            poll_count += 1
            if poll_count >= 3:
                return _mock_completed(returncode=1)
            return _mock_completed()
        if "capture-pane" in cmd:
            return _mock_completed(stdout="captured output")
        return _mock_completed()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("time.sleep", lambda _: None)

    runtime = InteractiveWrapperRuntime(_make_inner())
    handle = AgentHandle(
        agent_id="wait001",
        runtime_name="claude-code",
        pid=None,
        metadata={"session": "strawpot-wait0001"},
    )
    result = runtime.wait(handle)

    assert result.summary == "Session ended"
    assert result.output == "captured output"
    assert poll_count == 3


def test_wait_with_timeout(monkeypatch):
    """wait respects timeout and stops polling."""
    elapsed = {"value": 0.0}

    def fake_run(cmd, **kwargs):
        if "has-session" in cmd:
            return _mock_completed()  # always alive
        if "capture-pane" in cmd:
            return _mock_completed(stdout="")
        return _mock_completed()

    def fake_sleep(secs):
        elapsed["value"] += secs

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("time.sleep", fake_sleep)

    runtime = InteractiveWrapperRuntime(_make_inner())
    handle = AgentHandle(
        agent_id="tmout01",
        runtime_name="claude-code",
        pid=None,
        metadata={"session": "strawpot-tmout001"},
    )
    result = runtime.wait(handle, timeout=2.0)

    assert result.summary == "Session ended"
    assert elapsed["value"] >= 2.0


# ---------------------------------------------------------------------------
# is_alive
# ---------------------------------------------------------------------------


def test_is_alive_true(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: _mock_completed(),
    )

    runtime = InteractiveWrapperRuntime(_make_inner())
    handle = AgentHandle(
        agent_id="alive01",
        runtime_name="claude-code",
        pid=None,
        metadata={"session": "strawpot-alive001"},
    )
    assert runtime.is_alive(handle) is True


def test_is_alive_false(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: _mock_completed(returncode=1),
    )

    runtime = InteractiveWrapperRuntime(_make_inner())
    handle = AgentHandle(
        agent_id="alive02",
        runtime_name="claude-code",
        pid=None,
        metadata={"session": "strawpot-alive002"},
    )
    assert runtime.is_alive(handle) is False


# ---------------------------------------------------------------------------
# kill
# ---------------------------------------------------------------------------


def test_kill_sends_tmux_kill_session(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _mock_completed()

    monkeypatch.setattr("subprocess.run", fake_run)

    runtime = InteractiveWrapperRuntime(_make_inner())
    handle = AgentHandle(
        agent_id="kill01",
        runtime_name="claude-code",
        pid=None,
        metadata={"session": "strawpot-kill0001"},
    )
    runtime.kill(handle)

    assert any(
        cmd[:2] == ["tmux", "kill-session"] for cmd in calls
    )


# ---------------------------------------------------------------------------
# attach
# ---------------------------------------------------------------------------


def test_attach_calls_tmux_attach(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _mock_completed()

    monkeypatch.setattr("subprocess.run", fake_run)

    runtime = InteractiveWrapperRuntime(_make_inner())
    handle = AgentHandle(
        agent_id="att01",
        runtime_name="claude-code",
        pid=None,
        metadata={"session": "strawpot-att00001"},
    )
    runtime.attach(handle)

    assert calls[0][:2] == ["tmux", "attach-session"]
    assert "-t" in calls[0]
    assert "strawpot-att00001" in calls[0]


# ---------------------------------------------------------------------------
# session name derivation
# ---------------------------------------------------------------------------


def test_session_from_metadata(monkeypatch):
    """is_alive uses session from metadata, not derived from agent_id."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _mock_completed()

    monkeypatch.setattr("subprocess.run", fake_run)

    runtime = InteractiveWrapperRuntime(_make_inner())
    handle = AgentHandle(
        agent_id="x",
        runtime_name="claude-code",
        pid=None,
        metadata={"session": "custom-session"},
    )
    runtime.is_alive(handle)

    assert "custom-session" in calls[0]
