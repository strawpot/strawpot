"""E2E test fixtures — replaces only external boundaries.

Provides:
- strawpot_home: temp dir with fixture roles/skills/agents, sets STRAWPOT_HOME
- git_project: temp git repo with initial commit
- stub_agent_spec: AgentSpec pointing to stub_wrapper.py
- stub_resolver / stub_resolve_role_dirs: real strawhub resolver against fixtures
- make_session: factory for Session objects ready for E2E testing
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from strawpot.agents.registry import AgentSpec
from strawpot.agents.wrapper import WrapperRuntime
from strawpot.config import StrawPotConfig
from strawpot.isolation.protocol import NoneIsolator
from strawpot.session import Session, resolve_isolator

E2E_DIR = Path(__file__).parent
FIXTURES_DIR = E2E_DIR / "fixtures"
STUB_WRAPPER = str(E2E_DIR / "stub_wrapper.py")
STUB_AGENT = str(E2E_DIR / "stub_agent.py")
STUB_AGENT_DELEGATE = str(E2E_DIR / "stub_agent_delegate.py")


@pytest.fixture
def strawpot_home(tmp_path, monkeypatch):
    """Create a temporary STRAWPOT_HOME with test fixture data.

    Copies roles and skills from fixtures/ into a temp dir structured
    like ~/.strawpot/. Creates an AGENT.md for the stub agent wrapper.
    Sets STRAWPOT_HOME env var for the duration of the test.
    """
    home = tmp_path / "strawpot_home"
    home.mkdir()

    # Copy fixture roles and skills
    for subdir in ["roles", "skills"]:
        src = FIXTURES_DIR / subdir
        if src.is_dir():
            shutil.copytree(str(src), str(home / subdir))

    # Create agent directory with AGENT.md pointing to stub_wrapper.py
    agent_dir = home / "agents" / "stub_agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text(
        f"---\n"
        f"name: stub_agent\n"
        f"description: Stub agent for E2E tests\n"
        f"metadata:\n"
        f"  version: '1.0.0'\n"
        f"  strawpot:\n"
        f"    bin:\n"
        f"      macos: {STUB_WRAPPER}\n"
        f"      linux: {STUB_WRAPPER}\n"
        f"---\n"
        f"Stub agent for E2E testing.\n"
    )

    monkeypatch.setenv("STRAWPOT_HOME", str(home))
    return home


@pytest.fixture
def git_project(tmp_path):
    """Create a temporary git repository with an initial commit."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=str(project),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(project),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(project),
        capture_output=True,
    )
    (project / "README.md").write_text("# Test Project\n")
    subprocess.run(
        ["git", "add", "."], cwd=str(project), capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(project),
        capture_output=True,
    )
    return project


@pytest.fixture
def stub_agent_spec():
    """Return an AgentSpec that uses stub_wrapper.py as the wrapper."""
    return AgentSpec(
        name="stub_agent",
        version="1.0.0",
        wrapper_cmd=[sys.executable, STUB_WRAPPER],
        config={},
        env_schema={},
        tools={},
    )


@pytest.fixture
def stub_resolver(strawpot_home):
    """Resolver callable using real strawhub.resolver against fixture data."""
    from strawhub.resolver import resolve

    def _resolve(slug, kind="role"):
        return resolve(slug, kind=kind, global_root=strawpot_home)

    return _resolve


@pytest.fixture
def stub_resolve_role_dirs(strawpot_home):
    """Role-dirs resolver callable against fixture data."""
    from strawhub.version_spec import parse_dir_name

    def _resolve_dirs(slug):
        roles_dir = strawpot_home / "roles"
        if roles_dir.is_dir():
            for entry in roles_dir.iterdir():
                parsed = parse_dir_name(entry.name)
                if parsed and parsed[0] == slug:
                    return str(entry)
        return None

    return _resolve_dirs


@pytest.fixture
def make_config():
    """Factory for StrawPotConfig with E2E defaults."""

    def _make(**overrides):
        defaults = dict(
            runtime="stub_agent",
            isolation="none",
            denden_addr="127.0.0.1:0",
            orchestrator_role="orchestrator",
            allowed_roles=["orchestrator", "implementer"],
            max_depth=3,
            memory="",
        )
        defaults.update(overrides)
        return StrawPotConfig(**defaults)

    return _make


@pytest.fixture
def make_session(
    stub_agent_spec,
    stub_resolver,
    stub_resolve_role_dirs,
    make_config,
    monkeypatch,
):
    """Factory that creates a Session ready for E2E testing.

    Uses WrapperRuntime for both orchestrator and sub-agents.
    Monkeypatches resolve_agent in delegation to use the stub spec.
    """

    def _make(working_dir, task="", config_overrides=None, agent_script=None):
        config = make_config(**(config_overrides or {}))
        wrapper = WrapperRuntime(stub_agent_spec)
        isolator = resolve_isolator(config.isolation)

        # Monkeypatch resolve_agent so delegation uses our stub
        monkeypatch.setattr(
            "strawpot.delegation.resolve_agent",
            lambda name, wd, user_config=None: stub_agent_spec,
        )

        # Optionally override which stub agent script to use
        if agent_script:
            monkeypatch.setenv("STUB_AGENT_SCRIPT", agent_script)

        session = Session(
            config=config,
            wrapper=wrapper,
            runtime=wrapper,  # WrapperRuntime as orchestrator runtime (task mode)
            isolator=isolator,
            resolve_role=stub_resolver,
            resolve_role_dirs=stub_resolve_role_dirs,
            task=task,
        )
        return session

    return _make
