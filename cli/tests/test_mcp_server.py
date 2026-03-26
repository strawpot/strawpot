"""Tests for strawpot.mcp.server — MCP memory server tool handlers."""

import json
from unittest.mock import MagicMock, patch

import pytest
from strawpot_memory.memory_protocol import (
    ForgetResult,
    ListEntry,
    ListResult,
    RecallEntry,
    RecallResult,
    RememberResult,
)


@pytest.fixture(autouse=True)
def _reset_provider():
    """Reset the lazy provider singleton between tests."""
    import strawpot.mcp.server as mod

    mod._provider = None
    yield
    mod._provider = None


def _mock_provider():
    return MagicMock()


@pytest.fixture
def provider():
    p = _mock_provider()
    with patch("strawpot.mcp.server.get_standalone_provider", return_value=p):
        yield p


# -- list_tools ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools():
    from strawpot.mcp.server import list_tools

    tools = await list_tools()
    names = {t.name for t in tools}
    assert "memory_remember" in names
    assert "memory_recall" in names
    assert "memory_forget" in names
    assert "memory_list" in names


# -- memory_remember ----------------------------------------------------------


@pytest.mark.asyncio
async def test_remember_accepted(provider):
    provider.remember.return_value = RememberResult(
        status="accepted", entry_id="k_abc12345"
    )
    from strawpot.mcp.server import call_tool

    result = await call_tool("memory_remember", {"content": "Uses pytest"})
    assert not result.isError
    assert "k_abc12345" in result.content[0].text


@pytest.mark.asyncio
async def test_remember_duplicate(provider):
    provider.remember.return_value = RememberResult(status="duplicate", entry_id="")
    from strawpot.mcp.server import call_tool

    result = await call_tool("memory_remember", {"content": "Duplicate"})
    assert "duplicate" in result.content[0].text.lower()


@pytest.mark.asyncio
async def test_remember_with_keywords(provider):
    provider.remember.return_value = RememberResult(
        status="accepted", entry_id="k_kw123456"
    )
    from strawpot.mcp.server import call_tool

    await call_tool(
        "memory_remember",
        {"content": "JWT auth", "keywords": ["auth", "jwt"], "scope": "global"},
    )
    call_kwargs = provider.remember.call_args.kwargs
    assert call_kwargs["keywords"] == ["auth", "jwt"]
    assert call_kwargs["scope"] == "global"


# -- memory_recall ------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_with_results(provider):
    provider.recall.return_value = RecallResult(
        entries=[
            RecallEntry(
                entry_id="k_r1", content="JWT auth", keywords=["auth"],
                scope="project", score=0.92,
            ),
        ]
    )
    from strawpot.mcp.server import call_tool

    result = await call_tool("memory_recall", {"query": "auth"})
    data = json.loads(result.content[0].text)
    assert len(data) == 1
    assert data[0]["entry_id"] == "k_r1"
    assert data[0]["score"] == 0.92


@pytest.mark.asyncio
async def test_recall_empty(provider):
    provider.recall.return_value = RecallResult(entries=[])
    from strawpot.mcp.server import call_tool

    result = await call_tool("memory_recall", {"query": "nothing"})
    assert "No memories found" in result.content[0].text


# -- memory_forget ------------------------------------------------------------


@pytest.mark.asyncio
async def test_forget_deleted(provider):
    provider.forget.return_value = ForgetResult(
        status="deleted", entry_id="k_del12345"
    )
    from strawpot.mcp.server import call_tool

    result = await call_tool("memory_forget", {"entry_id": "k_del12345"})
    assert "Deleted" in result.content[0].text


@pytest.mark.asyncio
async def test_forget_not_found(provider):
    provider.forget.return_value = ForgetResult(
        status="not_found", entry_id="k_missing"
    )
    from strawpot.mcp.server import call_tool

    result = await call_tool("memory_forget", {"entry_id": "k_missing"})
    assert "not found" in result.content[0].text


# -- memory_list --------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_entries(provider):
    provider.list_entries.return_value = ListResult(
        entries=[
            ListEntry(
                entry_id="k_l1", content="Fact 1", keywords=["k1"],
                scope="project", ts="2026-03-26T12:00:00Z",
            ),
        ],
        total_count=1,
    )
    from strawpot.mcp.server import call_tool

    result = await call_tool("memory_list", {})
    assert "1 memories" in result.content[0].text
    data_text = result.content[0].text
    assert "k_l1" in data_text


@pytest.mark.asyncio
async def test_list_empty(provider):
    provider.list_entries.return_value = ListResult(entries=[], total_count=0)
    from strawpot.mcp.server import call_tool

    result = await call_tool("memory_list", {})
    assert "No memories stored" in result.content[0].text


# -- error handling -----------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool(provider):
    from strawpot.mcp.server import call_tool

    result = await call_tool("nonexistent_tool", {})
    assert result.isError
    assert "Unknown tool" in result.content[0].text


@pytest.mark.asyncio
async def test_tool_exception_returns_error(provider):
    provider.remember.side_effect = RuntimeError("boom")
    from strawpot.mcp.server import call_tool

    result = await call_tool("memory_remember", {"content": "test"})
    assert result.isError
    assert "boom" in result.content[0].text


# -- resources ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_resources():
    from strawpot.mcp.server import list_resources

    resources = await list_resources()
    assert len(resources) == 1
    assert str(resources[0].uri) == "memory://project"


@pytest.mark.asyncio
async def test_read_project_resource(provider):
    from pydantic import AnyUrl
    provider.list_entries.return_value = ListResult(
        entries=[
            ListEntry(
                entry_id="k_r1", content="Uses pytest", keywords=["testing"],
                scope="project", ts="2026-03-26T12:00:00Z",
            ),
        ],
        total_count=1,
    )
    from strawpot.mcp.server import read_resource

    result = await read_resource(AnyUrl("memory://project"))
    text = result.contents[0].text
    assert "Uses pytest" in text
    assert "testing" in text


@pytest.mark.asyncio
async def test_read_project_resource_empty(provider):
    from pydantic import AnyUrl
    provider.list_entries.return_value = ListResult(entries=[], total_count=0)
    from strawpot.mcp.server import read_resource

    result = await read_resource(AnyUrl("memory://project"))
    assert "No memories" in result.contents[0].text
