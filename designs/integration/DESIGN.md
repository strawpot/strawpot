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
Adapter: conversation poller detects new session → watches for completion
  ↓
Session completes → adapter reads summary from conversation
  ↓
Bot replies: "Done. Fixed the login validation in auth.py — ..."
```

The conversation poller also picks up sessions started by other sources
(GUI, scheduler, another adapter). Any session that completes in a
conversation the adapter is watching gets relayed back to the platform.

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
    install:
      macos: pip install -r requirements.txt
      linux: pip install -r requirements.txt
    env:
      STRAWPOT_BOT_TOKEN:
        required: true
        description: Telegram bot API token from @BotFather
      POLL_INTERVAL:
        required: false
        description: Session poll interval in seconds when WebSocket fails (default 3)
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
| `metadata.strawpot.env` | No | User-configurable environment variables (same convention as skills/agents). Keys are env var names, fields: `required`, `description`. Values saved in GUI and passed at start. |
| `metadata.strawpot.health_check` | No | Endpoint + interval for liveness checks |
| `metadata.strawpot.install` | No | OS-keyed install commands (same convention as agents). Run by `strawhub install`. |

**Note:** `auto_start` is managed in the GUI database, not in the
manifest. Users toggle it via the detail sheet in the Integrations page.

Unlike agents/skills/memory, integrations do **not** use `tools`,
`params`, or `dependencies`. Those exist for CLI-resolved resources
that need pre-launch validation. Integrations are standalone processes
managed by the GUI — the adapter handles its own environment and setup.
The `env` field follows the same convention as skills/agents: keys are
env var names, values declare `required` and `description`. The GUI
saves values and passes them as environment variables when starting
the adapter process.

**Auto-set environment variables:** The GUI automatically sets the
following env vars when starting an adapter — these should **not** be
declared in the manifest's `env` schema:

| Variable | Description |
|----------|-------------|
| `STRAWPOT_API_URL` | Full URL of the running StrawPot API server (derived from `request.base_url`) |
| `STRAWPOT_DATA_DIR` | Persistent data directory for the adapter (`~/.strawpot/data/integrations/<name>/`). Survives reinstalls. |

If a `requirements.txt` exists, the GUI runs `pip install -r requirements.txt`
automatically on install.

**Package structure:**

```
~/.strawpot/integrations/telegram/
  INTEGRATION.md      # manifest (frontmatter + docs)
  adapter.py          # entry point
  requirements.txt    # python-telegram-bot, httpx
  .version            # installed version (Strawhub convention, e.g., "0.1.0\n")
  .log                # stdout/stderr log (runtime, streamed to GUI)

~/.strawpot/data/integrations/telegram/
  adapter.db          # local SQLite for platform → conversation mapping (runtime)
```

Adapter runtime data (conversation mappings, etc.) is stored in
`STRAWPOT_DATA_DIR` (`~/.strawpot/data/integrations/<name>/`), separate
from the integration code directory. This ensures data survives
reinstalls (which delete and recreate the code directory).

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

The page uses the standard resource pattern — a table listing all
installed integrations. Clicking a row opens a detail sheet with
config fields, lifecycle controls, and an auto-start toggle.

```
┌───────────────────────────────────────────────────────┐
│ Integrations                           [+ Install]    │
├───────────┬─────────────────────────┬─────────────────┤
│ Name      │ Description             │ Status          │
├───────────┼─────────────────────────┼─────────────────┤
│ telegram  │ Telegram bot adapter    │ ● Running       │
│ slack     │ Slack bot adapter       │ ○ Stopped       │
│ discord   │ Discord bot adapter     │ ○ Stopped       │
└───────────┴─────────────────────────┴─────────────────┘

