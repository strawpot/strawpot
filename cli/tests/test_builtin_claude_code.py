"""Tests for the built-in claude_code agent (AGENT.md + wrapper)."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from strawpot.agents.registry import parse_agent_md, resolve_agent

# Import the wrapper module directly for unit testing
WRAPPER_DIR = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "strawpot"
    / "_builtin_agents"
    / "claude_code"
)
sys.path.insert(0, str(WRAPPER_DIR))
from wrapper import (  # noqa: E402
    APPROVAL_MODE_MAP,
    _session_name,
    main,
)

sys.path.pop(0)


# ---------------------------------------------------------------------------
# AGENT.md manifest
# ---------------------------------------------------------------------------

AGENT_MD = WRAPPER_DIR / "AGENT.md"


def test_agent_md_parses():
    fm, body = parse_agent_md(AGENT_MD)
    assert fm["name"] == "claude-code"
    assert fm["metadata"]["version"] == "0.1.0"
    assert fm["metadata"]["strawpot"]["wrapper"]["script"] == "wrapper.py"


def test_agent_md_tools():
    fm, _ = parse_agent_md(AGENT_MD)
    tools = fm["metadata"]["strawpot"]["tools"]
    assert "claude" in tools
    assert "tmux" not in tools  # tmux is a strawpot dependency, not agent's


def test_agent_md_env_optional():
    fm, _ = parse_agent_md(AGENT_MD)
    env = fm["metadata"]["strawpot"]["env"]
    assert env["ANTHROPIC_API_KEY"]["required"] is False


def test_agent_md_params():
    fm, _ = parse_agent_md(AGENT_MD)
    params = fm["metadata"]["strawpot"]["params"]
    assert params["model"]["default"] == "claude-sonnet-4-6"


def test_resolve_builtin_agent(tmp_path, monkeypatch):
    """Registry finds the built-in agent as last fallback."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global"))
    spec = resolve_agent("claude_code", str(tmp_path))
    assert spec.name == "claude-code"
    assert spec.version == "0.1.0"
    assert spec.config == {"model": "claude-sonnet-4-6"}
    assert sys.executable in spec.wrapper_cmd[0]


# ---------------------------------------------------------------------------
# Wrapper helpers
# ---------------------------------------------------------------------------


def test_session_name():
    assert _session_name("abcdef1234567890") == "strawpot-abcdef12"
    assert _session_name("short") == "strawpot-short"


def test_approval_mode_map():
    assert APPROVAL_MODE_MAP["auto"] == "auto"
    assert APPROVAL_MODE_MAP["suggest"] == "default"
    assert APPROVAL_MODE_MAP["force"] == "plan"


# ---------------------------------------------------------------------------
# spawn
# ---------------------------------------------------------------------------


def _mock_run_ok(stdout: str = "", returncode: int = 0):
    """Create a mock CompletedProcess."""
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.stderr = ""
    r.returncode = returncode
    return r


def test_spawn_builds_tmux_command(tmp_path, monkeypatch, capsys):
    """spawn creates the correct tmux + claude command."""
    monkeypatch.setenv("APPROVAL_MODE", "suggest")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "tmux" and cmd[1] == "new-session":
            return _mock_run_ok()
        if cmd[0] == "tmux" and cmd[1] == "display-message":
            return _mock_run_ok(stdout="12345")
        return _mock_run_ok()

    monkeypatch.setattr("subprocess.run", fake_run)

    main([
        "spawn",
        "--agent-id", "abc12345",
        "--working-dir", str(tmp_path),
        "--role-prompt", "You are a coder.",
        "--memory-prompt", "Previous context.",
        "--task", "fix the bug",
        "--config", '{"model": "claude-opus-4-6"}',
    ])

    # Check tmux new-session was called
    tmux_call = calls[0]
    assert tmux_call[0] == "tmux"
    assert tmux_call[1] == "new-session"
    assert "-d" in tmux_call
    assert "-s" in tmux_call
    session_idx = tmux_call.index("-s") + 1
    assert tmux_call[session_idx] == "strawpot-abc12345"

    # Find claude args after "--"
    sep_idx = tmux_call.index("--")
    claude_args = tmux_call[sep_idx + 1:]
    assert claude_args[0] == "claude"
    assert "-p" in claude_args
    assert claude_args[claude_args.index("-p") + 1] == "fix the bug"
    assert "--model" in claude_args
    assert claude_args[claude_args.index("--model") + 1] == "claude-opus-4-6"
    assert "--permission-mode" in claude_args
    assert claude_args[claude_args.index("--permission-mode") + 1] == "default"

    # Check JSON output
    out = json.loads(capsys.readouterr().out)
    assert out["pid"] == 12345
    assert out["metadata"]["session"] == "strawpot-abc12345"


def test_spawn_interactive_mode(tmp_path, monkeypatch, capsys):
    """When task is empty, claude is run without -p flag."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "tmux" and cmd[1] == "display-message":
            return _mock_run_ok(stdout="999")
        return _mock_run_ok()

    monkeypatch.setattr("subprocess.run", fake_run)

    main([
        "spawn",
        "--agent-id", "inter123",
        "--working-dir", str(tmp_path),
        "--task", "",
        "--config", "{}",
    ])

    tmux_call = calls[0]
    sep_idx = tmux_call.index("--")
    claude_args = tmux_call[sep_idx + 1:]
    assert "-p" not in claude_args


def test_spawn_system_prompt_file(tmp_path, monkeypatch, capsys):
    """System prompt file is written with role + memory prompts."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: _mock_run_ok(stdout="1"),
    )

    main([
        "spawn",
        "--agent-id", "prompt01",
        "--working-dir", str(tmp_path),
        "--role-prompt", "Role text here.",
        "--memory-prompt", "Memory text here.",
        "--task", "do work",
        "--config", "{}",
    ])

    prompt_file = tmp_path / ".strawpot" / "runtime" / "prompt01-prompt.md"
    assert prompt_file.exists()
    content = prompt_file.read_text()
    assert "Role text here." in content
    assert "Memory text here." in content


