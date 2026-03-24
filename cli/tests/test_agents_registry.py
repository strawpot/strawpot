"""Tests for strawpot.agents.registry."""

from pathlib import Path
from textwrap import dedent

import pytest


from strawpot.agents.registry import (
    AgentSpec,
    ValidationResult,
    _merge_config,
    _resolve_wrapper_cmd,
    check_install_prerequisites,
    parse_agent_md,
    resolve_agent,
    validate_agent,
)

SAMPLE_AGENT_MD = dedent("""\
    ---
    name: test-agent
    description: A test agent
    metadata:
      version: "1.2.3"
      strawpot:
        wrapper:
          command: test-agent-cli
        tools:
            sometool:
              description: A tool
              install:
                macos: brew install sometool
        params:
          model:
            type: string
            default: gpt-4
            description: Model to use
          temperature:
            type: float
            default: 0.7
        env:
          API_KEY:
            required: true
            description: API key
    ---

    # Test Agent

    This is the body.
""")


def _write_agent(base: Path, name: str, content: str) -> Path:
    """Helper to write an AGENT.md in the expected directory structure."""
    agent_dir = base / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text(content)
    return agent_dir


# --- parse_agent_md ---


def test_parse_agent_md(tmp_path):
    path = tmp_path / "AGENT.md"
    path.write_text(SAMPLE_AGENT_MD)
    fm, body = parse_agent_md(path)

    assert fm["name"] == "test-agent"
    assert fm["metadata"]["version"] == "1.2.3"
    assert fm["metadata"]["strawpot"]["wrapper"]["command"] == "test-agent-cli"
    assert "# Test Agent" in body


def test_parse_agent_md_no_frontmatter(tmp_path):
    path = tmp_path / "AGENT.md"
    path.write_text("# Just markdown\n\nNo frontmatter here.")
    with pytest.raises(ValueError, match="missing frontmatter"):
        parse_agent_md(path)


def test_parse_agent_md_missing_closing(tmp_path):
    path = tmp_path / "AGENT.md"
    path.write_text("---\nname: broken\n")
    with pytest.raises(ValueError, match="missing closing"):
        parse_agent_md(path)


# --- _resolve_wrapper_cmd ---



def test_resolve_wrapper_cmd_bin(tmp_path, monkeypatch):
    binary = tmp_path / "my-agent"
    binary.write_text("#!/bin/sh\necho hi")
    binary.chmod(0o755)
    monkeypatch.setattr(
        "strawpot.agents.registry._current_os", lambda: "macos"
    )
    meta = {"bin": {"macos": "my-agent", "linux": "my-agent"}}
    cmd = _resolve_wrapper_cmd(tmp_path, meta)
    assert cmd == [str(binary)]



def test_resolve_wrapper_cmd_bin_linux(tmp_path, monkeypatch):
    binary = tmp_path / "my-agent-linux"
    binary.write_text("#!/bin/sh\necho hi")
    binary.chmod(0o755)
    monkeypatch.setattr(
        "strawpot.agents.registry._current_os", lambda: "linux"
    )
    meta = {"bin": {"macos": "my-agent-darwin", "linux": "my-agent-linux"}}
    cmd = _resolve_wrapper_cmd(tmp_path, meta)
    assert cmd == [str(binary)]


def test_resolve_wrapper_cmd_bin_no_os_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "strawpot.agents.registry._current_os", lambda: "freebsd"
    )
    meta = {"bin": {"macos": "my-agent", "linux": "my-agent"}}
    with pytest.raises(ValueError, match="No binary defined for OS"):
        _resolve_wrapper_cmd(tmp_path, meta)


def test_resolve_wrapper_cmd_bin_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "strawpot.agents.registry._current_os", lambda: "macos"
    )
    meta = {"bin": {"macos": "missing-binary"}}
    with pytest.raises(ValueError, match="Agent binary not found"):
        _resolve_wrapper_cmd(tmp_path, meta)


def test_resolve_wrapper_cmd_command(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda c: f"/usr/bin/{c}")
    meta = {"wrapper": {"command": "my-agent"}}
    cmd = _resolve_wrapper_cmd(Path("/dummy"), meta)
    assert cmd == ["/usr/bin/my-agent"]


def test_resolve_wrapper_cmd_command_not_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda c: None)
    meta = {"wrapper": {"command": "missing-agent"}}
    with pytest.raises(ValueError, match="not found on PATH"):
        _resolve_wrapper_cmd(Path("/dummy"), meta)


