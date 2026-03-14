"""E2E tests for the full session lifecycle."""

import os

import pytest


@pytest.mark.e2e
class TestSessionLifecycle:
    """Full session start/stop exercising real components in task mode."""

    def test_basic_task_session(self, make_session, git_project):
        """Start a session with a task, verify agent runs and session cleans up."""
        session = make_session(str(git_project), task="write hello.txt")
        session.start(str(git_project))

        # Agent should have written the file
        assert (git_project / "hello.txt").exists()
        assert (git_project / "hello.txt").read_text() == "Written by stub agent\n"

        # running/ should be empty after cleanup, archive/ should have the session
        running_dir = git_project / ".strawpot" / "running"
        assert not list(running_dir.iterdir()) if running_dir.exists() else True
        archive_dir = git_project / ".strawpot" / "archive"
        assert archive_dir.exists()

    def test_session_cleanup_removes_artifacts(self, make_session, git_project):
        """Session directory stays but running symlink is removed."""
        session = make_session(str(git_project), task="noop")
        session.start(str(git_project))

        running_dir = git_project / ".strawpot" / "running"
        active = list(running_dir.iterdir()) if running_dir.exists() else []
        assert active == [], f"Stale running symlinks: {active}"

