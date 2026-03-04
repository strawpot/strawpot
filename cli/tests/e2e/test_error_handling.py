"""E2E tests for error handling and edge cases."""

import json
import os
from pathlib import Path

import pytest

from strawpot.session import recover_stale_sessions

E2E_DIR = Path(__file__).parent
STUB_AGENT_DELEGATE = str(E2E_DIR / "stub_agent_delegate.py")


@pytest.mark.e2e
class TestErrorHandling:
    """Error conditions handled gracefully in E2E context."""

    def test_agent_nonzero_exit(self, make_session, git_project):
        """Session handles agent exiting with non-zero code."""
        session = make_session(str(git_project), task="exit 1")

        with pytest.raises(SystemExit) as exc_info:
            session.start(str(git_project))
        assert exc_info.value.code == 1

        # Session should still clean up
        sessions_dir = git_project / ".strawpot" / "sessions"
        if sessions_dir.exists():
            assert len(list(sessions_dir.iterdir())) == 0

    def test_delegation_timeout(self, make_session, git_project):
        """Sub-agent that exceeds timeout is killed during delegation."""
        session = make_session(
            str(git_project),
            task="delegate implementer sleep 30",
            agent_script=STUB_AGENT_DELEGATE,
            config_overrides={"agent_timeout": 2},
        )
        # Should not hang — timeout kills the sub-agent
        session.start(str(git_project))

        # Session should still clean up after timeout
        sessions_dir = git_project / ".strawpot" / "sessions"
        if sessions_dir.exists():
            assert len(list(sessions_dir.iterdir())) == 0

    def test_stale_session_recovery(self, git_project, make_config, strawpot_home):
        """Stale session files with dead PIDs are cleaned up."""
        config = make_config()

        # Write a fake stale session file with a dead PID
        sessions_dir = git_project / ".strawpot" / "sessions" / "run_stale123"
        sessions_dir.mkdir(parents=True)
        session_file = sessions_dir / "session.json"
        session_file.write_text(
            json.dumps(
                {
                    "run_id": "run_stale123",
                    "working_dir": str(git_project),
                    "isolation": "none",
                    "runtime": "stub_agent",
                    "denden_addr": "127.0.0.1:9999",
                    "pid": 999999,  # dead PID
                    "agents": {},
                }
            )
        )

        recovered = recover_stale_sessions(str(git_project), config)
        assert "run_stale123" in recovered

        # Session directory should be removed
        assert not sessions_dir.exists()
