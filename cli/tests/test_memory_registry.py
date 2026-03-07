"""Tests for strawpot.memory.registry."""

from pathlib import Path
from textwrap import dedent

import pytest

from strawpot.agents.registry import ValidationResult
from strawpot.memory.protocol import MemoryProvider
from strawpot.memory.registry import (
    MemorySpec,
    _merge_config,
    _resolve_script,
    load_provider,
    parse_memory_md,
    resolve_memory,
    validate_memory,
)

SAMPLE_MEMORY_MD = dedent("""\
    ---
    name: test-memory
    description: A test memory provider
    metadata:
      version: "0.1.0"
      strawpot:
        memory_module: provider.py
        tools:
            sometool:
              description: A tool
              install:
                macos: brew install sometool
        params:
          storage_dir:
            type: string
            default: .strawpot/memory
          em_max_events:
            type: int
            default: 10000
        env:
          API_KEY:
            required: true
            description: API key
    ---

    # Test Memory Provider

    This is the body.
""")


def _write_memory(base: Path, name: str, content: str, script: bool = True) -> Path:
    """Helper to write a MEMORY.md in the expected directory structure."""
    memory_dir = base / name
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "MEMORY.md").write_text(content)
    if script:
        (memory_dir / "provider.py").write_text("# provider stub\n")
    return memory_dir


# --- parse_memory_md ---


def test_parse_memory_md(tmp_path):
    path = tmp_path / "MEMORY.md"
    path.write_text(SAMPLE_MEMORY_MD)
    fm, body = parse_memory_md(path)

    assert fm["name"] == "test-memory"
    assert fm["metadata"]["version"] == "0.1.0"
    assert fm["metadata"]["strawpot"]["memory_module"] == "provider.py"
    assert "# Test Memory Provider" in body


def test_parse_memory_md_no_frontmatter(tmp_path):
    path = tmp_path / "MEMORY.md"
    path.write_text("# Just markdown\n\nNo frontmatter here.")
    with pytest.raises(ValueError, match="missing frontmatter"):
        parse_memory_md(path)


def test_parse_memory_md_missing_closing(tmp_path):
    path = tmp_path / "MEMORY.md"
    path.write_text("---\nname: broken\n")
    with pytest.raises(ValueError, match="missing closing"):
        parse_memory_md(path)


# --- _resolve_script ---


def test_resolve_script_found(tmp_path):
    script = tmp_path / "provider.py"
    script.write_text("# stub")
    meta = {"memory_module": "provider.py"}
    result = _resolve_script(tmp_path, meta)
    assert result == str(script.resolve())


def test_resolve_script_missing_field():
    with pytest.raises(ValueError, match="must define"):
        _resolve_script(Path("/dummy"), {})


def test_resolve_script_file_not_found(tmp_path):
    meta = {"memory_module": "missing.py"}
    with pytest.raises(ValueError, match="not found"):
        _resolve_script(tmp_path, meta)


# --- _merge_config ---


def test_merge_config_defaults_only():
    params = {
        "storage_dir": {"type": "string", "default": ".strawpot/memory"},
        "em_max_events": {"type": "int", "default": 10000},
    }
    result = _merge_config(params, {})
    assert result == {"storage_dir": ".strawpot/memory", "em_max_events": 10000}


def test_merge_config_user_overrides():
    params = {
        "storage_dir": {"type": "string", "default": ".strawpot/memory"},
        "em_max_events": {"type": "int", "default": 10000},
    }
    result = _merge_config(params, {"storage_dir": "/custom/path", "extra": True})
    assert result == {
        "storage_dir": "/custom/path",
        "em_max_events": 10000,
        "extra": True,
    }


# --- resolve_memory ---


