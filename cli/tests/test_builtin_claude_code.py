"""Tests for the built-in claude_code agent (AGENT.md + registry resolution + Go binary)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from strawpot.agents.registry import parse_agent_md, resolve_agent

AGENT_DIR = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "strawpot"
    / "_builtin_agents"
    / "claude_code"
)
AGENT_MD = AGENT_DIR / "AGENT.md"
GO_BINARY = AGENT_DIR / "strawpot_claude_code"


# ---------------------------------------------------------------------------
# AGENT.md manifest
# ---------------------------------------------------------------------------


def test_agent_md_parses():
    fm, body = parse_agent_md(AGENT_MD)
    assert fm["name"] == "claude-code"
    assert fm["metadata"]["version"] == "0.1.0"
    assert fm["metadata"]["strawpot"]["bin"]["macos"] == "strawpot_claude_code"


def test_agent_md_tools():
    fm, _ = parse_agent_md(AGENT_MD)
    tools = fm["metadata"]["strawpot"]["tools"]
    assert "claude" in tools


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
    # Mock wrapper resolution — binary may not be built on CI
    monkeypatch.setattr(
        "strawpot.agents.registry._resolve_wrapper_cmd",
        lambda agent_dir, _meta: [str(agent_dir / "strawpot_claude_code")],
    )
    spec = resolve_agent("claude_code", str(tmp_path))
    assert spec.name == "claude-code"
    assert spec.version == "0.1.0"
    assert spec.config == {"model": "claude-sonnet-4-6"}


# ---------------------------------------------------------------------------
# Go binary integration tests (skipped if binary not built)
# ---------------------------------------------------------------------------

needs_binary = pytest.mark.skipif(
    not GO_BINARY.exists(), reason="Go binary not built"
)


@needs_binary
def test_go_build_returns_command_json(tmp_path):
    """Go binary build returns JSON with cmd and cwd."""
    workspace = tmp_path / "workspace"
    result = subprocess.run(
        [
            str(GO_BINARY), "build",
            "--agent-id", "build001",
            "--working-dir", str(tmp_path),
            "--agent-workspace-dir", str(workspace),
            "--role-prompt", "You are a coder.",
            "--memory-prompt", "Previous context.",
            "--task", "fix the bug",
            "--config", '{"model": "claude-opus-4-6"}',
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    out = json.loads(result.stdout)
    assert out["cwd"] == str(tmp_path)
    cmd = out["cmd"]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert cmd[cmd.index("-p") + 1] == "fix the bug"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-opus-4-6"
    # --add-dir points to the workspace directly
    assert "--add-dir" in cmd
    assert cmd[cmd.index("--add-dir") + 1] == str(workspace)


@needs_binary
def test_go_build_interactive_mode(tmp_path):
    """When task is empty, claude is run without -p flag."""
    workspace = tmp_path / "workspace"
    result = subprocess.run(
        [
            str(GO_BINARY), "build",
            "--agent-id", "build002",
            "--working-dir", str(tmp_path),
            "--agent-workspace-dir", str(workspace),
            "--task", "",
            "--config", "{}",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert "-p" not in out["cmd"]


@needs_binary
def test_go_build_permission_mode(tmp_path):
    """PERMISSION_MODE env var is passed through to --permission-mode."""
    import os

    workspace = tmp_path / "workspace"
    env = {**os.environ, "PERMISSION_MODE": "auto"}
    result = subprocess.run(
        [
            str(GO_BINARY), "build",
            "--agent-id", "build003",
            "--working-dir", str(tmp_path),
            "--agent-workspace-dir", str(workspace),
            "--task", "work",
            "--config", "{}",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    cmd = out["cmd"]
    assert "--permission-mode" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "auto"


@needs_binary
def test_go_build_with_skills_dir(tmp_path):
    """--skills-dir is a parent dir; children are symlinked into claude/.claude/skills/."""
    workspace = tmp_path / "workspace"
    # Create a parent skills dir containing a skill subdirectory
    skills_parent = tmp_path / "staged" / "skills"
    skills_parent.mkdir(parents=True)
    skill_dir = skills_parent / "my_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("skill content")

    result = subprocess.run(
        [
            str(GO_BINARY), "build",
            "--agent-id", "build005",
            "--working-dir", str(tmp_path),
            "--agent-workspace-dir", str(workspace),
            "--task", "work",
            "--config", "{}",
            "--skills-dir", str(skills_parent),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    cmd = out["cmd"]

    # Single --add-dir pointing to the workspace
    add_dir_indices = [i for i, v in enumerate(cmd) if v == "--add-dir"]
    assert len(add_dir_indices) == 1
    assert cmd[add_dir_indices[0] + 1] == str(workspace)

    # Skill linked (symlink) or copied (Windows fallback)
    link = workspace / ".claude" / "skills" / "my_skill"
    assert link.exists()
    assert (link / "SKILL.md").read_text() == "skill content"


@needs_binary
def test_go_build_with_roles_dir(tmp_path):
    """--roles-dir is a parent dir; children are symlinked into claude/roles/."""
    workspace = tmp_path / "workspace"
    # Create a parent roles dir containing a role subdirectory
    roles_parent = tmp_path / "staged" / "roles"
    roles_parent.mkdir(parents=True)
    role_dir = roles_parent / "my_role"
    role_dir.mkdir()
    (role_dir / "ROLE.md").write_text("role content")

    result = subprocess.run(
        [
            str(GO_BINARY), "build",
            "--agent-id", "build007",
            "--working-dir", str(tmp_path),
            "--agent-workspace-dir", str(workspace),
            "--task", "work",
            "--config", "{}",
            "--roles-dir", str(roles_parent),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    cmd = out["cmd"]

    # Single --add-dir pointing to the workspace
    add_dir_indices = [i for i, v in enumerate(cmd) if v == "--add-dir"]
    assert len(add_dir_indices) == 1
    assert cmd[add_dir_indices[0] + 1] == str(workspace)

    # Role linked (symlink) or copied (Windows fallback)
    link = workspace / "roles" / "my_role"
    assert link.exists()
    assert (link / "ROLE.md").read_text() == "role content"


@needs_binary
def test_go_build_multiple_roles_dirs(tmp_path):
    """Multiple --roles-dir flags merge children into claude/roles/."""
    workspace = tmp_path / "workspace"
    # First roles dir: staged role deps
    staged_roles = tmp_path / "staged" / "roles"
    staged_roles.mkdir(parents=True)
    dep_role = staged_roles / "reviewer"
    dep_role.mkdir()
    (dep_role / "ROLE.md").write_text("reviewer content")

    # Second roles dir: requester role in workspace
    ws_roles = tmp_path / "ws_roles"
    ws_roles.mkdir(parents=True)
    req_role = ws_roles / "orchestrator"
    req_role.mkdir()
    (req_role / "ROLE.md").write_text("orchestrator content")

    result = subprocess.run(
        [
            str(GO_BINARY), "build",
            "--agent-id", "build009",
            "--working-dir", str(tmp_path),
            "--agent-workspace-dir", str(workspace),
            "--task", "work",
            "--config", "{}",
            "--roles-dir", str(staged_roles),
            "--roles-dir", str(ws_roles),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    # Both roles present
    assert (workspace / "roles" / "reviewer" / "ROLE.md").read_text() == "reviewer content"
    assert (workspace / "roles" / "orchestrator" / "ROLE.md").read_text() == "orchestrator content"


@needs_binary
def test_go_build_prompt_file(tmp_path):
    """System prompt file is written into agent workspace dir."""
    workspace = tmp_path / "workspace"
    result = subprocess.run(
        [
            str(GO_BINARY), "build",
            "--agent-id", "build006",
            "--working-dir", str(tmp_path),
            "--agent-workspace-dir", str(workspace),
            "--role-prompt", "Role text here.",
            "--memory-prompt", "Memory text here.",
            "--task", "do work",
            "--config", "{}",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    prompt_file = workspace / "prompt.md"
    assert prompt_file.exists()
    content = prompt_file.read_text()
    assert "Role text here." in content
    assert "Memory text here." in content


@needs_binary
def test_go_build_requires_agent_workspace_dir(tmp_path):
    """Build fails if --agent-workspace-dir is not provided."""
    result = subprocess.run(
        [
            str(GO_BINARY), "build",
            "--agent-id", "build008",
            "--working-dir", str(tmp_path),
            "--task", "work",
            "--config", "{}",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "agent-workspace-dir" in result.stderr
