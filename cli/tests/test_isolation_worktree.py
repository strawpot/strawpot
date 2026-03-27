"""Tests for strawpot.isolation.worktree.

These tests use real git repos (via tmp_path) — no mocking of git commands.
"""

import os
import subprocess
import warnings

import pytest

from strawpot.isolation.protocol import IsolatedEnv, Isolator
from strawpot.isolation.worktree import WorktreeIsolator, _project_hash
from strawpot.session import resolve_isolator


def _init_repo(path):
    """Initialize a git repo with an initial commit."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), capture_output=True, check=True,
    )
    # Need at least one commit for worktrees to work
    readme = path / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(path), capture_output=True, check=True,
    )


def _branches(path):
    """List local branch names in the repo."""
    result = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=str(path), capture_output=True, text=True, check=True,
    )
    return result.stdout.strip().splitlines()


def _worktrees(path):
    """List worktree paths in the repo."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(path), capture_output=True, text=True, check=True,
    )
    paths = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(line.split(" ", 1)[1])
    return paths


# --- Protocol conformance ---


def test_worktree_satisfies_protocol():
    assert isinstance(WorktreeIsolator(), Isolator)


# --- create ---


def test_create_worktree(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "strawpot_home"))
    isolator = WorktreeIsolator()

    env = isolator.create(session_id="run_abc123", base_dir=str(tmp_path))

    assert isinstance(env, IsolatedEnv)
    assert os.path.isdir(env.path)
    assert env.branch is not None


def test_create_worktree_path_and_branch(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    home = tmp_path / "strawpot_home"
    monkeypatch.setenv("STRAWPOT_HOME", str(home))
    isolator = WorktreeIsolator()

    env = isolator.create(session_id="run_abc123", base_dir=str(tmp_path))

    proj_hash = _project_hash(str(tmp_path))
    expected_path = os.path.join(
        str(home), "worktrees", proj_hash, "run_abc123"
    )
    assert env.path == expected_path
    assert env.branch == "strawpot/run_abc123"


def test_create_worktree_has_files(tmp_path, monkeypatch):
    """Worktree should contain the same files as the main repo."""
    _init_repo(tmp_path)
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "strawpot_home"))
    isolator = WorktreeIsolator()

    env = isolator.create(session_id="run_xyz", base_dir=str(tmp_path))

    assert os.path.isfile(os.path.join(env.path, "README.md"))


def test_create_worktree_branch_exists(tmp_path, monkeypatch):
    """The branch should appear in git branch output."""
    _init_repo(tmp_path)
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "strawpot_home"))
    isolator = WorktreeIsolator()

    env = isolator.create(session_id="run_branchtest", base_dir=str(tmp_path))

    assert env.branch in _branches(tmp_path)


def test_create_worktree_not_git_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "strawpot_home"))
    isolator = WorktreeIsolator()
    with pytest.raises(ValueError, match="Not a git repository"):
        isolator.create(session_id="run_fail", base_dir=str(tmp_path))


# --- cleanup ---


def test_cleanup_removes_worktree(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "strawpot_home"))
    isolator = WorktreeIsolator()

    env = isolator.create(session_id="run_clean", base_dir=str(tmp_path))
    assert os.path.isdir(env.path)

    isolator.cleanup(env, base_dir=str(tmp_path))

    assert not os.path.isdir(env.path)
    assert env.branch not in _branches(tmp_path)


def test_cleanup_idempotent(tmp_path, monkeypatch):
    """Calling cleanup twice should not raise."""
    _init_repo(tmp_path)
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "strawpot_home"))
    isolator = WorktreeIsolator()

    env = isolator.create(session_id="run_idem", base_dir=str(tmp_path))
    isolator.cleanup(env, base_dir=str(tmp_path))
    isolator.cleanup(env, base_dir=str(tmp_path))  # should not raise


# --- multiple sessions ---


def test_multiple_sessions(tmp_path, monkeypatch):
    """Two concurrent worktrees should coexist."""
    _init_repo(tmp_path)
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "strawpot_home"))
    isolator = WorktreeIsolator()

    env1 = isolator.create(session_id="run_session_a", base_dir=str(tmp_path))
    env2 = isolator.create(session_id="run_session_b", base_dir=str(tmp_path))

    assert os.path.isdir(env1.path)
    assert os.path.isdir(env2.path)
    assert env1.path != env2.path
    assert env1.branch != env2.branch

    # Both branches exist
    branches = _branches(tmp_path)
    assert env1.branch in branches
    assert env2.branch in branches

    # Cleanup one doesn't affect the other
    isolator.cleanup(env1, base_dir=str(tmp_path))
    assert not os.path.isdir(env1.path)
    assert os.path.isdir(env2.path)

    isolator.cleanup(env2, base_dir=str(tmp_path))
    assert not os.path.isdir(env2.path)


# --- delete_branch parameter ---


def test_cleanup_delete_branch_false(tmp_path, monkeypatch):
    """When delete_branch=False, worktree is removed but branch is preserved."""
    _init_repo(tmp_path)
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "strawpot_home"))
    isolator = WorktreeIsolator()

    env = isolator.create(session_id="run_keep_branch", base_dir=str(tmp_path))
    assert env.branch in _branches(tmp_path)

    isolator.cleanup(env, base_dir=str(tmp_path), delete_branch=False)

    assert not os.path.isdir(env.path)
    assert env.branch in _branches(tmp_path)


def test_cleanup_delete_branch_true(tmp_path, monkeypatch):
    """When delete_branch=True (default), both worktree and branch are removed."""
    _init_repo(tmp_path)
    monkeypatch.setenv("STRAWPOT_HOME", str(tmp_path / "strawpot_home"))
    isolator = WorktreeIsolator()

    env = isolator.create(session_id="run_del_branch", base_dir=str(tmp_path))

    isolator.cleanup(env, base_dir=str(tmp_path), delete_branch=True)

    assert not os.path.isdir(env.path)
    assert env.branch not in _branches(tmp_path)


# --- deprecation warning ---


def test_resolve_isolator_worktree_emits_deprecation_warning():
    """resolve_isolator('worktree') should emit a DeprecationWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        isolator = resolve_isolator("worktree")

    assert isinstance(isolator, WorktreeIsolator)
    deprecation_warnings = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert len(deprecation_warnings) == 1
    assert "deprecated" in str(deprecation_warnings[0].message).lower()


def test_resolve_isolator_none_no_deprecation_warning():
    """resolve_isolator('none') should not emit any deprecation warning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolve_isolator("none")

    deprecation_warnings = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert len(deprecation_warnings) == 0
