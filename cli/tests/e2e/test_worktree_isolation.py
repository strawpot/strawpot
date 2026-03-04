"""E2E tests for git worktree isolation and merge strategies."""

import os
import subprocess

import pytest


@pytest.mark.e2e
class TestWorktreeIsolation:
    """Session with worktree isolation creates and cleans up git worktrees."""

    def test_worktree_agent_changes_merged_local(
        self, make_session, git_project, strawpot_home
    ):
        """Agent writes a file in worktree; local merge applies it to base."""
        session = make_session(
            str(git_project),
            task="write from-worktree.txt",
            config_overrides={
                "isolation": "worktree",
                "merge_strategy": "local",
            },
        )
        session.start(str(git_project))

        # After local merge, the file should exist on the base branch
        assert (git_project / "from-worktree.txt").exists()
        assert "Written by stub agent" in (
            git_project / "from-worktree.txt"
        ).read_text()

    def test_worktree_cleanup_removes_worktree(
        self, make_session, git_project, strawpot_home
    ):
        """Worktree directory and branch are removed after session cleanup."""
        session = make_session(
            str(git_project),
            task="noop",
            config_overrides={
                "isolation": "worktree",
                "merge_strategy": "local",
            },
        )
        session.start(str(git_project))

        # No worktrees should remain (only the main one)
        result = subprocess.run(
            ["git", "worktree", "list"],
            cwd=str(git_project),
            capture_output=True,
            text=True,
        )
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 1, f"Expected 1 worktree, got: {result.stdout}"

    def test_worktree_no_changes_merge(
        self, make_session, git_project, strawpot_home
    ):
        """Session with no agent changes merges cleanly (no-op)."""
        session = make_session(
            str(git_project),
            task="noop",
            config_overrides={
                "isolation": "worktree",
                "merge_strategy": "local",
            },
        )
        session.start(str(git_project))

        # Base branch should be unchanged (only README.md from init)
        contents = sorted(
            f.name
            for f in git_project.iterdir()
            if f.name not in (".git", ".strawpot")
        )
        assert contents == ["README.md"]
