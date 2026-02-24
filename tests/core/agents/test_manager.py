"""Tests for AgentManager."""
from __future__ import annotations

from typing import AsyncIterator

import pytest

from core.agents.manager import AgentManager
from core.agents.types import AgentResponse, Charter, Message, ModelConfig


class StubProvider:
    def __init__(self, name: str = "stub") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def complete(self, messages, *, system=None, model=None, max_tokens=8096, **kw):
        return AgentResponse(content="ok")

    async def stream(self, messages, *, system=None, model=None, max_tokens=8096, **kw):
        yield "ok"


@pytest.fixture
def manager():
    m = AgentManager()
    m.register_provider(StubProvider("stub"))
    return m


@pytest.fixture
def charter():
    return Charter(name="alice", role="reviewer", model=ModelConfig(provider="stub"))


# ------------------------------------------------------------------
# Provider registry
# ------------------------------------------------------------------


def test_register_provider(manager):
    assert "stub" in manager.providers


def test_register_overwrites(manager):
    p2 = StubProvider("stub")
    manager.register_provider(p2)
    assert manager.get_provider("stub") is p2


def test_get_unknown_provider_returns_none(manager):
    assert manager.get_provider("nonexistent") is None


# ------------------------------------------------------------------
# Agent lifecycle
# ------------------------------------------------------------------


def test_create_agent(manager, charter):
    agent = manager.create_agent(charter)
    assert agent.charter is charter
    assert agent.provider.name == "stub"


def test_create_agent_stored(manager, charter):
    agent = manager.create_agent(charter)
    assert manager.get_agent("alice") is agent


def test_create_duplicate_raises(manager, charter):
    manager.create_agent(charter)
    with pytest.raises(ValueError, match="already exists"):
        manager.create_agent(charter)


def test_create_unknown_provider_raises(manager):
    charter = Charter(name="bob", role="planner", model=ModelConfig(provider="unknown"))
    with pytest.raises(ValueError, match="not registered"):
        manager.create_agent(charter)


def test_get_unknown_agent_returns_none(manager):
    assert manager.get_agent("ghost") is None


def test_remove_agent(manager, charter):
    manager.create_agent(charter)
    assert manager.remove_agent("alice") is True
    assert manager.get_agent("alice") is None


def test_remove_nonexistent_agent(manager):
    assert manager.remove_agent("ghost") is False


def test_agents_property_is_copy(manager, charter):
    manager.create_agent(charter)
    snapshot = manager.agents
    manager.remove_agent("alice")
    assert "alice" in snapshot  # snapshot not affected


# ------------------------------------------------------------------
# Multiple providers + agents
# ------------------------------------------------------------------


def test_multiple_providers(manager):
    manager.register_provider(StubProvider("other"))
    assert set(manager.providers) == {"stub", "other"}


def test_multiple_agents(manager):
    c1 = Charter(name="a1", role="planner", model=ModelConfig(provider="stub"))
    c2 = Charter(name="a2", role="reviewer", model=ModelConfig(provider="stub"))
    manager.create_agent(c1)
    manager.create_agent(c2)
    assert set(manager.agents) == {"a1", "a2"}


def test_repr(manager):
    r = repr(manager)
    assert "stub" in r
