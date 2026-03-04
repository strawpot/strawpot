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

        # Session artifacts should be cleaned up
        sessions_dir = git_project / ".strawpot" / "sessions"
        if sessions_dir.exists():
            assert len(list(sessions_dir.iterdir())) == 0

    def test_session_cleanup_removes_artifacts(self, make_session, git_project):
        """Session directory is removed after normal completion."""
        session = make_session(str(git_project), task="noop")
        session.start(str(git_project))

        sessions_dir = git_project / ".strawpot" / "sessions"
        if sessions_dir.exists():
            remaining = list(sessions_dir.iterdir())
            assert len(remaining) == 0, f"Stale session dirs: {remaining}"

    def test_default_task_prints_message(self, make_session, git_project):
        """Agent with no special task prints default message."""
        session = make_session(str(git_project), task="hello world")
        session.start(str(git_project))

        # No files should be created for a generic task
        contents = [
            f.name
            for f in git_project.iterdir()
            if f.name not in ("README.md", ".git", ".strawpot")
        ]
        assert contents == []