Detail sheet (click row):
┌──────────────────────────────────────────────┐
│ telegram   ● Running                         │
│ Telegram bot adapter for StrawPot            │
│                                              │
│ Path: ~/.strawpot/integrations/telegram      │
│ Started: 2026-03-16 10:00 AM                 │
│ PID: 12345                                   │
│                                              │
│ [✓] Start automatically when StrawPot        │
│     launches                                 │
│                                              │
│ Configuration                                │
│ STRAWPOT_BOT_TOKEN*  [••••••••••]            │
│ [Save Configuration]                         │
│                                              │
│ [Stop] [Logs] [Update] [Reinstall] [Uninst.] │
└──────────────────────────────────────────────┘
```

**Lifecycle controls:**

| Action | How it works |
|--------|-------------|
| **Install** | `strawhub install <slug>` to `~/.strawpot/integrations/<name>/`. Same as other resource types. |
| **Configure** | Config UI reads `env` schema from manifest frontmatter. Values saved to `gui.db` `integration_config` table. All values use password inputs (typically tokens/secrets). |
| **Start** | GUI spawns `entry_point` as a subprocess. Passes config + auto-set env vars (`STRAWPOT_API_URL`, `STRAWPOT_DATA_DIR`). PID tracked in `gui.db`. |
| **Stop** | GUI sends SIGTERM to subprocess PID. |
| **Status** | Process alive check (PID exists) + optional health check endpoint. Status: `running`, `stopped`, `error`. |
| **Logs** | Stream adapter stdout/stderr via WebSocket. Output written to `~/.strawpot/integrations/<name>/.log`. Log panel supports search, select-all, copy-all, and clear. |
| **Auto-start** | Toggle in detail sheet. Stored in `gui.db` `integrations.auto_start`. On GUI launch, all integrations with `auto_start=1` are started automatically. |
| **Update** | Stop if running → `strawhub update` → restart if was running. |
| **Reinstall** | Stop if running → `strawhub reinstall` → restart if was running. Data in `STRAWPOT_DATA_DIR` is preserved. |
| **Uninstall** | Stop if running → remove code directory. Data directory is preserved. |

**Startup behavior:**

On GUI startup, `mark_orphaned_integrations_stopped` sends SIGTERM to
all processes marked as running in the DB (they may be stale from a
previous crash pointing at the wrong API URL). Then
`auto_start_integrations` re-launches those with `auto_start=1`.

**Shutdown behavior:**

On GUI shutdown, `stop_all_integrations` sends SIGTERM to all running
adapter processes.

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
| PUT | `/api/integrations/:name/auto-start` | Toggle auto-start (`{"enabled": true/false}`) |
| DELETE | `/api/integrations/:name/config` | Clear saved config |
| POST | `/api/integrations/:name/start` | Start the adapter process |
| POST | `/api/integrations/:name/stop` | Stop the adapter process |
| GET | `/api/integrations/:name/status` | Check live status (process alive + health check) |
| WS | `/api/integrations/:name/logs/ws` | WebSocket: stream adapter log output |
| POST | `/api/integrations/install` | Install from Strawhub |
| POST | `/api/integrations/update` | Stop → update → restart if was running |
| POST | `/api/integrations/reinstall` | Stop → reinstall → restart if was running |
| DELETE | `/api/integrations/:name` | Stop + uninstall |
| POST | `/api/integrations/:name/notify` | Queue a notification for the adapter |
| GET | `/api/integrations/:name/notifications` | Poll pending notifications (adapter use) |
| POST | `/api/integrations/:name/notifications/:id/ack` | Mark notification as delivered |

---

## Adapter Contract

An adapter is a standalone process that relays messages between a chat
platform and imu via the StrawPot REST API.

**Responsibilities:**

| Responsibility | Description |
|----------------|-------------|
| **Inbound** | Platform message → `POST /api/imu/conversations` (new) or `POST /api/conversations/{id}/tasks` (existing) |
| **Outbound** | Poll conversations for new sessions (from any source — chat, GUI, scheduler). On session completion, read summary and reply in platform thread. |
| **Mapping** | Maintain `(platform_id, thread_id) → conversation_id` in local SQLite. |
| **Output formatting** | Chunk long output for platform limits (Telegram: 4096 chars, Discord: 2000, Slack: 40K blocks). Send recap as reply, full output as file attachment if needed. |
| **Conversation reset** | Handle `/new` command to create a fresh imu conversation for the chat/thread. |
| **Health check** | Expose `GET /health` endpoint for GUI status monitoring (optional). |
| **Notifications** | Poll `GET /api/integrations/{name}/notifications` and deliver to platform (optional). |

**What adapters do NOT do:**
- No project/role selection — imu handles routing
- No session launching — the conversation API handles it
- No context building — imu and the GUI handle it
- No authentication to StrawPot — local-only, no auth needed

---

## Building a Community Adapter

Adapter authors need to implement:

1. A Python script (or any executable) that:
   - Reads `STRAWPOT_API_URL` from env (auto-set by GUI)
   - Reads `STRAWPOT_DATA_DIR` from env for persistent state (auto-set by GUI, falls back to `Path(__file__).parent`)
   - Reads platform-specific config from env vars (e.g., `STRAWPOT_BOT_TOKEN`)
   - Connects to the chat platform
   - Relays messages to/from the imu conversation API
   - Maintains a local mapping of platform threads to conversation IDs (stored in `STRAWPOT_DATA_DIR`)
   - Polls watched conversations for new/completed sessions (from any source — chat, GUI, scheduler)
   - Handles SIGTERM for graceful shutdown
   - Exposes a health check endpoint (optional)
   - Polls for direct notifications (optional — see Integration Notifications)
2. An `INTEGRATION.md` manifest with `env` schema (only user-configurable vars — not `STRAWPOT_API_URL` or `STRAWPOT_DATA_DIR`)
3. A `requirements.txt` for dependencies

The adapter has no dependency on StrawPot internals — only the public
REST API. This makes it possible to write adapters in any language,
though Python is the recommended default for Strawhub distribution.

**Environment variables available to adapters:**

| Variable | Source | Description |
|----------|--------|-------------|
| `STRAWPOT_API_URL` | Auto-set by GUI | Full URL of the StrawPot API server |
| `STRAWPOT_DATA_DIR` | Auto-set by GUI | Persistent data directory (survives reinstalls) |
| `STRAWPOT_BOT_TOKEN` | User-configured | Platform bot token (declared in `env` schema) |
| *(other env vars)* | User-configured | Any additional vars declared in the manifest `env` schema |

**Example minimal adapter (Telegram):**

```python
# adapter.py
import asyncio
import os
import sqlite3
from pathlib import Path
import httpx
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters

