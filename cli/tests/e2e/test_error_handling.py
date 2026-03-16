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

        # Session should still clean up (running/ should be empty)
        running_dir = git_project / ".strawpot" / "running"
        if running_dir.exists():
            active = list(running_dir.iterdir())
            assert len(active) == 0

    def test_delegation_timeout(self, make_session, git_project):
        """Sub-agent that exceeds timeout is killed during delegation."""
        session = make_session(
            str(git_project),
            task="delegate implementer sleep 30",
            agent_script=STUB_AGENT_DELEGATE,
            config_overrides={"agent_timeout": 2},
        )
        # Should not hang — timeout kills the sub-agent.
        # The orchestrator may exit 0 (error handled) or non-zero
        # (propagated failure) depending on timing; both are acceptable.
        try:
            session.start(str(git_project))
        except SystemExit:
            pass

        # Session should still clean up (running/ should be empty)
        running_dir = git_project / ".strawpot" / "running"
        if running_dir.exists():
            active = list(running_dir.iterdir())
            assert len(active) == 0

    def test_delegation_subagent_failure_returns_error(self, make_session, git_project):
        """Sub-agent that exits non-zero causes ERROR response to calling agent."""
        session = make_session(
            str(git_project),
            task="delegate implementer exit 1",
            agent_script=STUB_AGENT_DELEGATE,
        )
        session.start(str(git_project))

        # The orchestrator (stub_agent_delegate) receives ERROR from denden
        # and prints "Delegation error: ..." — verify it saw the error
        result = session._orchestrator_result
        assert result is not None
        assert "Delegation error:" in result.output

    def test_stale_session_recovery(self, git_project, make_config, strawpot_home):
        """Stale session files with dead PIDs are cleaned up."""
        config = make_config()

        # Write a fake stale session file with a dead PID + running symlink
        strawpot_dir = git_project / ".strawpot"
        session_dir = strawpot_dir / "sessions" / "run_stale123"
        session_dir.mkdir(parents=True)
        session_file = session_dir / "session.json"
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
        running_dir = strawpot_dir / "running"
        running_dir.mkdir(parents=True, exist_ok=True)
        (running_dir / "run_stale123").symlink_to("../sessions/run_stale123")

        recovered = recover_stale_sessions(str(git_project), config)
        assert "run_stale123" in recovered

        # Session dir stays, running symlink removed, archive symlink created
        assert session_dir.is_dir()
        assert not (running_dir / "run_stale123").is_symlink()
        archived = strawpot_dir / "archive" / "run_stale123"
        assert archived.is_symlink()
