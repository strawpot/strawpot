# Chat & Community Service Integrations — Design

Support chat services (Telegram) and community platforms (Slack,
Discord) as conversation interfaces. Users interact with StrawPot agents
through familiar messaging platforms instead of (or alongside) the GUI.

**Motivation:** StrawPot's GUI requires the user to be at their desk
watching a browser. Chat integrations enable mobile access, team
visibility, and async workflows — "message the bot, come back later to
see results."

---

## Architecture

```
                 StrawPot GUI (API server)
                /        |          \
          Web GUI    Telegram     Slack
         (built-in)  (adapter)   (adapter)
```

All interfaces are equal consumers of the REST API. The GUI server is the
API backend; the web frontend is one client among many.

**Key design constraint:** Adapters are not part of `strawpot-gui`. They
are community-extensible packages distributed via Strawhub, but managed
through the GUI like other resources (roles, skills, agents, memory).
Unlike those resource types — which are consumed by the StrawPot CLI
during sessions — adapters are standalone processes that consume the GUI's
REST API. They are neither injected into the GUI nor owned by the CLI.

This makes integrations a **new resource type with a runtime contract** —
they follow the same install/configure/uninstall patterns as other
resources, but add lifecycle management (start/stop/status) unique to
their nature as long-running processes.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Integrations are a new resource type | Reuses existing resource patterns (Strawhub install, config UI, browse/uninstall). Community authors build adapters the same way they build skills. |
| Adapters are standalone processes | Decoupled from GUI lifecycle. A buggy adapter doesn't crash the server. Each can restart/update independently. Can run on different machines. |
| Adapters consume the public REST API | No internal module imports. Stable contract. No version coupling beyond API compatibility. |
| GUI manages adapter lifecycle | Start/stop/status/logs through the Integrations page. Users don't need terminal access to manage adapters. |
| Distributed via Strawhub | `strawpot install telegram-adapter`. Community can contribute adapters for LINE, WeChat, Teams, etc. |
| Thread → conversation mapping | Slack thread, Telegram chat, Discord thread each map to a StrawPot conversation. Stored in `platform_bindings` table. |
| Message queuing (GUI Phase 7) is prerequisite | Chat platforms are async by nature. Users fire-and-forget messages. Without queuing, messages during active sessions are lost. |

---

## Integration Resource Type

**Storage:** `~/.strawpot/integrations/<name>/` (global only — integrations
are not project-scoped since they bridge external platforms to the GUI).

**Manifest:** `INTEGRATION.md` with frontmatter (follows the pattern of
`ROLE.md`, `SKILL.md`, `AGENT.md`):

```yaml
---
name: telegram
version: 0.1.0
description: Telegram bot adapter for StrawPot conversations
type: integration
entry_point: python adapter.py
auto_start: false
config:
  bot_token:
    type: secret
    required: true
    description: Telegram bot API token from @BotFather
  default_project:
    type: string
    description: Project name to route messages to by default
  default_role:
    type: string
    default: developer
    description: Role to use when launching sessions
health_check:
  endpoint: http://localhost:${port}/health
  interval_seconds: 30
---

# Telegram Adapter

Connects a Telegram bot to StrawPot conversations. Messages sent to
the bot become tasks in a conversation; session outputs are replied
back in the chat.

## Setup

1. Create a bot via @BotFather on Telegram
2. Install this integration and configure the bot token
3. Start the integration from the GUI Integrations page
```

**Package structure:**

```
~/.strawpot/integrations/telegram/
  INTEGRATION.md      # manifest (frontmatter + docs)
  adapter.py          # entry point
  requirements.txt    # python-telegram-bot
  .version            # version file (Strawhub convention)
```

---

## GUI Lifecycle Management

The GUI adds an **Integrations page** in the sidebar alongside Roles,
Skills, Agents, and Memory. It provides the same browse/install/configure
UX plus lifecycle controls unique to integrations.

**Integrations page:**

```
┌──────────────────────────────────────────────────────┐
│ Integrations                          + Install      │
├──────────────────────────────────────────────────────┤
│ ● Telegram          Running · 2h 14m   [Stop] [Logs]│
│   Bot: @mybot  ·  Project: myapp  ·  Role: developer│
│                                                      │
│ ○ Slack             Stopped             [Start] [⚙]  │
│   Not configured                                     │
│                                                      │
│ ○ Discord           Stopped             [Start] [⚙]  │
│   Workspace: myserver                                │
└──────────────────────────────────────────────────────┘
```

**Lifecycle controls:**

| Action | How it works |
|--------|-------------|
| **Install** | `strawhub install <slug>` to `~/.strawpot/integrations/<name>/`. Same as other resource types. |
| **Configure** | Config UI reads `config` schema from manifest frontmatter. Values saved to `gui.db` `integration_config` table (not `strawpot.toml` — integrations are GUI-managed). Secrets stored with masked inputs (same pattern as resource env vars). |
| **Start** | GUI spawns `entry_point` as a subprocess. Passes config as env vars (`STRAWPOT_API_URL`, `STRAWPOT_BOT_TOKEN`, etc.) plus `--api-url http://localhost:{gui_port}`. PID tracked in `gui.db`. |
| **Stop** | GUI sends SIGTERM to subprocess PID. Waits up to 5s, then SIGKILL. |
| **Status** | Process alive check (PID exists) + optional health check endpoint. Status: `running`, `stopped`, `error`. |
| **Logs** | Stream adapter stdout/stderr. Reuses the existing `AgentLogViewer` component. Adapter output written to `~/.strawpot/integrations/<name>/.log`. |
| **Auto-start** | If `auto_start: true` in manifest (or toggled in GUI), start on GUI launch. |
| **Uninstall** | Stop if running, then remove directory. Same as other resource types. |

