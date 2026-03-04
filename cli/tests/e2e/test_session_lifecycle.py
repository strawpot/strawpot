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

    def test_session_cleanup_unconditional(self, make_session, git_project):
        """Session dir is created during run and fully removed after."""
        session = make_session(str(git_project), task="write cleanup-test.txt")
        session.start(str(git_project))

        # File was written, proving the session actually ran
        assert (git_project / "cleanup-test.txt").exists()

        # .strawpot/sessions must be gone or empty — not conditionally skipped
        sessions_dir = git_project / ".strawpot" / "sessions"
        if sessions_dir.exists():
            remaining = list(sessions_dir.iterdir())
            assert remaining == [], f"Stale session dirs: {remaining}"
