# Chat & Community Service Integrations — Design

Support chat services (Telegram) and community platforms (Slack,
Discord) as conversation interfaces. Users interact with StrawPot
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
              Web GUI    Telegram     Slack/Discord
             (built-in)  (adapter)   (adapter)
                    \        |          /
                     +--> imu (project_id=0) <--+
                          |
                     delegates to projects/roles
```

All chat messages route through **imu** — the same self-operation agent
that powers the Bot Imu chat in the GUI. Adapters are thin message
relays between the chat platform and imu's conversation API. imu handles
project/role routing, delegation, and context — the adapter doesn't need
to know about StrawPot internals.

**Why imu as sole entry point:**
- Consistent UX — chat and GUI work the same way
- Adapter stays simple — just a message relay, no routing logic
- imu already handles project/role routing and delegation
- Natural language routing ("fix the login bug in myapp") is better
  than slash commands (`/strawpot bind project=myapp role=developer`)

**Future option:** Direct project binding (bypass imu) for latency-
sensitive or automated workflows (CI/CD bots, alert channels). The
conversation API already supports `project_id` — adapters could target
a specific project conversation instead of imu. Not needed initially.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| imu is the sole entry point | Adapters are simple relays. imu already handles routing, delegation, and context. Same UX as the GUI. |
| Integrations are a new resource type | Reuses existing resource patterns (Strawhub install, config UI, browse/uninstall). Community authors build adapters the same way they build skills. |
| Adapters are standalone processes | Decoupled from GUI lifecycle. A buggy adapter doesn't crash the server. Each can restart/update independently. |
| Adapters consume the public REST API | No internal module imports. Stable contract. No version coupling beyond API compatibility. |
| GUI manages adapter lifecycle | Start/stop/status/logs through the Integrations page. Users don't need terminal access. |
| Distributed via Strawhub | `strawhub install telegram-adapter`. Community can contribute adapters for LINE, WeChat, Teams, etc. |
| One bot per platform, many conversations | Each platform's natural grouping (Telegram chat, Slack thread) maps to a separate imu conversation. No need for multiple bot instances. |
| Task queuing handles async messages | `POST /api/conversations/{id}/tasks` already returns 202 when a session is active. Chat messages during active sessions are automatically queued. |

---

## Conversation Mapping

Each platform's natural threading model determines conversation
boundaries. All conversations route to imu (`project_id=0`).

| Platform | Conversation boundary | How it works |
|----------|----------------------|-------------|
| Telegram | Per-chat (DM or group) | Each DM or group the bot is in = one imu conversation. User sends `/new` to reset. |
| Slack | Per-thread | `@strawpot` mention in channel → new thread, new conversation. Replies in thread → same conversation. DMs work like Telegram. |
| Discord | Per-thread | Same as Slack — mention creates thread, replies continue it. |

The adapter maintains a local mapping of `(platform_id, thread_id) →
conversation_id` in its own SQLite database. This is adapter state, not
GUI state — the GUI only sees imu conversations.

**Example flow (Telegram):**

```
User DMs bot: "fix the login bug in myapp"
  ↓
Adapter: lookup chat_id → conversation_id (or create new)
  ↓
POST /api/conversations/{conv_id}/tasks
  body: {"task": "fix the login bug in myapp"}
  ↓
Response: 201 (session launched) or 202 (queued)
  ↓
Adapter: connect /ws/sessions/{run_id} for real-time updates
  ↓
Session completes → adapter reads summary from conversation
  ↓
Bot replies: "Done. Fixed the login validation in auth.py — ..."
```

**Example flow (Slack):**

```
User in #engineering: "@strawpot fix the login bug"
  ↓
Adapter: create new thread, new imu conversation
  ↓
POST /api/conversations/{conv_id}/tasks
  ↓
Bot replies in thread: "On it..."
  ↓
Session completes → bot posts summary in thread
  ↓
User replies in thread: "now add tests for it"
  ↓
Adapter: same thread → same conversation_id
  ↓
