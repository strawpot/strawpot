"""Tests for SkillManager (pool resolver)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.skills.manager import SkillManager
from core.skills.types import SkillPool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """Workdir with agent identity and skill pool directories."""
    runtime = tmp_path / ".loguetown" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "agent.json").write_text(
        json.dumps({"name": "charlie", "role": "implementer"})
    )

    # Create project and agent pool directories
    (tmp_path / ".loguetown" / "skills").mkdir(parents=True)
    (tmp_path / ".loguetown" / "skills" / "charlie").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def global_root(tmp_path: Path) -> Path:
    skills_dir = tmp_path / "global_home" / "skills"
    skills_dir.mkdir(parents=True)
    return tmp_path / "global_home"


# ---------------------------------------------------------------------------
# from_workdir
# ---------------------------------------------------------------------------


def test_from_workdir_reads_agent_name(workdir, global_root):
    manager = SkillManager.from_workdir(workdir, global_root=global_root)
    pools = manager.pools()
    scopes = [p.scope for p in pools]
    assert "agent" in scopes  # charlie's pool exists


def test_from_workdir_no_identity(tmp_path, global_root):
    """No agent.json → no agent pool, only project if it exists."""
    manager = SkillManager.from_workdir(tmp_path, global_root=global_root)
    pools = manager.pools()
    scopes = [p.scope for p in pools]
    assert "agent" not in scopes


def test_from_workdir_missing_dirs_omitted(tmp_path, global_root):
    """Project and agent pools are omitted when their directories don't exist."""
    runtime = tmp_path / ".loguetown" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "agent.json").write_text(json.dumps({"name": "bob", "role": "reviewer"}))
    # No project or agent skills directories created
    manager = SkillManager.from_workdir(tmp_path, global_root=global_root)
    scopes = [p.scope for p in manager.pools()]
    assert "project" not in scopes
    assert "agent" not in scopes


# ---------------------------------------------------------------------------
# from_charter
# ---------------------------------------------------------------------------


def test_from_charter_uses_agent_name(workdir, global_root):
    from core.agents.types import Charter
    charter = Charter(name="charlie", role="implementer")
    manager = SkillManager.from_charter(charter, workdir=workdir, global_root=global_root)
    pools = manager.pools()
    scopes = [p.scope for p in pools]
    assert "agent" in scopes


def test_from_charter_different_name(workdir, global_root):
    from core.agents.types import Charter
    # Agent "diana" has no skills directory
    charter = Charter(name="diana", role="reviewer")
    manager = SkillManager.from_charter(charter, workdir=workdir, global_root=global_root)
    pools = manager.pools()
    scopes = [p.scope for p in pools]
    assert "agent" not in scopes  # diana's dir doesn't exist


# ---------------------------------------------------------------------------
# pools()
# ---------------------------------------------------------------------------


def test_pools_returns_skill_pool_objects(workdir, global_root):
    manager = SkillManager.from_workdir(workdir, global_root=global_root)
    pools = manager.pools()
    assert all(isinstance(p, SkillPool) for p in pools)


def test_pools_order_global_project_agent(workdir, global_root):
    manager = SkillManager.from_workdir(workdir, global_root=global_root)
    pools = manager.pools()
    scopes = [p.scope for p in pools]
    if "global" in scopes and "project" in scopes:
        assert scopes.index("global") < scopes.index("project")
    if "project" in scopes and "agent" in scopes:
        assert scopes.index("project") < scopes.index("agent")


def test_pools_global_path(workdir, global_root):
    manager = SkillManager.from_workdir(workdir, global_root=global_root)
    pools = manager.pools()
    global_pool = next(p for p in pools if p.scope == "global")
    assert global_pool.path == global_root / "skills"


def test_pools_project_path(workdir, global_root):
    manager = SkillManager.from_workdir(workdir, global_root=global_root)
    pools = manager.pools()
    project_pool = next(p for p in pools if p.scope == "project")
    assert project_pool.path == workdir / ".loguetown" / "skills"


def test_pools_agent_path(workdir, global_root):
    manager = SkillManager.from_workdir(workdir, global_root=global_root)
    pools = manager.pools()
    agent_pool = next(p for p in pools if p.scope == "agent")
    assert agent_pool.path == workdir / ".loguetown" / "skills" / "charlie"


# ---------------------------------------------------------------------------
# all_pools()
# ---------------------------------------------------------------------------


def test_all_pools_includes_nonexistent(tmp_path, global_root):
    """all_pools() includes all configured paths even if they don't exist."""
    runtime = tmp_path / ".loguetown" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "agent.json").write_text(json.dumps({"name": "charlie", "role": "implementer"}))

    manager = SkillManager.from_workdir(tmp_path, global_root=global_root)
    all_p = manager.all_pools()
    scopes = [p.scope for p in all_p]
    # All three scopes configured (global root exists, so it's always included)
    assert "global" in scopes
    assert "project" in scopes
    assert "agent" in scopes


def test_pools_subset_of_all_pools(workdir, global_root):
    manager = SkillManager.from_workdir(workdir, global_root=global_root)
    existing = {p.path for p in manager.pools()}
    all_paths = {p.path for p in manager.all_pools()}
    assert existing.issubset(all_paths)


# ---------------------------------------------------------------------------
# SkillPool.exists
# ---------------------------------------------------------------------------


def test_skill_pool_exists_true(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    pool = SkillPool(path=d, scope="project")
    assert pool.exists is True


def test_skill_pool_exists_false(tmp_path):
    pool = SkillPool(path=tmp_path / "nonexistent", scope="project")
    assert pool.exists is False
