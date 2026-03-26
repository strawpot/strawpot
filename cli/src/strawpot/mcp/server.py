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


def _text_result(text: str, *, is_error: bool = False) -> CallToolResult:
    """Build a CallToolResult with a single text content block."""
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        isError=is_error,
    )


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
    Tool(
        name="schedule_create",
        description="Create a new scheduled workflow.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Schedule name."},
                "task": {"type": "string", "description": "Task to execute."},
                "cron": {"type": "string", "description": "Cron expression (e.g. '0 8 * * *')."},
                "description": {"type": "string", "description": "Optional description."},
                "role": {"type": "string", "description": "Role to execute as (optional)."},
            },
            "required": ["name", "task", "cron"],
        },
    ),
    Tool(
        name="schedule_list",
        description="List all active schedules.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="schedule_delete",
        description="Remove a scheduled workflow.",
        inputSchema={
            "type": "object",
            "properties": {
                "schedule_id": {"type": "string", "description": "Schedule ID to delete."},
            },
            "required": ["schedule_id"],
        },
    ),
    Tool(
        name="schedule_run",
        description="Trigger a schedule to run immediately.",
        inputSchema={
            "type": "object",
            "properties": {
                "schedule_id": {"type": "string", "description": "Schedule ID to run."},
            },
            "required": ["schedule_id"],
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
            return _text_result(text)

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
                return _text_result("No memories found.")
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
            return _text_result(json.dumps(entries, indent=2))

        elif name == "memory_forget":
            result = provider.forget(entry_id=arguments["entry_id"])
            if result.status == "deleted":
                text = f"Deleted memory {arguments['entry_id']}."
            else:
                text = f"Memory {arguments['entry_id']} not found."
            return _text_result(text)

        elif name == "memory_list":
            result = provider.list_entries(
                scope=arguments.get("scope", ""),
                limit=arguments.get("limit", 50),
            )
            if not result.entries:
                return _text_result("No memories stored.")
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
            return _text_result(
                f"{result.total_count} memories.\n" + json.dumps(entries, indent=2)
            )

        elif name == "schedule_create":
            from strawpot.scheduler.store import ScheduleStore

            store = ScheduleStore()
            schedule = store.create(
                name=arguments["name"],
                task=arguments["task"],
                cron=arguments["cron"],
                description=arguments.get("description", ""),
                role=arguments.get("role", ""),
            )
            text = (
                f"Schedule created. ID: {schedule.schedule_id}\n"
                f"Name: {schedule.name}\n"
                f"Cron: {schedule.cron}\n"
                f"Next run: {schedule.next_run()}"
            )
            return CallToolResult(content=[TextContent(type="text", text=text)])

        elif name == "schedule_list":
            from strawpot.scheduler.store import ScheduleStore

            store = ScheduleStore()
            schedules = store.list_schedules()
            if not schedules:
                return CallToolResult(
                    content=[TextContent(type="text", text="No schedules configured.")]
                )
            entries = [
                {
                    "schedule_id": s.schedule_id,
                    "name": s.name,
                    "cron": s.cron,
                    "task": s.task,
                    "role": s.role,
                    "next_run": s.next_run(),
                    "last_status": s.last_status,
                }
                for s in schedules
            ]
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(entries, indent=2))]
            )

        elif name == "schedule_delete":
            from strawpot.scheduler.store import ScheduleStore

            store = ScheduleStore()
            deleted = store.delete(arguments["schedule_id"])
            if deleted:
                text = f"Deleted schedule {arguments['schedule_id']}."
            else:
                text = f"Schedule {arguments['schedule_id']} not found."
            return CallToolResult(content=[TextContent(type="text", text=text)])

        elif name == "schedule_run":
            # Execution is out of scope — mark as triggered
            from strawpot.scheduler.store import ScheduleStore

            store = ScheduleStore()
            schedule = store.get(arguments["schedule_id"])
            if schedule is None:
                text = f"Schedule {arguments['schedule_id']} not found."
            else:
                store.update_status(arguments["schedule_id"], "triggered")
                text = (
                    f"Triggered schedule '{schedule.name}' ({arguments['schedule_id']}).\n"
                    "Note: Schedule daemon must be running for actual execution."
                )
            return CallToolResult(content=[TextContent(type="text", text=text)])

        else:
            return _text_result(f"Unknown tool: {name}", is_error=True)

    except KeyError as exc:
        return _text_result(f"Missing required argument: {exc}", is_error=True)
    except Exception as exc:
        log.exception("Tool %s failed", name)
        return _text_result(f"Error: {exc}", is_error=True)


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
            raise

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