POST /api/conversations/{conv_id}/tasks (queues if previous still running)
```

---

## Integration Resource Type

**Storage:** `~/.strawpot/integrations/<name>/` (global only — integrations
are not project-scoped since they bridge external platforms to the GUI).
No project-local variant (unlike roles/skills which support both).

**Manifest:** `INTEGRATION.md` with YAML frontmatter. Uses `metadata.strawpot`
nesting for consistency with the Strawhub publish/install pipeline, but only
declares fields the GUI actually needs to manage the adapter process:

```yaml
---
name: telegram
description: Telegram bot adapter for StrawPot conversations
metadata:
  strawpot:
    entry_point: python adapter.py
    auto_start: false
    config:
      bot_token:
        type: secret
        required: true
        description: Telegram bot API token from @BotFather
    health_check:
      endpoint: http://localhost:${port}/health
      interval_seconds: 30
---

# Telegram Adapter

Connects a Telegram bot to StrawPot via imu. Messages sent to
the bot become tasks in imu conversations; session outputs are
replied back in the chat.

## Setup

1. Create a bot via @BotFather on Telegram
2. Install this integration and configure the bot token
3. Start the integration from the GUI Integrations page
```

**Frontmatter fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Slug, matches directory name |
| `description` | Yes | One-line summary |
| `metadata.strawpot.entry_point` | Yes | Command to launch the adapter (e.g., `python adapter.py`) |
| `metadata.strawpot.auto_start` | No | Start on GUI launch (default: `false`) |
| `metadata.strawpot.config` | No | Schema for user-facing config (type, required, secret, default, description). Values are passed as env vars at start. |
| `metadata.strawpot.health_check` | No | Endpoint + interval for liveness checks |

Unlike agents/skills/memory, integrations do **not** use `env`, `install`,
`tools`, `params`, or `dependencies`. Those exist for CLI-resolved resources
that need pre-launch validation. Integrations are standalone processes
managed by the GUI — the adapter handles its own environment and setup.
If a `requirements.txt` exists, the GUI runs `pip install -r requirements.txt`
automatically on install.

**Package structure:**

```
~/.strawpot/integrations/telegram/
  INTEGRATION.md      # manifest (frontmatter + docs)
  adapter.py          # entry point
  requirements.txt    # python-telegram-bot, httpx
  .version            # installed version (Strawhub convention, e.g., "0.1.0\n")
  .adapter.db         # local SQLite for platform → conversation mapping (runtime)
```

**Installation:**

```bash
strawhub install integration telegram [--version X.Y.Z]
```

Follows the standard Strawhub install flow: resolve version → download
files → write `.version` marker → run `pip install -r requirements.txt`
if present.

Integrations are **not** added to `strawpot.lock` — they are GUI-managed
resources with lifecycle state (running/stopped), not CLI-resolved
dependencies. The GUI tracks them in its own `integrations` table.

**Publishing:**

Published via `strawhub publish` like other resource types. The Strawhub
registry stores integrations in an `integrations` table + `integrationVersions`
table following the same schema pattern as skills/roles/agents/memory
(slug, versions, files, parsed frontmatter, scan status, stats).

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
│   Bot: @mybot                                        │
│                                                      │
│ ○ Slack             Stopped             [Start] [⚙]  │
│   Not configured                                     │
│                                                      │
│ ○ Discord           Stopped             [Start] [⚙]  │
│   Not configured                                     │
└──────────────────────────────────────────────────────┘
```

**Lifecycle controls:**

| Action | How it works |
|--------|-------------|
| **Install** | `strawhub install <slug>` to `~/.strawpot/integrations/<name>/`. Same as other resource types. |
| **Configure** | Config UI reads `config` schema from manifest frontmatter. Values saved to `gui.db` `integration_config` table. Secrets stored with masked inputs. |
| **Start** | GUI spawns `entry_point` as a subprocess. Passes config as env vars (`STRAWPOT_API_URL`, `STRAWPOT_BOT_TOKEN`, etc.). PID tracked in `gui.db`. |
| **Stop** | GUI sends SIGTERM to subprocess PID. Waits up to 5s, then SIGKILL. |
| **Status** | Process alive check (PID exists) + optional health check endpoint. Status: `running`, `stopped`, `error`. |
| **Logs** | Stream adapter stdout/stderr. Reuses existing `AgentLogViewer` component. Output written to `~/.strawpot/integrations/<name>/.log`. |
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

