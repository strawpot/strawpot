"""Tests for ClaudeSessionProvider and AgentSession."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agents.context import SessionContext
from core.agents.providers.claude_session import ClaudeSessionProvider
from core.agents.session import AgentSession, SessionStatus
from core.agents.types import Charter, ModelConfig
from core.skills.types import SkillFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_charter(**kwargs) -> Charter:
    defaults = dict(name="charlie", role="implementer")
    defaults.update(kwargs)
    return Charter(**defaults)


def make_context(**kwargs) -> SessionContext:
    charter = kwargs.pop("charter", make_charter())
    return SessionContext(charter=charter, **kwargs)


def make_skill(title: str) -> SkillFile:
    return SkillFile(
        path=Path(f"{title}.md"),
        scope="role",
        role="implementer",
        title=title,
        content=f"# {title}\n\nContent.",
    )


# ---------------------------------------------------------------------------
# ClaudeSessionProvider.spawn
# ---------------------------------------------------------------------------


class TestClaudeSessionProvider:
    @pytest.fixture
    def provider(self):
        return ClaudeSessionProvider(claude_path="claude")

    @pytest.fixture
    def workdir(self, tmp_path: Path) -> Path:
        return tmp_path / "workdir"

    async def _spawn(self, provider, charter, workdir, **ctx_kwargs):
        ctx = make_context(charter=charter, **ctx_kwargs)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            return await provider.spawn(charter, workdir, ctx)

    # --- settings.json written correctly ---

    async def test_writes_settings_json(self, provider, workdir):
        charter = make_charter()
        await self._spawn(provider, charter, workdir)

        settings_path = workdir / ".claude" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        hooks = data["hooks"]["SessionStart"][0]["hooks"]
        assert any(h["command"] == "lt prime --hook" for h in hooks)

    async def test_settings_includes_allowed_tools(self, provider, workdir):
        charter = make_charter(allowed_tools=["Read", "Write"])
        await self._spawn(provider, charter, workdir)

        data = json.loads((workdir / ".claude" / "settings.json").read_text())
        assert data["permissions"]["allow"] == ["Read", "Write"]

    # --- runtime files written correctly ---

    async def test_writes_agent_json(self, provider, workdir):
        charter = make_charter(name="charlie", role="implementer")
        await self._spawn(provider, charter, workdir)

        agent_json = workdir / ".loguetown" / "runtime" / "agent.json"
        assert agent_json.exists()
        data = json.loads(agent_json.read_text())
        assert data["name"] == "charlie"
        assert data["role"] == "implementer"

    async def test_writes_work_txt(self, provider, workdir):
        charter = make_charter()
        await self._spawn(provider, charter, workdir, work="Build the login page.")

        work_file = workdir / ".loguetown" / "runtime" / "work.txt"
        assert work_file.exists()
        assert work_file.read_text() == "Build the login page."

    async def test_no_work_removes_work_txt(self, provider, workdir):
        charter = make_charter()
        # First spawn with work
        await self._spawn(provider, charter, workdir, work="task 1")
        # Second spawn without work
        await self._spawn(provider, charter, workdir, work=None)
        work_file = workdir / ".loguetown" / "runtime" / "work.txt"
        assert not work_file.exists()

    # --- tmux command construction ---

    async def test_tmux_session_name(self, provider, workdir):
        charter = make_charter(name="charlie")
        captured = {}

        async def fake_exec(*args, **kwargs):
            captured["args"] = args
            proc = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        ctx = make_context(charter=charter)
        with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_exec)):
            await provider.spawn(charter, workdir, ctx)

        cmd = captured["args"]
        assert "lt-charlie" in cmd

    async def test_tmux_uses_model_id(self, provider, workdir):
        charter = make_charter(model=ModelConfig(provider="claude_session", id="claude-opus-4-6"))
        captured = {}

        async def fake_exec(*args, **kwargs):
            captured["args"] = args
            proc = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        ctx = make_context(charter=charter)
        with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_exec)):
            await provider.spawn(charter, workdir, ctx)

        cmd = list(captured["args"])
        assert "--model" in cmd
        assert "claude-opus-4-6" in cmd

    async def test_spawn_returns_agent_session(self, provider, workdir):
        charter = make_charter()
        session = await self._spawn(provider, charter, workdir)
        assert isinstance(session, AgentSession)
        assert session.session_name == "lt-charlie"
        assert session.charter is charter

    async def test_spawn_failure_raises(self, provider, workdir):
        charter = make_charter()
        ctx = make_context(charter=charter)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"session exists"))
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            with pytest.raises(RuntimeError, match="Failed to start tmux session"):
                await provider.spawn(charter, workdir, ctx)

    def test_provider_name(self, provider):
        assert provider.name == "claude_session"


# ---------------------------------------------------------------------------
# AgentSession
# ---------------------------------------------------------------------------


class TestAgentSession:
    @pytest.fixture
    def session(self, tmp_path: Path) -> AgentSession:
        return AgentSession(
            session_name="lt-charlie",
            workdir=tmp_path,
            charter=make_charter(),
        )

    def test_is_alive_false_when_tmux_not_running(self, session):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert session.is_alive is False

    def test_is_alive_true_when_tmux_running(self, session):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert session.is_alive is True

    def test_status_running(self, session):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert session.status == SessionStatus.RUNNING

    def test_status_completed(self, session):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert session.status == SessionStatus.COMPLETED

    async def test_wait_returns_when_not_alive(self, session):
        # Already dead — should return immediately on first poll
        call_count = 0

        def fake_is_alive():
            nonlocal call_count
            call_count += 1
            return False  # dead from the start

        with patch.object(type(session), "is_alive", property(lambda self: fake_is_alive())):
            result = await session.wait(poll_interval=0)

        assert result.status == SessionStatus.COMPLETED
        assert result.duration_seconds is not None

    async def test_terminate_calls_tmux(self, session):
        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock()
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)) as mock_exec:
            await session.terminate()
            cmd = mock_exec.call_args[0]
            assert "kill-session" in cmd
            assert "lt-charlie" in cmd

    def test_repr(self, session):
        with patch.object(type(session), "is_alive", property(lambda self: False)):
            r = repr(session)
            assert "lt-charlie" in r
            assert "charlie" in r


# ---------------------------------------------------------------------------
# Agent.spawn integration
# ---------------------------------------------------------------------------


async def test_agent_spawn_delegates_to_provider(tmp_path: Path):
    from core.agents.agent import Agent

    charter = make_charter()
    provider = ClaudeSessionProvider(claude_path="claude")
    agent = Agent(charter=charter, provider=provider)

    ctx = make_context(charter=charter, work="Do the thing.")
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        session = await agent.spawn(tmp_path / "workdir", ctx)

    assert isinstance(session, AgentSession)


async def test_agent_spawn_rejects_completion_provider():
    from core.agents.agent import Agent
    from core.agents.providers.claude_api import ClaudeAPIProvider

    charter = make_charter()
    with patch("core.agents.providers.claude_api.anthropic.AsyncAnthropic"):
        provider = ClaudeAPIProvider(api_key="test")
    agent = Agent(charter=charter, provider=provider)

    ctx = make_context(charter=charter)
    with pytest.raises(TypeError, match="does not support sessions"):
        await agent.spawn(Path("/tmp/workdir"), ctx)


async def test_agent_run_rejects_session_provider():
    from core.agents.agent import Agent

    charter = make_charter()
    provider = ClaudeSessionProvider(claude_path="claude")
    agent = Agent(charter=charter, provider=provider)

    with pytest.raises(TypeError, match="does not support completion"):
        await agent.run("hello")