def test_spawn_with_skills_dir(tmp_path, monkeypatch, capsys):
    """Skills .md files from --skills-dir are passed as --append-system-prompt."""
    # Create skill files
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "coding.md").write_text("# Coding skill")
    (skills_dir / "review.md").write_text("# Review skill")
    (skills_dir / "not-a-skill.txt").write_text("ignored")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "tmux" and cmd[1] == "display-message":
            return _mock_run_ok(stdout="1")
        return _mock_run_ok()

    monkeypatch.setattr("subprocess.run", fake_run)

    main([
        "spawn",
        "--agent-id", "skill001",
        "--working-dir", str(tmp_path),
        "--task", "work",
        "--config", "{}",
        "--skills-dir", str(skills_dir),
    ])

    tmux_call = calls[0]
    sep_idx = tmux_call.index("--")
    claude_args = tmux_call[sep_idx + 1:]

    # Find all --append-system-prompt values
    append_indices = [
        i for i, v in enumerate(claude_args)
        if v == "--append-system-prompt"
    ]
    appended_files = [claude_args[i + 1] for i in append_indices]
    assert len(appended_files) == 2
    assert any("coding.md" in f for f in appended_files)
    assert any("review.md" in f for f in appended_files)


def test_spawn_approval_mode_force(tmp_path, monkeypatch, capsys):
    """APPROVAL_MODE=force maps to --permission-mode plan."""
    monkeypatch.setenv("APPROVAL_MODE", "force")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "tmux" and cmd[1] == "display-message":
            return _mock_run_ok(stdout="1")
        return _mock_run_ok()

    monkeypatch.setattr("subprocess.run", fake_run)

    main([
        "spawn",
        "--agent-id", "force001",
        "--working-dir", str(tmp_path),
        "--task", "work",
        "--config", "{}",
    ])

    tmux_call = calls[0]
    sep_idx = tmux_call.index("--")
    claude_args = tmux_call[sep_idx + 1:]
    pm_idx = claude_args.index("--permission-mode") + 1
    assert claude_args[pm_idx] == "plan"


# ---------------------------------------------------------------------------
# wait
# ---------------------------------------------------------------------------


def test_wait_polls_until_exit(monkeypatch, capsys):
    """wait polls tmux has-session until it returns non-zero."""
    poll_count = 0

    def fake_run(cmd, **kwargs):
        nonlocal poll_count
        if cmd[1] == "has-session":
            poll_count += 1
            if poll_count >= 3:
                return _mock_run_ok(returncode=1)  # session gone
            return _mock_run_ok()
        if cmd[1] == "capture-pane":
            return _mock_run_ok(stdout="captured output")
        return _mock_run_ok()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("time.sleep", lambda _: None)

    main(["wait", "--agent-id", "wait0001"])

    out = json.loads(capsys.readouterr().out)
    assert out["summary"] == "Session ended"
    assert out["output"] == "captured output"
    assert out["exit_code"] == 0
    assert poll_count == 3


def test_wait_with_timeout(monkeypatch, capsys):
    """wait respects --timeout and stops polling."""
    elapsed = {"value": 0.0}

    def fake_run(cmd, **kwargs):
        if cmd[1] == "has-session":
            return _mock_run_ok()  # always alive
        if cmd[1] == "capture-pane":
            return _mock_run_ok(stdout="")
        return _mock_run_ok()

    def fake_sleep(secs):
        elapsed["value"] += secs

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("time.sleep", fake_sleep)

    main(["wait", "--agent-id", "tmout001", "--timeout", "2.0"])

    out = json.loads(capsys.readouterr().out)
    assert out["summary"] == "Session ended"


# ---------------------------------------------------------------------------
# alive
# ---------------------------------------------------------------------------


def test_alive_true(monkeypatch, capsys):
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: _mock_run_ok(),
    )
    main(["alive", "--agent-id", "alive001"])
    out = json.loads(capsys.readouterr().out)
    assert out["alive"] is True


def test_alive_false(monkeypatch, capsys):
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: _mock_run_ok(returncode=1),
    )
    main(["alive", "--agent-id", "alive002"])
    out = json.loads(capsys.readouterr().out)
    assert out["alive"] is False


# ---------------------------------------------------------------------------
# kill
# ---------------------------------------------------------------------------


def test_kill(monkeypatch, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _mock_run_ok()

    monkeypatch.setattr("subprocess.run", fake_run)
    main(["kill", "--agent-id", "kill0001"])

    out = json.loads(capsys.readouterr().out)
    assert out["killed"] is True
    assert calls[0] == ["tmux", "kill-session", "-t", "strawpot-kill0001"]


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


def test_setup_runs_claude_login(monkeypatch):
    """setup runs 'claude /login' interactively."""
    captured = {}

    def fake_which(cmd):
        return f"/usr/bin/{cmd}"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _mock_run_ok()

    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        main(["setup"])

    assert exc_info.value.code == 0
    assert captured["cmd"] == ["/usr/bin/claude", "/login"]
    # setup runs interactively — no capture_output
    assert "capture_output" not in captured["kwargs"]


def test_setup_claude_not_found(monkeypatch, capsys):
    """setup exits with error if claude is not on PATH."""
    monkeypatch.setattr("shutil.which", lambda c: None)

    with pytest.raises(SystemExit) as exc_info:
        main(["setup"])

    assert exc_info.value.code == 1
