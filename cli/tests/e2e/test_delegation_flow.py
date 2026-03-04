"""E2E tests for the delegation flow through real gRPC."""

import os
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).parent
STUB_AGENT_DELEGATE = str(E2E_DIR / "stub_agent_delegate.py")


@pytest.mark.e2e
class TestDelegationFlow:
    """Orchestrator delegates to sub-agent via real denden gRPC server."""

    def test_orchestrator_delegates_to_sub_agent(
        self, make_session, git_project
    ):
        """Full delegation: orchestrator -> gRPC -> handle_delegate -> sub-agent."""
        session = make_session(
            str(git_project),
            task="delegate implementer write delegated.txt",
            agent_script=STUB_AGENT_DELEGATE,
        )
        session.start(str(git_project))

        # Sub-agent should have written the file via delegation
        assert (git_project / "delegated.txt").exists()
        assert "Written by stub agent" in (git_project / "delegated.txt").read_text()

    def test_delegation_policy_denied(self, make_session, git_project):
        """Delegation to a role not in allowed_roles returns DENIED."""
        session = make_session(
            str(git_project),
            task="delegate implementer write denied.txt",
            agent_script=STUB_AGENT_DELEGATE,
            config_overrides={"allowed_roles": ["orchestrator"]},
        )
        session.start(str(git_project))

        # Sub-agent should NOT have run — file must not exist
        assert not (git_project / "denied.txt").exists()

    def test_delegation_depth_limit(self, make_session, git_project):
        """Delegation beyond max_depth returns DENIED."""
        session = make_session(
            str(git_project),
            task="delegate implementer write depth-denied.txt",
            agent_script=STUB_AGENT_DELEGATE,
            config_overrides={"max_depth": 0},
        )
        session.start(str(git_project))

        # Sub-agent should NOT have run — file must not exist
        assert not (git_project / "depth-denied.txt").exists()