No `platform_bindings` table in the GUI database — each adapter manages
its own `(platform_id, thread_id) → conversation_id` mapping locally.

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

## Adapter Contract

An adapter is a standalone process that relays messages between a chat
platform and imu via the StrawPot REST API.

**Responsibilities:**

| Responsibility | Description |
|----------------|-------------|
| **Inbound** | Platform message → `POST /api/imu/conversations` (new) or `POST /api/conversations/{id}/tasks` (existing) |
| **Outbound** | Subscribe to `/ws/sessions/{run_id}` for real-time updates. On session completion, read summary and reply in platform thread. |
| **Mapping** | Maintain `(platform_id, thread_id) → conversation_id` in local SQLite. |
| **Output formatting** | Chunk long output for platform limits (Telegram: 4096 chars, Discord: 2000, Slack: 40K blocks). Send recap as reply, full output as file attachment if needed. |
| **Conversation reset** | Handle `/new` command to create a fresh imu conversation for the chat/thread. |
| **Health check** | Expose `GET /health` endpoint for GUI status monitoring (optional). |

**What adapters do NOT do:**
- No project/role selection — imu handles routing
- No session launching — the conversation API handles it
- No context building — imu and the GUI handle it
- No authentication to StrawPot — local-only, no auth needed

---

## Building a Community Adapter

Adapter authors need to implement:

1. A Python script (or any executable) that:
   - Reads `STRAWPOT_API_URL` from env vars
   - Reads platform-specific config from env vars (e.g., `STRAWPOT_BOT_TOKEN`)
   - Connects to the chat platform
   - Relays messages to/from the imu conversation API
   - Maintains a local mapping of platform threads to conversation IDs
   - Exposes a health check endpoint (optional)
2. An `INTEGRATION.md` manifest with config schema
3. A `requirements.txt` for dependencies

The adapter has no dependency on StrawPot internals — only the public
REST API. This makes it possible to write adapters in any language,
though Python is the recommended default for Strawhub distribution.

**Example minimal adapter (Telegram):**

```python
# adapter.py
import os
import sqlite3
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

API_URL = os.environ["STRAWPOT_API_URL"]
BOT_TOKEN = os.environ["STRAWPOT_BOT_TOKEN"]

# Local mapping: telegram chat_id → imu conversation_id
db = sqlite3.connect(".adapter.db")
db.execute("""
    CREATE TABLE IF NOT EXISTS chat_conversations (
        chat_id TEXT PRIMARY KEY,
        conversation_id INTEGER NOT NULL
    )
""")


async def get_or_create_conversation(client: httpx.AsyncClient, chat_id: str) -> int:
    """Find existing imu conversation for this chat, or create a new one."""
    row = db.execute(
        "SELECT conversation_id FROM chat_conversations WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()
    if row:
        return row[0]

    resp = await client.post(f"{API_URL}/api/imu/conversations")
    resp.raise_for_status()
    conv_id = resp.json()["id"]
    db.execute(
        "INSERT INTO chat_conversations (chat_id, conversation_id) VALUES (?, ?)",
        (chat_id, conv_id),
    )
    db.commit()
    return conv_id


async def handle_new(update: Update, context) -> None:
    """Handle /new command — start a fresh conversation."""
    chat_id = str(update.effective_chat.id)
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{API_URL}/api/imu/conversations")
        resp.raise_for_status()
        conv_id = resp.json()["id"]
    db.execute(
        "INSERT OR REPLACE INTO chat_conversations (chat_id, conversation_id) VALUES (?, ?)",
        (chat_id, conv_id),
    )
    db.commit()
    await update.message.reply_text("New conversation started.")


async def handle_message(update: Update, context) -> None:
    """Handle incoming message — submit as task to imu."""
    chat_id = str(update.effective_chat.id)
    text = update.message.text

    async with httpx.AsyncClient() as client:
        conv_id = await get_or_create_conversation(client, chat_id)

        resp = await client.post(
            f"{API_URL}/api/conversations/{conv_id}/tasks",
            json={"task": text},
        )

        if resp.status_code == 202:
            await update.message.reply_text("Queued — will run after current session.")
            return

        run_id = resp.json().get("run_id")
        if not run_id:
            return

        # Wait for session completion and reply with summary
        summary = await wait_for_completion(client, conv_id, run_id)
        await reply_with_summary(update, summary)


async def wait_for_completion(client: httpx.AsyncClient, conv_id: int, run_id: str) -> str:
    """Poll conversation until session completes. Returns summary."""
    import asyncio
    while True:
        await asyncio.sleep(3)
        resp = await client.get(f"{API_URL}/api/conversations/{conv_id}")
        resp.raise_for_status()
        conv = resp.json()
        for session in conv["sessions"]:
            if session["run_id"] == run_id:
                if session["status"] in ("completed", "failed", "stopped"):
                    return session.get("summary") or f"Session {session['status']}."
        # Session still running — keep polling


async def reply_with_summary(update: Update, summary: str) -> None:
    """Reply with summary, chunking for Telegram's 4096 char limit."""
    max_len = 4000  # Leave room for formatting
    if len(summary) <= max_len:
        await update.message.reply_text(summary)
    else:
        for i in range(0, len(summary), max_len):
            await update.message.reply_text(summary[i : i + max_len])


app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("new", handle_new))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.run_polling()
```

