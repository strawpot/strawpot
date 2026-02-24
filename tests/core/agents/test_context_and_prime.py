"""Tests for ContextBuilder, Charter YAML, and the prime command."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from core.agents.context import ContextBuilder, SessionContext
from core.agents.types import Charter, ModelConfig
from core.skills.types import SkillPool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_pool(scope: str, path: Path) -> SkillPool:
    return SkillPool(path=path, scope=scope)  # type: ignore[arg-type]


@pytest.fixture
def charter():
    return Charter(
        name="charlie",
        role="implementer",
        instructions="Write clean, tested code.",
        model=ModelConfig(provider="claude_session", id="claude-opus-4-6"),
    )


@pytest.fixture
def skill_pools(tmp_path: Path):
    global_dir = tmp_path / "global_skills"
    project_dir = tmp_path / "project_skills"
    agent_dir = tmp_path / "agent_skills"
    for d in (global_dir, project_dir, agent_dir):
        d.mkdir()
    return [
        SkillPool(path=global_dir, scope="global"),
        SkillPool(path=project_dir, scope="project"),
        SkillPool(path=agent_dir, scope="agent"),
    ]


# ---------------------------------------------------------------------------
# ContextBuilder
# ---------------------------------------------------------------------------


def test_identity_section(charter, skill_pools):
    ctx = SessionContext(charter=charter, skill_pools=skill_pools)
    output = ContextBuilder().build(ctx)
    assert "# Identity" in output
    assert "charlie" in output
    assert "implementer" in output


def test_instructions_section(charter, skill_pools):
    ctx = SessionContext(charter=charter, skill_pools=skill_pools)
    output = ContextBuilder().build(ctx)
    assert "# Role Instructions" in output
    assert "Write clean, tested code." in output


def test_skill_pools_section(charter, skill_pools):
    ctx = SessionContext(charter=charter, skill_pools=skill_pools)
    output = ContextBuilder().build(ctx)
    assert "# Skill Pools" in output
    # All three scopes appear in the table
    assert "global" in output
    assert "project" in output
    assert "agent" in output
    # Instruction to generate CLAUDE.md
    assert "CLAUDE.md" in output


def test_skill_pools_table_format(charter, skill_pools):
    ctx = SessionContext(charter=charter, skill_pools=skill_pools)
    output = ContextBuilder().build(ctx)
    assert "| Scope | Path |" in output
    assert "|-------|------|" in output


def test_work_section(charter, skill_pools):
    ctx = SessionContext(charter=charter, skill_pools=skill_pools, work="Implement the login endpoint.")
    output = ContextBuilder().build(ctx)
    assert "# Current Work" in output
    assert "Implement the login endpoint." in output


def test_no_work_omits_section(charter, skill_pools):
    ctx = SessionContext(charter=charter, skill_pools=skill_pools, work=None)
    output = ContextBuilder().build(ctx)
    assert "# Current Work" not in output


def test_empty_instructions_omitted():
    charter = Charter(name="alice", role="reviewer", instructions="")
    ctx = SessionContext(charter=charter, skill_pools=[])
    output = ContextBuilder().build(ctx)
    assert "# Role Instructions" not in output


def test_no_pools_omits_skill_section(charter):
    ctx = SessionContext(charter=charter, skill_pools=[])
    output = ContextBuilder().build(ctx)
    assert "# Skill Pools" not in output


# ---------------------------------------------------------------------------
# Charter YAML round-trip
# ---------------------------------------------------------------------------


def test_charter_to_yaml(tmp_path: Path, charter):
    path = tmp_path / "charlie.yaml"
    charter.to_yaml(path)
    assert path.exists()
    content = path.read_text()
    assert "charlie" in content
    assert "implementer" in content


def test_charter_from_yaml_round_trip(tmp_path: Path, charter):
    path = tmp_path / "charlie.yaml"
    charter.to_yaml(path)
    loaded = Charter.from_yaml(path)

    assert loaded.name == charter.name
    assert loaded.role == charter.role
    assert loaded.instructions == charter.instructions
    assert loaded.model.provider == charter.model.provider
    assert loaded.model.id == charter.model.id
    assert loaded.max_tokens == charter.max_tokens


def test_charter_from_yaml_defaults(tmp_path: Path):
    path = tmp_path / "minimal.yaml"
    path.write_text("name: alice\nrole: reviewer\n")
    charter = Charter.from_yaml(path)
    assert charter.name == "alice"
    assert charter.role == "reviewer"
    assert charter.instructions == ""
    assert charter.model.provider == "claude_session"
    assert charter.model.id is None
    assert charter.allowed_tools != []


def test_charter_from_yaml_allowed_tools(tmp_path: Path):
    path = tmp_path / "c.yaml"
    path.write_text(textwrap.dedent("""\
        name: charlie
        role: implementer
        tools:
          allowed: [Read, Write]
    """))
    charter = Charter.from_yaml(path)
    assert charter.allowed_tools == ["Read", "Write"]


# ---------------------------------------------------------------------------
# prime.build_prime_output
# ---------------------------------------------------------------------------


@pytest.fixture
def prime_workdir(tmp_path: Path) -> Path:
    """Workdir with agent identity, a skill pool, and current work."""
    runtime = tmp_path / ".loguetown" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "agent.json").write_text(
        json.dumps({"name": "charlie", "role": "implementer"})
    )
    (runtime / "work.txt").write_text("Implement the login endpoint.")

    # Create the agent skill pool directory
    agent_skills = tmp_path / ".loguetown" / "skills" / "charlie"
    agent_skills.mkdir(parents=True)
    (agent_skills / "typescript-patterns").mkdir()

    return tmp_path


def test_prime_output_contains_identity(prime_workdir: Path):
    from core.prime import build_prime_output
    output = build_prime_output(prime_workdir)
    assert "charlie" in output
    assert "implementer" in output


def test_prime_output_contains_work(prime_workdir: Path):
    from core.prime import build_prime_output
    output = build_prime_output(prime_workdir)
    assert "Implement the login endpoint." in output


def test_prime_output_contains_skill_pools(prime_workdir: Path):
    from core.prime import build_prime_output
    output = build_prime_output(prime_workdir)
    # Pool section is present with path references
    assert "# Skill Pools" in output
    assert "agent" in output
    assert "CLAUDE.md" in output


def test_prime_persists_session_id(prime_workdir: Path):
    from core.prime import build_prime_output
    hook_input = {"session_id": "sess-abc123", "source": "startup"}
    build_prime_output(prime_workdir, hook_input=hook_input)

    session_file = prime_workdir / ".loguetown" / "runtime" / "session.json"
    assert session_file.exists()
    data = json.loads(session_file.read_text())
    assert data["session_id"] == "sess-abc123"


def test_prime_no_identity(tmp_path: Path):
    from core.prime import build_prime_output
    output = build_prime_output(tmp_path)
    assert "No agent identity" in output


def test_prime_uses_charter_yaml(tmp_path: Path):
    from core.prime import build_prime_output

    runtime = tmp_path / ".loguetown" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "agent.json").write_text(
        json.dumps({"name": "charlie", "role": "implementer"})
    )

    charter_dir = tmp_path / ".loguetown" / "agents"
    charter_dir.mkdir(parents=True)
    (charter_dir / "charlie.yaml").write_text(textwrap.dedent("""\
        name: charlie
        role: implementer
        instructions: "Always write tests first."
    """))

    output = build_prime_output(tmp_path)
    assert "Always write tests first." in output