def test_resolve_project_local(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global"))
    project_dir = tmp_path / "project"
    memory_dir = project_dir / ".strawpot" / "memory"
    _write_memory(memory_dir, "test-mem", SAMPLE_MEMORY_MD)

    spec = resolve_memory("test-mem", str(project_dir))
    assert spec.name == "test-memory"
    assert spec.version == "0.1.0"
    assert spec.config == {"storage_dir": ".strawpot/memory", "em_max_events": 10000}
    assert spec.env_schema["API_KEY"]["required"] is True
    assert "sometool" in spec.tools
    assert spec.script.endswith("provider.py")


def test_resolve_global(tmp_path, monkeypatch):
    global_dir = tmp_path / "global"
    monkeypatch.setenv("STRAWPOT_HOME", str(global_dir))
    memory_dir = global_dir / "memory"
    _write_memory(memory_dir, "test-mem", SAMPLE_MEMORY_MD)

    project_dir = tmp_path / "empty_project"
    project_dir.mkdir()

    spec = resolve_memory("test-mem", str(project_dir))
    assert spec.name == "test-memory"


def test_resolve_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global"))
    with pytest.raises(FileNotFoundError, match="Memory provider not found"):
        resolve_memory("nonexistent", str(tmp_path))


def test_resolve_merges_config(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global"))
    project_dir = tmp_path / "project"
    memory_dir = project_dir / ".strawpot" / "memory"
    _write_memory(memory_dir, "test-mem", SAMPLE_MEMORY_MD)

    spec = resolve_memory(
        "test-mem", str(project_dir), user_config={"storage_dir": "/custom"}
    )
    assert spec.config["storage_dir"] == "/custom"
    assert spec.config["em_max_events"] == 10000


# --- validate_memory ---


def test_validate_ok(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda c: f"/usr/bin/{c}")
    monkeypatch.setenv("API_KEY", "secret")
    spec = MemorySpec(
        name="ok-memory",
        version="1.0.0",
        script="/path/to/provider.py",
        tools={"git": {"description": "version control"}},
        env_schema={"API_KEY": {"required": True}},
    )
    result = validate_memory(spec)
    assert result.ok


def test_validate_missing_tool(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda c: None)
    spec = MemorySpec(
        name="tool-memory",
        version="1.0.0",
        script="/path/to/provider.py",
        tools={
            "sometool": {
                "description": "A tool",
                "install": {"macos": "brew install sometool"},
            }
        },
    )
    result = validate_memory(spec)
    assert not result.ok
    assert len(result.missing_tools) == 1
    name, hint = result.missing_tools[0]
    assert name == "sometool"


def test_validate_missing_env(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    spec = MemorySpec(
        name="env-memory",
        version="1.0.0",
        script="/path/to/provider.py",
        env_schema={
            "SECRET_KEY": {"required": True},
            "OPTIONAL_VAR": {"required": False},
        },
    )
    result = validate_memory(spec)
    assert not result.ok
    assert "SECRET_KEY" in result.missing_env
    assert "OPTIONAL_VAR" not in result.missing_env


def test_validate_no_deps():
    spec = MemorySpec(
        name="simple-memory",
        version="1.0.0",
        script="/path/to/provider.py",
    )
    result = validate_memory(spec)
    assert result.ok


# --- MemorySpec ---


def test_memory_spec_defaults():
    spec = MemorySpec(name="m", version="1.0", script="/p.py")
    assert spec.config == {}
    assert spec.env_schema == {}
    assert spec.tools == {}


# --- Built-in noop provider ---


def test_resolve_builtin_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global"))
    spec = resolve_memory("noop", str(tmp_path))
    assert spec.name == "noop"
    assert spec.version == "0.1.0"
    assert spec.script.endswith("provider.py")


def test_noop_provider_satisfies_protocol():
    from strawpot.memory._builtin_memory.noop.provider import NoopMemoryProvider

    provider = NoopMemoryProvider()
    assert isinstance(provider, MemoryProvider)


def test_noop_provider_get_returns_empty():
    from strawpot.memory._builtin_memory.noop.provider import NoopMemoryProvider

    provider = NoopMemoryProvider()
    result = provider.get(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="do something",
    )
    assert result.context_cards == []
    assert result.context_hash == ""


def test_noop_provider_dump_returns_empty():
    from strawpot.memory._builtin_memory.noop.provider import NoopMemoryProvider

    provider = NoopMemoryProvider()
    receipt = provider.dump(
        session_id="s1", agent_id="a1", role="impl",
        behavior_ref="text", task="do something",
        status="success", output="done",
    )
    assert receipt.em_event_ids == []


# --- load_provider ---


def test_load_provider(tmp_path):
    provider_code = dedent("""\
        from strawpot.memory.protocol import DumpReceipt, GetResult, RememberResult

        class MyProvider:
            name = "test"

            def get(self, *, session_id, agent_id, role, behavior_ref,
                    task, budget=None, parent_agent_id=None):
                return GetResult()

            def dump(self, *, session_id, agent_id, role, behavior_ref,
                     task, status, output, tool_trace="",
                     parent_agent_id=None, artifacts=None):
                return DumpReceipt()

            def remember(self, *, session_id, agent_id, role, content,
                         keywords=None, scope="project"):
                return RememberResult(status="accepted")
    """)
    script = tmp_path / "provider.py"
    script.write_text(provider_code)
    spec = MemorySpec(name="test", version="1.0", script=str(script))

    provider = load_provider(spec)
    assert isinstance(provider, MemoryProvider)
    assert provider.name == "test"
    result = provider.get(
        session_id="s1", agent_id="a1", role="r",
        behavior_ref="desc", task="t",
    )
    assert result.context_cards == []


def test_load_provider_no_class(tmp_path):
    script = tmp_path / "empty.py"
    script.write_text("# no provider class\nx = 42\n")
    spec = MemorySpec(name="bad", version="1.0", script=str(script))

    with pytest.raises(ValueError, match="No MemoryProvider"):
        load_provider(spec)


def test_load_provider_noop(tmp_path, monkeypatch):
    """load_provider works with the built-in noop provider."""
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "global"))
    spec = resolve_memory("noop", str(tmp_path))
    provider = load_provider(spec)
    assert isinstance(provider, MemoryProvider)
    assert provider.name == "noop"