---

## Platform-Specific Notes

### Telegram

- **Auth:** Bot token from @BotFather. No OAuth.
- **Transport:** Long polling (simplest) or webhook.
- **Threading:** No native threads. One conversation per chat (DM or group).
- **Reset:** `/new` command starts a fresh imu conversation.
- **Groups:** Bot responds when mentioned (`@botname`) or to all messages
  (configurable). Each group = separate conversation.
- **Limits:** 4096 chars per message. Chunk longer output.

### Slack

- **Auth:** OAuth 2.0 workspace install. Bot token + signing secret.
- **Transport:** Events API (HTTP webhook) or Socket Mode (WebSocket, no
  public URL needed — better for local StrawPot).
- **Threading:** `@strawpot` mention in channel → new thread + new
  conversation. Thread replies → same conversation. DMs → per-DM
  conversation with `/new` reset.
- **Limits:** 40K chars per message in blocks. Rich formatting with
  Block Kit.
- **Socket Mode recommended:** StrawPot runs locally — Socket Mode
  avoids the need for a public URL or ngrok. The adapter connects
  outbound to Slack's WebSocket, no inbound HTTP needed.

### Discord

- **Auth:** Bot token from Developer Portal.
- **Transport:** Gateway WebSocket (required for receiving messages).
- **Threading:** Similar to Slack — mention creates thread, replies
  continue it.
- **Limits:** 2000 chars per message. Chunk aggressively.

---

## Not Planned

| Feature | Reason |
|---------|--------|
| Multi-user / auth | StrawPot is local-first, single-user. Chat messages from anyone in a channel are treated as the StrawPot owner's tasks. |
| Direct project binding | Start with imu-only. If latency becomes an issue, the conversation API already supports targeting specific projects. |
| Rich interactive controls | No inline buttons, forms, or approval flows in chat. Use the GUI for complex interactions. |

---

## Implementation Status

**Phase 1 — Local integrations (no Strawhub)**

Manually place adapters in `~/.strawpot/integrations/<name>/`. GUI
discovers, configures, and manages them. Full feature without registry.

| # | Item | Status |
|---|------|--------|
| 1 | Database: `integrations` + `integration_config` tables | Planned |
| 2 | Backend: integration CRUD API (list, detail, config, uninstall) | Planned |
| 3 | Backend: lifecycle management (start, stop, status, health check) | Planned |
| 4 | Backend: adapter log streaming (SSE) | Planned |
| 5 | Frontend: Integrations page (list, configure, start/stop, logs) | Planned |
| 6 | Reference adapter: Telegram (bot token + long polling) | Planned |
| 7 | Reference adapter: Slack (Socket Mode + Events API) | Planned |
| 8 | Reference adapter: Discord (bot + gateway websocket) | Planned |

**Phase 2 — Strawhub distribution (when demand warrants)**

| # | Item | Status |
|---|------|--------|
| 9 | Strawhub registry: `integrations` + `integrationVersions` tables | Planned |
| 10 | Strawhub CLI: `strawhub publish/install integration` support | Planned |
| 11 | Frontend: browse + install from Strawhub in Integrations page | Planned |