---

## Database Additions

```sql
CREATE TABLE integrations (
    name        TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'stopped',  -- stopped | running | error
    pid         INTEGER,
    auto_start  INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    started_at  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE integration_config (
    integration_name TEXT NOT NULL REFERENCES integrations(name) ON DELETE CASCADE,
    key              TEXT NOT NULL,
    value            TEXT,
    PRIMARY KEY (integration_name, key)
);
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/integrations` | List installed integrations with status |
| GET | `/api/integrations/:name` | Integration detail (manifest + config + status) |
| GET | `/api/integrations/:name/config` | Config schema + saved values |
| PUT | `/api/integrations/:name/config` | Save config values |
| POST | `/api/integrations/:name/start` | Start the adapter process |
| POST | `/api/integrations/:name/stop` | Stop the adapter process |
| GET | `/api/integrations/:name/logs` | SSE: stream adapter log output |
| POST | `/api/integrations/install` | Install from Strawhub |
| DELETE | `/api/integrations/:name` | Stop + uninstall |

---

## Adapter Responsibilities

| Responsibility | Description |
|----------------|-------------|
| Inbound | Platform message → `POST /api/conversations/{id}/tasks` |
| Outbound | Poll SSE for session completion → reply in platform thread |
| Mapping | Maintain `(platform, thread_id) → (conversation_id, project_id)` |
| Output formatting | Chunk long output for platform limits (Telegram: 4096 chars, Discord: 2000, Slack: 40K). Send recap as reply, full output as file attachment. |
| Health check | Expose `GET /health` endpoint for GUI status monitoring |

---

## Platform Binding Table

```sql
CREATE TABLE platform_bindings (
    platform    TEXT NOT NULL,    -- 'telegram', 'slack', 'discord'
    thread_id   TEXT NOT NULL,    -- platform-specific thread/chat ID
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (platform, thread_id)
);
```

---

## Project/Role Selection

| Method | Example |
|--------|---------|
| Bind channel to project | `/strawpot bind project=myapp role=developer` |
| Mention-based routing | `@strawpot-dev` vs `@strawpot-reviewer` map to different roles |
| Default per workspace | First-time setup sets a default project |

---

## Building a Community Adapter

Adapter authors need to implement:

1. A Python script (or any executable) that:
   - Accepts `--api-url` and reads config from env vars
   - Connects to the platform (Telegram/Slack/Discord/etc.)
   - Routes messages to/from the StrawPot REST API
   - Exposes a health check endpoint (optional)
2. An `INTEGRATION.md` manifest with config schema
3. A `requirements.txt` for dependencies

The adapter has no dependency on StrawPot internals — only the public
REST API. This makes it possible to write adapters in any language,
though Python is the recommended default for Strawhub distribution.

**Example minimal adapter (Telegram, ~200 lines):**

```python
# adapter.py
import os, asyncio, httpx
from telegram import Update
from telegram.ext import Application, MessageHandler, filters

API_URL = os.environ["STRAWPOT_API_URL"]
BOT_TOKEN = os.environ["STRAWPOT_BOT_TOKEN"]
DEFAULT_PROJECT = os.environ.get("STRAWPOT_DEFAULT_PROJECT")

async def handle_message(update: Update, context):
    chat_id = str(update.effective_chat.id)
    text = update.message.text

    async with httpx.AsyncClient() as client:
        # Find or create conversation for this chat
        conv_id = await get_or_create_conversation(client, chat_id)
        # Submit task
        resp = await client.post(
            f"{API_URL}/api/conversations/{conv_id}/tasks",
            json={"task": text}
        )
        if resp.status_code == 202:
            await update.message.reply_text("Queued — will run after current session.")
        # Poll for completion and reply (simplified)
        ...

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT, handle_message))
app.run_polling()
```

**Implementation order:** Telegram first (simplest — bot token + long
polling, no OAuth), then Slack (OAuth + workspace install + Events API),
then Discord (bot setup + gateway websocket).

---

## Not Planned

| Feature | Reason |
|---------|--------|
| Multi-user / auth | StrawPot is local-first, single-user |
| Kanban / task management | Not our domain; users have existing tools |

---

## Implementation Status

| # | Item | Status |
|---|------|--------|
| 1 | Integration resource type: manifest schema, storage convention, Strawhub distribution | Planned |
| 2 | Database: `integrations` + `integration_config` tables | Planned |
| 3 | Backend: integration CRUD API (list, detail, install, uninstall, config) | Planned |
| 4 | Backend: lifecycle management (start, stop, status, health check) | Planned |
| 5 | Backend: adapter log streaming (SSE) | Planned |
| 6 | Frontend: Integrations page (list, install, configure, start/stop, logs) | Planned |
| 7 | Database: `platform_bindings` table | Planned |
| 8 | Reference adapter: Telegram (bot token + long polling) | Planned |
| 9 | Reference adapter: Slack (OAuth + Events API) | Planned |
| 10 | Reference adapter: Discord (bot + gateway websocket) | Planned |