API_URL = os.environ["STRAWPOT_API_URL"]
BOT_TOKEN = os.environ["STRAWPOT_BOT_TOKEN"]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "3"))

# Persistent data directory (auto-set by GUI, falls back to script directory)
DATA_DIR = Path(os.environ.get("STRAWPOT_DATA_DIR") or str(Path(__file__).parent))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Local mapping: telegram chat_id → imu conversation_id
db = sqlite3.connect(str(DATA_DIR / "adapter.db"))
db.execute("""
    CREATE TABLE IF NOT EXISTS chat_conversations (
        chat_id          TEXT PRIMARY KEY,
        conversation_id  INTEGER NOT NULL,
        last_session_id  TEXT    -- last session run_id the adapter has seen
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

        # Session launched — the conversation poller will pick up
        # the result and reply when it completes. No need to block here.


# ── Conversation poller ─────────────────────────────────────────
# Background task: polls all watched conversations for new completed
# sessions. Picks up results from ANY source — chat, GUI, scheduler.

async def conversation_poller(bot: Bot, client: httpx.AsyncClient):
    """Poll watched conversations and relay completed sessions to Telegram."""
    while True:
        try:
            rows = db.execute(
                "SELECT chat_id, conversation_id, last_session_id "
                "FROM chat_conversations"
            ).fetchall()
            for chat_id, conv_id, last_seen in rows:
                resp = await client.get(f"{API_URL}/api/conversations/{conv_id}")
                if resp.status_code != 200:
                    continue
                conv = resp.json()
                for session in conv.get("sessions", []):
                    run_id = session["run_id"]
                    if run_id == last_seen:
                        break  # Already seen this and older sessions
                    if session["status"] in ("completed", "failed", "stopped"):
                        summary = session.get("summary") or f"Session {session['status']}."
                        await send_summary(bot, chat_id, summary)
                        db.execute(
                            "UPDATE chat_conversations SET last_session_id = ? "
                            "WHERE chat_id = ?",
                            (run_id, chat_id),
                        )
                        db.commit()
                        break  # Process one session at a time
        except Exception:
            pass  # Log in real adapter
        await asyncio.sleep(POLL_INTERVAL)


async def send_summary(bot: Bot, chat_id: str, summary: str) -> None:
    """Send summary to Telegram, chunking for 4096 char limit."""
    max_len = 4000
    if len(summary) <= max_len:
        await bot.send_message(chat_id=chat_id, text=summary)
    else:
        for i in range(0, len(summary), max_len):
            await bot.send_message(chat_id=chat_id, text=summary[i : i + max_len])


app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("new", handle_new))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Start conversation poller alongside Telegram polling
async def post_init(application: Application) -> None:
    client = httpx.AsyncClient()
    asyncio.create_task(conversation_poller(application.bot, client))

app.post_init = post_init
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

## ask_user Handling for Chat-Originated Sessions

When a chat adapter submits a task to imu, the resulting session may
trigger an `ask_user` event — the agent needs human input to proceed.
In the GUI this opens a prompt dialog, but chat-originated sessions have
no GUI user watching. Three approaches, in order of complexity:

### Option 1: Route ask_user back through chat (long-term goal)

The adapter subscribes to the session WebSocket. When it receives an
`ask_user` event, it forwards the question to the chat user and relays
their reply back via a new API endpoint (e.g.,
`POST /api/sessions/{run_id}/reply`). This gives the best UX — the user
stays in their chat app for the full interaction.

**Requires:** A reply API endpoint, adapter awareness of ask_user events,
and per-platform UX for prompting the user (inline message + wait for
reply).

### Option 2: GUI-only prompt

ask_user events appear only in the GUI. The chat user gets a message
like "Action needed — check the StrawPot GUI to respond." Works but
breaks the "stay in chat" experience.

### Option 3: Disable ask_user for chat sessions (initial approach)

Sessions launched from chat adapters run with `ask_user` disabled —
agents must proceed without human input or fail gracefully. This is the
simplest starting point and avoids building reply infrastructure before
validating the chat workflow.

**How:** The adapter passes a flag (e.g., `"interactive": false`) when
submitting a task. The session launcher propagates this to the agent
config, which suppresses ask_user tool availability.

### Phased approach

Start with **Option 3** — disable ask_user for chat-originated sessions.
This unblocks the full chat integration flow without additional API work.
Move to **Option 1** when chat usage matures and users need interactive
workflows from chat.

---

## Integration Notifications

Scheduled tasks and agent sessions can notify chat integrations — posting
results back to a Telegram group, Slack channel, or Discord thread. This
enables async workflows: "run this report every morning and post to
#engineering."

### Architecture

```
Conversation targeting:

  Schedule fires (scheduler.py)
    ↓
  POST /api/conversations/{conv_id}/tasks   ← if conversation_id set
    ↓
  Session runs in target conversation
    ↓
  Adapter conversation poller detects completed session
    ↓
  Adapter replies in platform chat/thread


Direct notification:

  Session runs (any source — schedule, GUI, chat)
    ↓
  Agent calls POST /api/integrations/{name}/notify   ← via skill
    ↓
  GUI stores notification in integration_notifications table
    ↓
  Adapter polls GET /api/integrations/{name}/notifications
    ↓
  Adapter delivers message to platform (Telegram, Slack, etc.)
```

Two mechanisms work together:

1. **Conversation targeting** — schedules submit tasks to a specific
   conversation. The adapter's conversation poller (see Adapter Contract)
   detects the new completed session and relays the result back to the
   platform. No additional adapter code needed — this works because
   adapters already poll all their watched conversations.

2. **Direct notification** — a `POST /api/integrations/{name}/notify`
   endpoint lets agents explicitly send messages to a chat platform. A
   `notify-integration` skill teaches agents how to use it. This covers
   cases where there's no existing conversation to target (e.g., "post
   to the #alerts channel").

### Why two mechanisms

| Mechanism | Use case |
|-----------|----------|
| Conversation targeting | Continue an existing chat thread (adapter already watches it) |
| Direct notification | Post to a new or specific chat destination (no existing conversation) |

Conversation targeting is implicit — no adapter code change needed, since
adapters already watch their conversations. Direct notification requires
the adapter to implement a notification handler (optional contract
extension).

### Design Decisions

| Decision | Rationale |
|----------|-----------|
| Notify endpoint on GUI, not direct to adapter | Bot tokens stay contained in the adapter. Agents never see platform credentials. |
| Adapter polls for notifications | Reuses existing REST infrastructure. No need for adapters to expose HTTP endpoints. Simple for custom integration authors. |
| Notification handler is optional | Adapters that don't implement it still work — they just can't receive direct notifications. Conversation targeting works without it. |
| One generic `notify-integration` skill | Works for all platforms. Agent doesn't need to know Telegram vs Slack API. |
| Notifications persist in DB | If adapter is temporarily down, notifications are delivered when it restarts. |
| imu role is enforced for `project_id=0` | Schedules and conversations targeting imu (`project_id=0`) must use `role=imu`. The scheduler enforces this — if `project_id=0`, the role is forced to `"imu"` regardless of the schedule's `role` field. Same applies when submitting to an imu conversation via the conversation API. |

### Database Changes

Add `conversation_id` to scheduled tasks (enables conversation targeting):

```sql
ALTER TABLE scheduled_tasks
  ADD COLUMN conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL;
```

Add notification queue table:

```sql
CREATE TABLE IF NOT EXISTS integration_notifications (
    id              INTEGER PRIMARY KEY,
    integration_name TEXT NOT NULL REFERENCES integrations(name) ON DELETE CASCADE,
    chat_id         TEXT,              -- platform-specific destination (chat ID, channel, etc.)
    message         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    delivered_at    TEXT               -- NULL = pending, set when adapter ACKs
);

CREATE INDEX IF NOT EXISTS idx_integration_notifications_pending
    ON integration_notifications(integration_name, delivered_at)
    WHERE delivered_at IS NULL;
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/integrations/:name/notify` | Queue a notification for the adapter |
| GET | `/api/integrations/:name/notifications` | Poll pending notifications (adapter use) |
| POST | `/api/integrations/:name/notifications/:id/ack` | Mark notification as delivered |

**POST /api/integrations/:name/notify**

Called by agents (via skill) or any API consumer. Queues a message for
the adapter to deliver.

```json
{
  "chat_id": "12345",
  "message": "Daily report: 3 sessions completed, 0 failures."
}
```

`chat_id` is platform-specific — a Telegram chat ID, Slack channel ID,
Discord channel/thread ID, etc. The agent learns the target from the
skill prompt or schedule configuration.

**GET /api/integrations/:name/notifications**

Returns pending (undelivered) notifications. Adapter polls this
periodically.

```json
{
  "items": [
    {
      "id": 1,
      "chat_id": "12345",
      "message": "Daily report: ...",
      "created_at": "2026-03-16T10:00:00Z"
    }
  ]
}
```

**POST /api/integrations/:name/notifications/:id/ack**

Adapter calls this after successfully delivering the message. Sets
`delivered_at` timestamp. Acknowledged notifications are excluded from
future polls.

### Adapter Contract Extension

Supporting notifications is **optional**. Adapters that want to receive
direct notifications add a background poller:

| Responsibility | Required | Description |
|----------------|----------|-------------|
| **Poll notifications** | Optional | Periodically `GET /api/integrations/{name}/notifications`, deliver each to the platform, then ACK. |
| **Deliver to platform** | Optional | Use the platform's send API to post `message` to `chat_id`. |

**Example notification poller (Python):**

```python
async def notification_poller(client: httpx.AsyncClient, name: str):
    """Background task: poll for pending notifications and deliver them."""
    while True:
        try:
            resp = await client.get(
                f"{API_URL}/api/integrations/{name}/notifications"
            )
            for item in resp.json().get("items", []):
                await send_to_platform(item["chat_id"], item["message"])
                await client.post(
                    f"{API_URL}/api/integrations/{name}/notifications"
                    f"/{item['id']}/ack"
                )
        except Exception:
            logger.exception("Notification poll failed")
        await asyncio.sleep(5)
```

`send_to_platform()` is adapter-specific — for Telegram it calls the
Bot API `sendMessage`, for Slack it posts via `chat.postMessage`, etc.

### Notification Skills (`notify-<platform>`)

Standalone skills that send messages directly to chat platforms via
their native APIs. Each skill is independent — no dependency on
StrawPot's integration system or adapters. The agent calls the
platform API directly using a bundled helper script.

**Why per-platform skills (not one generic skill):**

| Approach | Problem |
|----------|---------|
| Generic `notify-integration` via StrawPot API | Agent needs to know integration name, chat_id format, and depends on adapter being installed and running |
| One skill that discovers integrations at runtime | Extra API call dependency, still needs platform-specific knowledge |
| **Per-platform skills** | Self-contained, platform-specific knowledge baked in, no dependencies |

**Available skills:**

| Skill | Platform API | Config (env params) |
|-------|-------------|-------------------|
| `notify-telegram` | Telegram Bot API `sendMessage` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DEFAULT_CHAT_ID` (optional) |
| `notify-slack` | Slack `chat.postMessage` | `SLACK_BOT_TOKEN`, `SLACK_DEFAULT_CHANNEL` (optional) |
| `notify-discord` | Discord webhook | `DISCORD_WEBHOOK_URL`, `DISCORD_DEFAULT_CHANNEL_ID` (optional) |

Each skill bundles a helper script (e.g., `scripts/send.py`) that
handles auth and message chunking for platform limits. The agent
calls the script — no need to construct auth headers manually.

**Example `notify-telegram/SKILL.md` frontmatter:**

```yaml
---
name: notify-telegram
description: "Send messages to Telegram chats. Use when a task needs to post results, alerts, or reports to a Telegram group or DM."
metadata:
  strawpot:
    env:
      TELEGRAM_BOT_TOKEN:
        required: true
        description: Telegram bot API token from @BotFather
      TELEGRAM_DEFAULT_CHAT_ID:
        required: false
        description: Default chat ID to send to (numeric, e.g., -100123456789 for groups)
---
```

**Relationship to integration notifications API (#14-#18):**

The notify/poll/ack API endpoints remain for internal use — cron jobs,
adapter-to-adapter push, and any workflow that needs to queue a
notification for an adapter to pick up. The per-platform skills bypass
this entirely and go direct to the platform API.

| Path | Use case |
|------|----------|
| Skills (`notify-telegram`, etc.) | Agent sends message directly to platform — simple, no dependencies |
| Notify API (`POST /api/integrations/:name/notify`) | Internal push to adapter — queued delivery, ACK tracking, works when agent can't reach platform directly |

Both mechanisms coexist. Skills are the primary agent-facing path.
The notify API is infrastructure for adapters and internal workflows.

### Scheduler Behavior

When the scheduler fires a schedule, it checks `conversation_id`:

- **With `conversation_id`:** Builds conversation context from prior
  turns and passes `conversation_id` to `launch_session_subprocess`.
  The session runs within that conversation, and the adapter's
  conversation poller picks up the result.
- **Without `conversation_id`:** Standalone session (original behavior).

**Role enforcement:** Schedules targeting `project_id=0` (imu) get
`role=imu` unless an explicit role is set. This matches the
conversations router: `role = schedule["role"] or ("imu" if project_id == 0 else None)`.

### Schedule → Chat Flow

**Example: daily report posted to a Telegram group**

1. User creates a schedule in the GUI:
   - Task: `Summarize today's sessions and post to Telegram`
   - Skills: `notify-telegram`
   - Cron: `0 9 * * *` (every day at 9am)

2. Scheduler fires → launches session with the task + skill

3. Agent runs the task, generates a summary, then uses
   `notify-telegram` to send directly via the Telegram Bot API

**Example: scheduled task continues an existing chat thread**

1. User in Telegram sends: "set up a daily code review for myapp"
2. imu creates a schedule with `conversation_id` pointing to this
   Telegram-linked conversation
3. Every day, scheduler fires the task into that conversation
4. Telegram adapter is already watching the conversation → picks up the
   session result → replies in the original chat

### Custom Integration Guide

For custom integration authors who want notification support:

1. **Add a notification poller** — background async task that polls
   `GET /api/integrations/{your_name}/notifications` every few seconds
2. **Implement `send_to_platform(chat_id, message)`** — use your
   platform's API to deliver the message
3. **ACK after delivery** — call
   `POST /api/integrations/{your_name}/notifications/{id}/ack`
4. **Document `chat_id` format** — tell users what to put in the
   `chat_id` field (e.g., Telegram numeric chat ID, Slack channel ID)

That's it. No manifest changes needed — notification support is a
runtime behavior, not a declared capability.

---

## Conversation Source Tracking

Conversations created by adapters, the scheduler, or the GUI are
visually indistinguishable. Adding a `source` column to conversations
lets the GUI show platform icons and labels so users can see where a
conversation originated.

### Database Changes

```sql
ALTER TABLE conversations ADD COLUMN source TEXT;       -- NULL=gui, "telegram", "slack", "scheduler", etc.
ALTER TABLE conversations ADD COLUMN source_meta TEXT;   -- JSON, platform-specific context
```

`source` is a short slug used for icon selection. `source_meta` is
freeform JSON carrying platform-specific details the GUI can display.

| source | source_meta example | GUI display |
|--------|-------------------|-------------|
| `NULL` | — | (no badge — default GUI conversation) |
| `"telegram"` | `{"chat_id": "-100123", "chat_title": "Engineering"}` | Telegram icon + "Engineering" |
| `"slack"` | `{"channel_id": "C0123", "channel_name": "#ops", "thread_ts": "1234.5678"}` | Slack icon + "#ops" |
| `"discord"` | `{"channel_id": "98765", "guild_name": "My Server"}` | Discord icon + "My Server" |
| `"scheduler"` | `{"schedule_id": 7, "schedule_name": "daily-report"}` | Clock icon + "daily-report" |

### Who Sets It

- **Adapters** pass `source` and `source_meta` when creating
  conversations via `POST /api/imu/conversations`. The adapter knows
  its own name and the platform context (chat title, channel name).
- **Scheduler** sets `source: "scheduler"` when creating a new
  conversation for a schedule (conversation targeting).
- **GUI** leaves `source` as NULL (the default).

### API Changes

`POST /api/imu/conversations` accepts two new optional fields:

```json
{
  "source": "telegram",
  "source_meta": {"chat_id": "-100123", "chat_title": "Engineering"}
}
```

`GET /api/conversations/:id` and list endpoints include `source` and
`source_meta` in their response.

### Frontend Display

- **Conversation list:** Small platform icon next to the title.
  Telegram paper plane, Slack hash, Discord controller, clock for
  scheduler. No icon when `source` is NULL.
- **Conversation header:** Subtitle line: "via Telegram / Engineering"
  or "via Slack / #ops". Derived from `source` + `source_meta`.
- **imu conversations page:** Source badge in the table row, making it
  easy to see which conversations came from which platform.

### Design Decisions

| Decision | Rationale |
|----------|-----------|
| Two columns (`source` + `source_meta`) instead of one | `source` is a fixed enum for icon/badge logic. `source_meta` is freeform JSON for display labels. Keeps queries simple while allowing platform-specific detail. |
| `source_meta` is JSON TEXT, not separate columns | Each platform has different context. A rigid schema would require migrations for every new platform. JSON is read-only display data — never queried. |
| Set at conversation creation, immutable | A conversation's origin doesn't change. Even if multiple sources submit tasks to it later, it was *started* from one place. |
| NULL means GUI | Most conversations are GUI-originated. NULL as default avoids backfilling existing data. |

### Lifecycle: Deletion and Orphaning

`source` is a display hint, not a foreign key. No cascade behavior
is needed — conversations and integrations are independent resources
that reference each other loosely.

**Conversation deleted, adapter still running:**

The adapter's local mapping (`chat_id → conversation_id`) now points
to a stale ID. When the adapter next submits a task, the API returns
404. The adapter handles this by creating a new conversation and
updating its local mapping. This is adapter-side logic — no GUI
changes needed. Adapters should treat 404 on task submission as
"conversation gone, create a new one."

**Adapter uninstalled, conversations remain:**

Conversations with `source="telegram"` are preserved as historical
records. The GUI shows a dimmed or generic icon when the referenced
integration is not installed. Conversations remain fully functional —
browsable, searchable, and can receive tasks from the GUI or other
sources. `source_meta` retains its value (chat title, channel name)
for display context even after the adapter is gone.

**Adapter reinstalled:**

The adapter creates new conversations by default. However, its
persistent mapping in `STRAWPOT_DATA_DIR` (which survives reinstalls)
may still reference old conversation IDs. If those conversations
exist, the adapter reconnects to them naturally. If they were deleted,
the adapter gets 404 and creates new ones (see above).

**Summary:**

| Scenario | Conversation | Adapter |
|----------|-------------|---------|
| Conversation deleted | Gone | Gets 404, creates new conversation |
| Adapter uninstalled | Preserved, dimmed icon | Gone |
| Adapter reinstalled | Old ones preserved | Reconnects via persisted mapping or creates new |
| Both deleted | Nothing to clean up | Nothing to clean up |

---

## Not Planned

| Feature | Reason |
|---------|--------|
| Multi-user / auth | StrawPot is local-first, single-user. Chat messages from anyone in a channel are treated as the StrawPot owner's tasks. |
| Direct project binding | Start with imu-only. If latency becomes an issue, the conversation API already supports targeting specific projects. |
| Rich interactive controls | No inline buttons, forms, or approval flows in chat. Use the GUI for complex interactions. |

---

## Implementation Status

**Phase 1 — Integration infrastructure**

Manually place adapters in `~/.strawpot/integrations/<name>/`. GUI
discovers, configures, and manages them. Full feature without registry.

| # | Item | Status |
|---|------|--------|
| 1 | Database: `integrations` + `integration_config` tables | Done |
| 2 | Backend: integration CRUD API (list, detail, config, uninstall) | Done |
| 3 | Backend: lifecycle management (start, stop, status, auto-start) | Done |
| 4 | Backend: adapter log streaming (WebSocket) | Done |
| 5 | Frontend: Integrations page (list, configure, start/stop, logs) | Done |
| 6 | Reference adapter: Telegram (bot token + long polling) | Done |
| 7 | Reference adapter: Slack (Socket Mode + Events API) | Done |
| 8 | Reference adapter: Discord (bot + gateway websocket) | Done |

**Phase 2 — imu project conversation support**

Currently imu only has its own conversations (`project_id=0`). When a
chat user says "fix the login bug in myapp", imu delegates a sub-agent
but the work lives in imu's conversation space — disconnected from the
project's conversation history.

Phase 2 gives imu the ability to create or continue conversations in
specific projects. This means:
- Delegated work shows up in the project's conversation history
- Context from prior project conversations is available to the agent
- Users can see and continue the same conversation from chat or GUI

| # | Item | Status |
|---|------|--------|
| 9 | imu tool: `conversation.submit(project, task)` — submit task to a project conversation | Done |
| 10 | GUI: cross-link between imu conversation and project conversation it spawned | Done |

**Phase 3 — Strawhub distribution (when demand warrants)**

| # | Item | Status |
|---|------|--------|
| 11 | Strawhub registry: `integrations` + `integrationVersions` tables | Done |
| 12 | Strawhub CLI: `strawhub publish/install integration` support | Done |
| 13 | Frontend: browse + install from Strawhub in Integrations page | Done |

**Phase 4 — Integration notifications**

Scheduled tasks and agent sessions can notify chat integrations —
posting results back to Telegram groups, Slack channels, etc.

| # | Item | Status |
|---|------|--------|
| 14 | Database: `integration_notifications` table | Done |
| 15 | Database: `conversation_id` column on `scheduled_tasks` | Done |
| 16 | Backend: `POST /api/integrations/:name/notify` endpoint | Done |
| 17 | Backend: `GET /api/integrations/:name/notifications` polling endpoint | Done |
| 18 | Backend: `POST /api/integrations/:name/notifications/:id/ack` endpoint | Done |
| 19 | Scheduler: submit to conversation API when `conversation_id` is set | Done |
| 20 | Scheduler: enforce `role=imu` for `project_id=0` schedules | Done |
| 21a | Skill: `notify-telegram` — direct Telegram Bot API messaging | Done |
| 21b | Skill: `notify-slack` — direct Slack API messaging | Done |
| 21c | Skill: `notify-discord` — direct Discord webhook messaging | Done |
| 22 | Reference adapters: add conversation poller to Telegram/Slack/Discord | Done |
| 23 | Reference adapters: add notification poller to Telegram/Slack/Discord | Done |
| 24 | Frontend: schedule UI — conversation targeting + Imu project support | Done |

**Phase 5 — Conversation source tracking**

Visual indicators showing where a conversation originated (Telegram,
Slack, scheduler, etc.). Platform icons and labels in the conversation
list and header.

| # | Item | Status |
|---|------|--------|
| 25 | Database: `source` + `source_meta` columns on `conversations` | Not started |
| 26 | Backend: accept `source`/`source_meta` in `POST /api/imu/conversations` | Not started |
| 27 | Backend: include `source`/`source_meta` in conversation list/detail responses | Not started |
| 28 | Backend: scheduler sets `source="scheduler"` when creating conversations | Not started |
| 29 | Frontend: platform icon badges in conversation list | Not started |
| 30 | Frontend: "via Platform / label" subtitle in conversation header | Not started |
| 31 | Reference adapters: pass `source`/`source_meta` when creating conversations | Not started |
