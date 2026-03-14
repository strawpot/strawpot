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

    def test_multi_level_delegation(self, make_session, git_project):
        """Two-level delegation: orchestrator -> forwarder -> implementer."""
        session = make_session(
            str(git_project),
            task="delegate forwarder delegate implementer write chained.txt",
            agent_script=STUB_AGENT_DELEGATE,
            config_overrides={"max_depth": 3},
        )
        session.start(str(git_project))

        # Implementer (depth 2) should have written the file
        assert (git_project / "chained.txt").exists()
        assert "Written by stub agent" in (git_project / "chained.txt").read_text()

    def test_multi_level_delegation_denied_at_depth(self, make_session, git_project):
        """Two-level delegation denied when max_depth=1 (forwarder can't delegate)."""
        session = make_session(
            str(git_project),
            task="delegate forwarder delegate implementer write denied-chain.txt",
            agent_script=STUB_AGENT_DELEGATE,
            config_overrides={"max_depth": 1},
        )
        session.start(str(git_project))

        # Forwarder runs at depth 1, but its delegation to implementer is denied
        assert not (git_project / "denied-chain.txt").exists()
