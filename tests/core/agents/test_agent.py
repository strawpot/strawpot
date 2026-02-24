"""Tests for Agent — uses a stub provider, no network required."""
from __future__ import annotations

from typing import AsyncIterator

import pytest

from core.agents.agent import Agent
from core.agents.types import AgentResponse, Charter, Message


class StubProvider:
    """Minimal in-memory provider for testing."""

    def __init__(self, reply: str = "stub reply") -> None:
        self.reply = reply
        self.calls: list[dict] = []

    @property
    def name(self) -> str:
        return "stub"

    async def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 8096,
        **kwargs,
    ) -> AgentResponse:
        self.calls.append({"messages": list(messages), "system": system, "model": model})
        return AgentResponse(content=self.reply, model="stub-model")

    async def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 8096,
        **kwargs,
    ) -> AsyncIterator[str]:
        self.calls.append({"messages": list(messages), "system": system, "model": model})
        for word in self.reply.split():
            yield word + " "


@pytest.fixture
def charter():
    return Charter(name="charlie", role="implementer", instructions="Be precise.")


@pytest.fixture
def provider():
    return StubProvider()


@pytest.fixture
def agent(charter, provider):
    return Agent(charter=charter, provider=provider)


# ------------------------------------------------------------------
# complete (run)
# ------------------------------------------------------------------


async def test_run_returns_response(agent, provider):
    response = await agent.run("hello")
    assert response.content == "stub reply"
    assert response.model == "stub-model"


async def test_run_appends_to_history(agent):
    await agent.run("first")
    await agent.run("second")
    history = agent.history
    assert len(history) == 4
    assert history[0] == {"role": "user", "content": "first"}
    assert history[1]["role"] == "assistant"
    assert history[2] == {"role": "user", "content": "second"}
    assert history[3]["role"] == "assistant"


async def test_run_passes_system_instructions(agent, provider, charter):
    await agent.run("hi")
    assert provider.calls[-1]["system"] == charter.instructions


async def test_run_reset_clears_history(agent):
    await agent.run("first")
    await agent.run("second", reset=True)
    assert len(agent.history) == 2  # only the reset turn


async def test_reset_method_clears_history(agent):
    await agent.run("hello")
    assert len(agent.history) == 2
    agent.reset()
    assert agent.history == []


# ------------------------------------------------------------------
# stream
# ------------------------------------------------------------------


async def test_stream_yields_chunks(agent):
    chunks = []
    async for chunk in agent.stream("hello"):
        chunks.append(chunk)
    assert len(chunks) > 0
    assert "".join(chunks).strip() == "stub reply"


async def test_stream_appends_to_history(agent):
    async for _ in agent.stream("hello"):
        pass
    history = agent.history
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"].strip() == "stub reply"


async def test_stream_reset_clears_history(agent):
    await agent.run("first")
    async for _ in agent.stream("second", reset=True):
        pass
    assert len(agent.history) == 2


# ------------------------------------------------------------------
# repr
# ------------------------------------------------------------------


def test_repr(agent):
    r = repr(agent)
    assert "charlie" in r
    assert "implementer" in r
    assert "stub" in r