def test_resolve_wrapper_cmd_missing():
    with pytest.raises(ValueError, match="must define"):
        _resolve_wrapper_cmd(Path("/dummy"), {})


# --- _merge_config ---


def test_merge_config_defaults_only():
    params = {
        "model": {"type": "string", "default": "gpt-4"},
        "temperature": {"type": "float", "default": 0.7},
    }
    result = _merge_config(params, {})
    assert result == {"model": "gpt-4", "temperature": 0.7}


def test_merge_config_user_overrides():
    params = {
        "model": {"type": "string", "default": "gpt-4"},
        "temperature": {"type": "float", "default": 0.7},
    }
    result = _merge_config(params, {"model": "claude-sonnet-4-6", "extra": True})
    assert result == {"model": "claude-sonnet-4-6", "temperature": 0.7, "extra": True}


def test_merge_config_no_defaults():
    params = {"model": {"type": "string", "description": "no default"}}
    result = _merge_config(params, {"model": "gpt-4"})
    assert result == {"model": "gpt-4"}


# --- resolve_agent ---


def test_resolve_agent_project_local(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global"))
    monkeypatch.setattr("shutil.which", lambda c: f"/usr/bin/{c}")
    project_dir = tmp_path / "project"
    agents_dir = project_dir / ".strawpot" / "agents"
    _write_agent(agents_dir, "myagent", SAMPLE_AGENT_MD)

    spec = resolve_agent("myagent", str(project_dir))
    assert spec.name == "test-agent"
    assert spec.version == "1.2.3"
    assert spec.config == {"model": "gpt-4", "temperature": 0.7}
    assert spec.env_schema["API_KEY"]["required"] is True
    assert "sometool" in spec.tools
    assert "/usr/bin/test-agent-cli" in spec.wrapper_cmd[0]


def test_resolve_agent_global(tmp_path, monkeypatch):
    global_dir = tmp_path / "global"
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))
    monkeypatch.setattr("shutil.which", lambda c: f"/usr/bin/{c}")
    agents_dir = global_dir / "agents"
    _write_agent(agents_dir, "myagent", SAMPLE_AGENT_MD)

    project_dir = tmp_path / "empty_project"
    project_dir.mkdir()

    spec = resolve_agent("myagent", str(project_dir))
    assert spec.name == "test-agent"


