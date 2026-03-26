"""StrawPot MCP memory server — expose memory as tools and resources for Claude Code."""

from __future__ import annotations

import json
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    ReadResourceResult,
    Resource,
    TextContent,
    TextResourceContents,
    Tool,
)

from strawpot.memory.standalone import (
    CLI_AGENT_ID,
    CLI_ROLE,
    CLI_SESSION_ID,
    get_standalone_provider,
)

# Route MCP logs to stderr (stdio transport uses stdout for protocol).
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger(__name__)

app = Server("strawpot-memory")

# ---------------------------------------------------------------------------
# Lazy provider — instantiated once on first use
# ---------------------------------------------------------------------------

_provider = None


def _get_provider():
    global _provider
    if _provider is None:
        _provider = get_standalone_provider()
    return _provider


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

_TOOLS = [
    Tool(
        name="memory_remember",
        description="Store a fact in project memory for AI agents to recall later.",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact to remember."},
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords for retrieval matching (optional).",
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "global", "role"],
                    "default": "project",
                    "description": "Storage scope.",
                },
            },
            "required": ["content"],
        },
    ),
    Tool(
        name="memory_recall",
        description="Search stored memories matching a query.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "scope": {
                    "type": "string",
                    "description": "Filter to scope (project, global, role). Empty = all.",
                    "default": "",
                },
                "max_results": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum results.",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="memory_forget",
        description="Delete a specific memory entry by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": "ID of the memory entry to delete.",
                },
            },
            "required": ["entry_id"],
        },
    ),
    Tool(
        name="memory_list",
        description="List all stored memories.",
        inputSchema={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Filter to scope. Empty = all scopes.",
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum entries to return.",
                },
            },
        },
    ),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        provider = _get_provider()

        if name == "memory_remember":
            result = provider.remember(
                session_id=CLI_SESSION_ID,
                agent_id=CLI_AGENT_ID,
                role=CLI_ROLE,
                content=arguments["content"],
                keywords=arguments.get("keywords"),
                scope=arguments.get("scope", "project"),
            )
            if result.status == "duplicate":
                text = "Already remembered (near-duplicate detected)."
            else:
                text = f"Remembered. ID: {result.entry_id}, scope: {arguments.get('scope', 'project')}"
            return CallToolResult(content=[TextContent(type="text", text=text)])

        elif name == "memory_recall":
            result = provider.recall(
                session_id=CLI_SESSION_ID,
                agent_id=CLI_AGENT_ID,
                role=CLI_ROLE,
                query=arguments["query"],
                scope=arguments.get("scope", ""),
                max_results=arguments.get("max_results", 10),
            )
            if not result.entries:
                return CallToolResult(
                    content=[TextContent(type="text", text="No memories found.")]
                )
            entries = [
                {
                    "entry_id": e.entry_id,
                    "content": e.content,
                    "keywords": e.keywords,
                    "scope": e.scope,
                    "score": round(e.score, 2),
                }
                for e in result.entries
            ]
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(entries, indent=2))]
            )

        elif name == "memory_forget":
            result = provider.forget(entry_id=arguments["entry_id"])
            if result.status == "deleted":
                text = f"Deleted memory {arguments['entry_id']}."
            else:
                text = f"Memory {arguments['entry_id']} not found."
            return CallToolResult(content=[TextContent(type="text", text=text)])

        elif name == "memory_list":
            result = provider.list_entries(
                scope=arguments.get("scope", ""),
                limit=arguments.get("limit", 50),
            )
            if not result.entries:
                return CallToolResult(
                    content=[TextContent(type="text", text="No memories stored.")]
                )
            entries = [
                {
                    "entry_id": e.entry_id,
                    "content": e.content,
                    "keywords": e.keywords,
                    "scope": e.scope,
                    "ts": e.ts,
                }
                for e in result.entries
            ]
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"{result.total_count} memories.\n"
                        + json.dumps(entries, indent=2),
                    )
                ]
            )

        else:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Unknown tool: {name}")],
                isError=True,
            )

    except Exception as exc:
        log.exception("Tool %s failed", name)
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {exc}")],
            isError=True,
        )


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@app.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri="memory://project",
            name="Project Memories",
            description="Persistent project knowledge stored via strawpot remember.",
            mimeType="text/plain",
        ),
    ]


@app.read_resource()
async def read_resource(uri) -> ReadResourceResult:
    uri_str = str(uri)
    if uri_str == "memory://project":
        try:
            provider = _get_provider()
            result = provider.list_entries(scope="", limit=100)
            if not result.entries:
                text = "No memories stored yet."
            else:
                lines = []
                for e in result.entries:
                    line = f"- {e.content}"
                    if e.keywords:
                        line += f" [keywords: {', '.join(e.keywords)}]"
                    lines.append(line)
                text = "\n".join(lines)
            return ReadResourceResult(
                contents=[
                    TextResourceContents(
                        uri=uri, text=text, mimeType="text/plain"
                    )
                ]
            )
        except Exception as exc:
            log.exception("Failed to read resource %s", uri_str)
            return ReadResourceResult(
                contents=[
                    TextResourceContents(
                        uri=uri, text=f"Error loading memories: {exc}", mimeType="text/plain"
                    )
                ]
            )

    raise ValueError(f"Unknown resource: {uri_str}")


# ---------------------------------------------------------------------------
# Server runner
# ---------------------------------------------------------------------------


async def run_server() -> None:
    """Run the MCP server on stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main() -> None:
    """Entry point for the strawpot-mcp command."""
    import asyncio

    asyncio.run(run_server())


if __name__ == "__main__":
    main()
