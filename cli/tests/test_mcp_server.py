"""Tests for strawpot.mcp.server — MCP memory server tool handlers."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import AnyUrl
from strawpot.mcp.server import call_tool, list_resources, list_tools, read_resource
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


@pytest.fixture
def provider():
    p = MagicMock()
    with patch("strawpot.mcp.server.get_standalone_provider", return_value=p):
        yield p


# -- list_tools ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert names == {
        "memory_remember", "memory_recall", "memory_forget", "memory_list",
        "schedule_create", "schedule_delete", "schedule_list", "schedule_run",
    }


# -- memory_remember ----------------------------------------------------------


@pytest.mark.asyncio
async def test_remember_accepted(provider):
    provider.remember.return_value = RememberResult(
        status="accepted", entry_id="k_abc12345"
    )
    result = await call_tool("memory_remember", {"content": "Uses pytest"})
    assert not result.isError
    assert "k_abc12345" in result.content[0].text


@pytest.mark.asyncio
async def test_remember_duplicate(provider):
    provider.remember.return_value = RememberResult(status="duplicate", entry_id="")
    result = await call_tool("memory_remember", {"content": "Duplicate"})
    assert "duplicate" in result.content[0].text.lower()


@pytest.mark.asyncio
async def test_remember_with_keywords(provider):
    provider.remember.return_value = RememberResult(
        status="accepted", entry_id="k_kw123456"
    )
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
    result = await call_tool("memory_recall", {"query": "auth"})
    data = json.loads(result.content[0].text)
    assert len(data) == 1
    assert data[0]["entry_id"] == "k_r1"
    assert data[0]["score"] == 0.92


@pytest.mark.asyncio
async def test_recall_empty(provider):
    provider.recall.return_value = RecallResult(entries=[])
    result = await call_tool("memory_recall", {"query": "nothing"})
    assert "No memories found" in result.content[0].text


# -- memory_forget ------------------------------------------------------------


@pytest.mark.asyncio
async def test_forget_deleted(provider):
    provider.forget.return_value = ForgetResult(
        status="deleted", entry_id="k_del12345"
    )
    result = await call_tool("memory_forget", {"entry_id": "k_del12345"})
    assert "Deleted" in result.content[0].text


@pytest.mark.asyncio
async def test_forget_not_found(provider):
    provider.forget.return_value = ForgetResult(
        status="not_found", entry_id="k_missing"
    )
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
    result = await call_tool("memory_list", {})
    text = result.content[0].text
    assert "1 memories" in text
    assert "k_l1" in text


@pytest.mark.asyncio
async def test_list_empty(provider):
    provider.list_entries.return_value = ListResult(entries=[], total_count=0)
    result = await call_tool("memory_list", {})
    assert "No memories stored" in result.content[0].text


# -- error handling -----------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool(provider):
    result = await call_tool("nonexistent_tool", {})
    assert result.isError
    assert "Unknown tool" in result.content[0].text


@pytest.mark.asyncio
async def test_tool_exception_returns_error(provider):
    provider.remember.side_effect = RuntimeError("boom")
    result = await call_tool("memory_remember", {"content": "test"})
    assert result.isError
    assert "boom" in result.content[0].text


# -- resources ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_resources():
    resources = await list_resources()
    assert len(resources) == 1
    assert str(resources[0].uri) == "memory://project"


@pytest.mark.asyncio
async def test_read_project_resource(provider):
    provider.list_entries.return_value = ListResult(
        entries=[
            ListEntry(
                entry_id="k_r1", content="Uses pytest", keywords=["testing"],
                scope="project", ts="2026-03-26T12:00:00Z",
            ),
        ],
        total_count=1,
    )
    result = await read_resource(AnyUrl("memory://project"))
    text = result.contents[0].text
    assert "Uses pytest" in text
    assert "testing" in text


@pytest.mark.asyncio
async def test_read_project_resource_empty(provider):
    provider.list_entries.return_value = ListResult(entries=[], total_count=0)
    result = await read_resource(AnyUrl("memory://project"))
    assert "No memories" in result.contents[0].text


@pytest.mark.asyncio
async def test_read_unknown_resource_raises(provider):
    with pytest.raises(ValueError, match="Unknown resource"):
        await read_resource(AnyUrl("memory://unknown"))


@pytest.mark.asyncio
async def test_read_resource_provider_error_raises(provider):
    provider.list_entries.side_effect = RuntimeError("disk error")
    with pytest.raises(RuntimeError, match="disk error"):
        await read_resource(AnyUrl("memory://project"))


@pytest.mark.asyncio
async def test_missing_required_argument(provider):
    """Missing required argument returns a clear error, not a cryptic KeyError."""
    result = await call_tool("memory_remember", {})
    assert result.isError
    assert "Missing required argument" in result.content[0].text