def test_resolve_agent_user_config_override(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global"))
    monkeypatch.setattr("shutil.which", lambda c: f"/usr/bin/{c}")
    project_dir = tmp_path / "project"
    agents_dir = project_dir / ".strawpot" / "agents"
    _write_agent(agents_dir, "myagent", SAMPLE_AGENT_MD)

    spec = resolve_agent(
        "myagent", str(project_dir), user_config={"model": "claude-opus-4-6"}
    )
    assert spec.config["model"] == "claude-opus-4-6"
    assert spec.config["temperature"] == 0.7  # default preserved


def test_resolve_agent_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global"))
    with pytest.raises(FileNotFoundError, match="Agent not found"):
        resolve_agent("nonexistent", str(tmp_path))


# --- validate_agent ---


def test_validate_agent_all_ok(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda c: f"/usr/bin/{c}")
    monkeypatch.setenv("API_KEY", "secret")
    spec = AgentSpec(
        name="ok-agent",
        version="1.0.0",
        wrapper_cmd=["/usr/bin/my-agent"],
        tools={"git": {"description": "version control"}},
        env_schema={"API_KEY": {"required": True}},
    )
    result = validate_agent(spec)
    assert result.ok
    assert result.missing_tools == []
    assert result.missing_env == []


def test_validate_agent_missing_tool(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda c: None)
    spec = AgentSpec(
        name="tool-agent",
        version="1.0.0",
        wrapper_cmd=["/usr/bin/my-agent"],
        tools={
            "sometool": {
                "description": "A tool",
                "install": {
                    "macos": "brew install sometool",
                    "linux": "apt install sometool",
                },
            }
        },
    )
    result = validate_agent(spec)
    assert not result.ok
    assert len(result.missing_tools) == 1
    name, hint = result.missing_tools[0]
    assert name == "sometool"
    assert hint is not None  # platform-specific hint


def test_validate_agent_missing_env(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    spec = AgentSpec(
        name="env-agent",
        version="1.0.0",
        wrapper_cmd=["/usr/bin/my-agent"],
        env_schema={
            "SECRET_KEY": {"required": True, "description": "Secret key"},
            "OPTIONAL_VAR": {"required": False, "description": "Not required"},
        },
    )
    result = validate_agent(spec)
    assert not result.ok
    assert "SECRET_KEY" in result.missing_env
    assert "OPTIONAL_VAR" not in result.missing_env


def test_validate_agent_no_deps():
    spec = AgentSpec(
        name="simple-agent",
        version="1.0.0",
        wrapper_cmd=["/usr/bin/my-agent"],
    )
    result = validate_agent(spec)
    assert result.ok


def test_validation_result_ok_property():
    assert ValidationResult().ok
    assert not ValidationResult(missing_tools=[("x", None)]).ok
    assert not ValidationResult(missing_env=["Y"]).ok


# --- check_install_prerequisites ---


AGENT_MD_WITH_CURL_INSTALL = dedent("""\
    ---
    name: curl-agent
    metadata:
      strawpot:
        bin:
          macos: my_binary
          linux: my_binary
        install:
          macos: curl -fsSL https://example.com/install.sh | sh
          linux: curl -fsSL https://example.com/install.sh | sh
        tools:
          npm:
            description: Node.js package manager
            install:
              macos: brew install node
              linux: apt install nodejs
    ---

    # Curl Agent
""")


@pytest.fixture()
def curl_agent_dir(tmp_path, monkeypatch):
    """Create a temp agent dir with AGENT.md that requires curl and npm."""
    agent_dir = tmp_path / "my-agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text(AGENT_MD_WITH_CURL_INSTALL)
    monkeypatch.setattr("strawpot.agents.registry._current_os", lambda: "macos")
    return agent_dir


def test_check_prerequisites_all_present(curl_agent_dir, monkeypatch):
    """When curl and npm are on PATH, no prerequisites are missing."""
    monkeypatch.setattr("shutil.which", lambda c: f"/usr/bin/{c}")
    assert check_install_prerequisites(curl_agent_dir) == []


def test_check_prerequisites_missing_curl(curl_agent_dir, monkeypatch):
    """When curl is missing, it's reported as a prerequisite."""
    monkeypatch.setattr(
        "shutil.which",
        lambda c: None if c == "curl" else f"/usr/bin/{c}",
    )
    tool_names = [name for name, _ in check_install_prerequisites(curl_agent_dir)]
    assert "curl" in tool_names


def test_check_prerequisites_missing_npm(curl_agent_dir, monkeypatch):
    """When npm is missing, it's reported with install guidance."""
    monkeypatch.setattr(
        "shutil.which",
        lambda c: None if c == "npm" else f"/usr/bin/{c}",
    )
    tool_names = [name for name, _ in check_install_prerequisites(curl_agent_dir)]
    assert "npm" in tool_names


def test_check_prerequisites_no_agent_md(tmp_path):
    """When AGENT.md doesn't exist, returns empty list (graceful)."""
    agent_dir = tmp_path / "missing-agent"
    agent_dir.mkdir()
    assert check_install_prerequisites(agent_dir) == []


def test_check_prerequisites_null_tool_meta(tmp_path, monkeypatch):
    """When tool metadata is YAML null (e.g. 'tools:\\n  npm:'), no crash."""
    agent_md = dedent("""\
        ---
        name: null-meta-agent
        metadata:
          strawpot:
            bin:
              macos: my_binary
              linux: my_binary
            tools:
              npm:
        ---

        # Agent with null tool meta
    """)
    agent_dir = tmp_path / "null-meta-agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text(agent_md)
    monkeypatch.setattr("strawpot.agents.registry._current_os", lambda: "macos")
    monkeypatch.setattr("shutil.which", lambda c: None)

    result = check_install_prerequisites(agent_dir)
    tool_names = [name for name, _ in result]
    assert "npm" in tool_names


def test_check_prerequisites_malformed_agent_md(tmp_path):
    """When AGENT.md is malformed, ValueError propagates (not silently swallowed)."""
    agent_dir = tmp_path / "bad-agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text("not valid frontmatter at all")

    with pytest.raises(ValueError, match="missing frontmatter"):
        check_install_prerequisites(agent_dir)


def test_resolve_wrapper_cmd_bin_not_found_includes_install_hint(tmp_path, monkeypatch):
    """When binary is missing, error includes install hint from metadata."""
    monkeypatch.setattr("strawpot.agents.registry._current_os", lambda: "macos")
    meta = {
        "bin": {"macos": "missing-binary"},
        "install": {"macos": "curl -fsSL https://example.com/install.sh | sh"},
    }
    with pytest.raises(ValueError, match="curl -fsSL"):
        _resolve_wrapper_cmd(tmp_path, meta)
