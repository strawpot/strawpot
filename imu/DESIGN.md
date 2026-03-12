# Bot Imu — StrawPot Self-Operation Agent

**Bot Imu** is the conversational self-operation agent for StrawPot.
"Imu" is the agent's name; "Bot Imu" is its display name in the GUI,
clearly marking it as an agent rather than a human user or a project.

Where normal sessions run agents that work on a project's code, Bot Imu
runs an agent that manages StrawPot itself: launching sessions,
configuring projects, installing packages, managing cron schedules, and
reviewing traces — all through natural language from a global-level chat
page accessible from the left navigation bar.

## Goals

1. **Global control plane.** Bot Imu operates on any registered project
   and on global StrawPot state from a single persistent chat panel —
   not scoped to one project, accessible from anywhere in the GUI.
2. **Full StrawPot management.** Launch and stop sessions, manage
   resources (roles, skills, agents, memory), edit configs, create and
   delete cron schedules, review traces and logs — all through
   natural language.
3. **Self-operation skills.** Teach Imu StrawPot's own CLI, GUI REST
   API, config format, and package management via reusable SKILL.md files.
4. **Zero new protocols.** Build on existing conversation infrastructure —
   interactive mode, ask_user bridge, ConversationView, session WS.
   No new IPC, no custom WebSocket endpoint, no PTY.

## Non-Goals

- Running arbitrary code on projects. Bot Imu manages StrawPot; it does
  not directly edit project source code (though it can launch sessions
  that do).

---

## Architecture

Bot Imu is not a special subsystem — it's just a role with skills, launched
like any other session. No custom CLI subcommand, no special protocol.

### Entry Points

**Terminal (CLI):**

```bash
strawpot start --role imu
```

Launches an interactive Imu session in the current terminal. The
working directory doesn't matter — the agent operates on global
StrawPot state via shell commands regardless of where it runs.

**GUI (dedicated page):**

The GUI spawns the same session via its existing conversation
infrastructure (`POST /api/conversations/{id}/tasks`), displayed in
the Bot Imu dedicated page using ConversationView.

### Session Storage

Bot Imu sessions use the standard session storage path. When launched
from the CLI, sessions go under the current directory's
`.strawpot/sessions/`. When launched from the GUI, sessions go to
`~/.strawpot/.strawpot/sessions/` (working directory: `~/.strawpot`).

### No Isolation

Bot Imu always runs with `isolation: none`. It needs to read and write real
config files, invoke real CLI commands, and manage real cron schedules.
Worktree isolation would defeat the purpose.

---

## Role: `imu`

```
~/.strawpot/roles/imu/ROLE.md
```

```yaml
---
name: imu
description: Bot Imu — StrawPot self-operation agent. Manages projects, sessions, resources, schedules, and configuration globally.
metadata:
  strawpot:
    dependencies:
      skills:
        - strawpot-cli
        - strawpot-config
        - strawpot-gui-api
        - strawpot-schedules
        - strawhub-cli
        - strawpot-sessions
    default_agent: strawpot-claude-code
---

# Imu — StrawPot Operator

You are **Imu**, the self-operation agent for StrawPot, displayed in
the GUI as **Bot Imu**. You manage StrawPot globally — across all
registered projects — through natural language.

You have full access to StrawPot's CLI commands, GUI REST API, and
configuration files. Your skills teach you exactly how to use each.

## What You Can Do

- **Projects**: List all registered projects and their status via the
  GUI API. Check which sessions are running, how many schedules are
  active, and what resources are installed.

- **Sessions**: Launch new headless or interactive sessions on any
  project (`strawpot start`). Stop running sessions via the GUI API.
  Review completed session traces, logs, and artifacts.

- **Resources**: Search, install, update, and remove roles, skills,
  agents, and memory providers from StrawHub. Apply them globally or
  to a specific project.

- **Configuration**: View and edit global (`~/.strawpot/strawpot.toml`)
  and per-project (`<project>/strawpot.toml`) settings. Validate
  changes before saving.

- **Schedules**: Create, update, enable, disable, and delete cron
  schedules via the GUI API. Show next-run times in human-readable
  form. Review schedule history.

- **Traces & Logs**: Read session traces (`trace.jsonl`), agent logs
  (`.log`), and artifacts to diagnose failures or summarize outcomes.

## What You Should Not Do

- Do not directly edit project source code. If code changes are needed,
  launch a session with the appropriate role (e.g. `implementer`).
- Do not modify StrawPot's own source code (`cli/` or `gui/` packages).
- Do not delete session history or artifacts unless explicitly asked.
- Do not run destructive operations (drop tables, delete projects)
  without explicit user confirmation.

## Interaction Style

- Be concise. Show command output when useful, summarize when verbose.
- Before launching a session, confirm: project, role, task description.
- Before creating or deleting a schedule, confirm the cron expression
  in human-readable form and the target project.
- Before editing config, show the current value and the proposed change.
- Proactively surface issues: stale sessions, missing API keys, failed
  schedules, resources that need updating.
- When the GUI is running, prefer GUI API calls over filesystem
  operations — they are safer and return structured data.
```

---

## Skills

### 1. `strawpot-cli`

Core CLI usage — launching sessions, checking status, stopping sessions.

```
~/.strawpot/skills/strawpot-cli/SKILL.md
```

```yaml
---
name: strawpot-cli
description: StrawPot CLI commands for session management
metadata:
  strawpot:
    tools:
      strawpot:
        description: StrawPot CLI
        install:
          macos: pip install strawpot
          linux: pip install strawpot
---

# StrawPot CLI

## Launch a Session

```bash
# Interactive session on a project
strawpot start --working-dir /path/to/project

# Headless session with a task
strawpot start --working-dir /path/to/project --headless --task "implement feature X"

# Override role and runtime
strawpot start --working-dir /path/to/project --role implementer --runtime strawpot-codex

# With custom system prompt
strawpot start --working-dir /path/to/project --headless --task "fix bug" --system-prompt "Focus on test coverage"
```

## Stop a Session

**Preferred (when GUI is running):** Use the GUI API (see
`strawpot-gui-api` skill — `POST /api/projects/{id}/sessions/{run_id}/stop`).

**Fallback (no GUI):** Find the session PID from `session.json`:

```bash
kill <pid>
```

## Session Status

Check `.strawpot/running/` for active sessions and `.strawpot/sessions/<run_id>/session.json` for details.

## Recovery

Stale sessions (PID dead but still in running/) are cleaned up automatically on next `strawpot start`.
```

### 2. `strawpot-gui-api`

Projects, sessions, and resources via the GUI REST API. Preferred over
CLI filesystem operations when the GUI server is running.

```
~/.strawpot/skills/strawpot-gui-api/SKILL.md
```

```yaml
---
name: strawpot-gui-api
description: StrawPot GUI REST API — projects, sessions, resources
metadata:
  strawpot:
    tools:
      curl:
        description: HTTP client for GUI API calls
        install:
          macos: built-in
          linux: apt install curl
    params:
      gui_port:
        type: integer
        default: 8741
        description: StrawPot GUI port
---

# StrawPot GUI REST API

The GUI exposes a REST API at `http://127.0.0.1:{gui_port}/api`.
Use this when the GUI is running — it is safer and returns structured
JSON rather than requiring filesystem access.

## Check if GUI is Running

```bash
curl -s http://127.0.0.1:8741/api/health
```

If not running, start it: `strawpot gui --port 8741 &`

## Projects

```bash
# List all registered projects
curl -s http://127.0.0.1:8741/api/projects | python3 -m json.tool

# Get a specific project (with session count, resources)
curl -s http://127.0.0.1:8741/api/projects/{id} | python3 -m json.tool
```

Key fields: `id`, `name`, `directory`, `session_count`,
`active_session_count`, `installed_roles`, `installed_skills`.

## Sessions

```bash
# List sessions for a project (newest first, paginated)
curl -s "http://127.0.0.1:8741/api/projects/{id}/sessions?limit=10" | python3 -m json.tool

# Get session detail (status, agents, trace events, tree)
curl -s http://127.0.0.1:8741/api/projects/{id}/sessions/{run_id} | python3 -m json.tool

# Launch a new session
curl -s -X POST http://127.0.0.1:8741/api/projects/{id}/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "task": "implement feature X",
    "role": "implementer",
    "interactive": false
  }' | python3 -m json.tool

# Stop a running session
curl -s -X POST http://127.0.0.1:8741/api/projects/{id}/sessions/{run_id}/stop

# Read an artifact by hash
curl -s http://127.0.0.1:8741/api/sessions/{run_id}/artifacts/{hash}
```

Session status values: `starting`, `running`, `completed`, `failed`, `stopped`.

## Installed Resources

```bash
# List globally installed roles
curl -s http://127.0.0.1:8741/api/registry/roles | python3 -m json.tool

# List globally installed skills
curl -s http://127.0.0.1:8741/api/registry/skills | python3 -m json.tool

# List project-scoped resources
curl -s http://127.0.0.1:8741/api/projects/{id}/resources | python3 -m json.tool

# Install a resource to a project
curl -s -X POST http://127.0.0.1:8741/api/projects/{id}/resources \
  -H "Content-Type: application/json" \
  -d '{"type": "skill", "name": "git-workflow"}' | python3 -m json.tool

# Remove a resource from a project
curl -s -X DELETE http://127.0.0.1:8741/api/projects/{id}/resources/{type}/{name}
```

## Configuration

```bash
# Get project config
curl -s http://127.0.0.1:8741/api/projects/{id}/config | python3 -m json.tool

# Update a config key (PATCH merges, does not overwrite)
curl -s -X PATCH http://127.0.0.1:8741/api/projects/{id}/config \
  -H "Content-Type: application/json" \
  -d '{"runtime": "strawpot-codex", "max_depth": 4}'

# Get global config
curl -s http://127.0.0.1:8741/api/config | python3 -m json.tool
```
```

### 3. `strawpot-config`

Reading and editing configuration files.

```
~/.strawpot/skills/strawpot-config/SKILL.md
```

```yaml
---
name: strawpot-config
description: StrawPot configuration management
metadata:
  strawpot:
    dependencies: []
---

# StrawPot Configuration

## Config Locations

- **Global**: `~/.strawpot/strawpot.toml` — applies to all projects
- **Project**: `<project>/strawpot.toml` — overrides global settings

## Config Sections

```toml
# Default agent runtime
runtime = "strawpot-claude-code"

# Isolation mode: "none" or "worktree"
isolation = "none"

# Orchestrator settings
orchestrator_role = "orchestrator"
permission_mode = "default"

# Delegation policy
max_depth = 3
agent_timeout = 600  # seconds, optional
max_delegate_retries = 0

# Memory provider
memory = "dial"

# Merge strategy: "auto", "local", "pr"
merge_strategy = "auto"

# Agent-specific config
[agents.strawpot-claude-code]
model = "claude-opus-4-6"

# Skill environment variables
[skills.github-issues.env]
GITHUB_TOKEN = "ghp_..."
```

## Editing Config

Use a text editor or `strawpot config` subcommands. Changes to global
config affect all future sessions. Changes to project config only affect
that project.

When editing TOML files, preserve existing comments and formatting.
Only modify the specific fields requested.
```

### 4. `strawpot-schedules`

Cron schedule management through the GUI API.

```
~/.strawpot/skills/strawpot-schedules/SKILL.md
```

```yaml
---
name: strawpot-schedules
description: Manage StrawPot scheduled tasks (cron jobs)
metadata:
  strawpot:
    tools:
      curl:
        description: HTTP client for GUI API calls
        install:
          macos: built-in
          linux: apt install curl
    params:
      gui_port:
        type: integer
        default: 8741
        description: StrawPot GUI port
---

# StrawPot Scheduled Tasks

Scheduled tasks are cron-based jobs that automatically launch StrawPot
sessions. They are managed through the GUI API.

## API Base

```
http://127.0.0.1:{gui_port}/api
```

Check if GUI is running:

```bash
curl -s http://127.0.0.1:8741/api/health
```

If not running, start it with `strawpot gui --port 8741`.

## List Schedules

```bash
curl -s http://127.0.0.1:8741/api/schedules | python3 -m json.tool
```

## Create a Schedule

```bash
curl -s -X POST http://127.0.0.1:8741/api/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "daily-github-triage",
    "project_id": 1,
    "task": "Review open GitHub issues and PRs, triage by priority",
    "cron_expr": "0 9 * * 1-5",
    "role": "github-triage",
    "enabled": true
  }'
```

## Update a Schedule

```bash
curl -s -X PUT http://127.0.0.1:8741/api/schedules/{id} \
  -H "Content-Type: application/json" \
  -d '{
    "cron_expr": "0 8 * * *",
    "task": "Updated task description"
  }'
```

## Enable / Disable

```bash
curl -s -X POST http://127.0.0.1:8741/api/schedules/{id}/enable
curl -s -X POST http://127.0.0.1:8741/api/schedules/{id}/disable
```

## Delete a Schedule

```bash
curl -s -X DELETE http://127.0.0.1:8741/api/schedules/{id}
```

## View Schedule History

```bash
curl -s http://127.0.0.1:8741/api/schedules/{id}/history | python3 -m json.tool
```

## Cron Expression Reference

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6, Sun=0)
│ │ │ │ │
* * * * *
```

Common patterns:
- `0 9 * * 1-5` — weekdays at 9am
- `*/30 * * * *` — every 30 minutes
- `0 0 * * 0` — weekly on Sunday midnight
- `0 */6 * * *` — every 6 hours

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique schedule name |
| `project_id` | integer | yes | Target project |
| `task` | string | yes | Task description for the agent |
| `cron_expr` | string | yes | Cron expression (validated) |
| `role` | string | no | Role override (uses project default if omitted) |
| `system_prompt` | string | no | Custom system prompt |
| `enabled` | boolean | no | Default true |
```

### 5. `strawhub-cli`

Package management — search, install, info.

```
~/.strawpot/skills/strawhub-cli/SKILL.md
```

```yaml
---
name: strawhub-cli
description: StrawHub package management for roles, skills, agents, and memories
metadata:
  strawpot:
    tools:
      strawhub:
        description: StrawHub CLI
        install:
          macos: pip install strawhub
          linux: pip install strawhub
---

# StrawHub CLI

StrawHub is the package registry for StrawPot resources.

## Search Packages

```bash
# Search all resource types
strawhub search "github"

# Search by type
strawhub search --type skill "git"
strawhub search --type role "engineer"
strawhub search --type agent "claude"
```

## Install Packages

```bash
# Install globally
strawhub install skill git-workflow
strawhub install role implementer

# Install to a specific project
strawhub install skill git-workflow --project /path/to/project

# Install a specific version
strawhub install skill git-workflow@1.2.0
```

## View Package Info

```bash
strawhub info skill git-workflow
strawhub info role implementer
```

## List Installed

```bash
# List all globally installed
strawhub list

# List by type
strawhub list --type skill
strawhub list --type role

# List project-scoped
strawhub list --project /path/to/project
```

## Uninstall

```bash
strawhub uninstall skill git-workflow
strawhub uninstall role implementer --project /path/to/project
```
```

### 6. `strawpot-sessions`

Inspecting session traces, logs, and artifacts.

```
~/.strawpot/skills/strawpot-sessions/SKILL.md
```

```yaml
---
name: strawpot-sessions
description: Inspect StrawPot session traces, logs, and artifacts
metadata:
  strawpot:
    dependencies: []
---

# StrawPot Session Inspection

## Session Storage

Sessions are stored at `<project>/.strawpot/sessions/<run_id>/`.
Bot Imu sessions are stored at `~/.strawpot/.strawpot/sessions/<run_id>/`
(Bot Imu uses `~/.strawpot` as its working directory).

## Find Sessions

```bash
# Active sessions for a project
ls <project>/.strawpot/running/

# Archived sessions
ls <project>/.strawpot/archive/

# All sessions
ls <project>/.strawpot/sessions/
```

## Read Session Metadata

```bash
cat <project>/.strawpot/sessions/<run_id>/session.json | python3 -m json.tool
```

Key fields: `run_id`, `working_dir`, `role`, `runtime`, `isolation`,
`started_at`, `pid`, `task`, `agents` (map of agent_id → agent info).

## Read Trace Events

```bash
# All events
cat <project>/.strawpot/sessions/<run_id>/trace.jsonl | python3 -m json.tool --json-lines

# Filter by event type
grep '"event": "delegate_start"' <project>/.strawpot/sessions/<run_id>/trace.jsonl
```

Event types: `session_start`, `session_end`, `delegate_start`,
`delegate_end`, `delegate_denied`, `agent_spawn`, `agent_end`,
`memory_get`, `memory_dump`, `memory_remember`.

## Read Agent Logs

```bash
cat <project>/.strawpot/sessions/<run_id>/agents/<agent_id>/.log
```

## Read Artifacts

Fields ending in `_ref` (e.g., `context_ref`, `output_ref`) are
SHA256[:12] hashes. Read the artifact:

```bash
cat <project>/.strawpot/sessions/<run_id>/artifacts/<hash>
```

## Via GUI API

```bash
# List sessions for a project
curl -s http://127.0.0.1:8741/api/projects/{id}/sessions | python3 -m json.tool

# Session detail with agents and events
curl -s http://127.0.0.1:8741/api/projects/{id}/sessions/{run_id} | python3 -m json.tool

# Read artifact
curl -s http://127.0.0.1:8741/api/sessions/{run_id}/artifacts/{hash}
```
```

---

## GUI Integration

### Embedded Chat

Bot Imu is embedded in the GUI as a persistent chat panel, accessible
from anywhere via the `[Bot Imu]` button in the global navigation bar.
Users can also run it from the terminal with `strawpot start --role imu`.

#### Architecture

```
Browser (React SPA)
  │
  │  WebSocket: /ws/sessions/{run_id}  (existing session WS)
  │
  ▼
Session WebSocket handler
  │
  │  ask_user bridge (file-based, chat_messages.jsonl)
  │
  ▼
Imu Session (interactive mode — ask_user loop)
```

Bot Imu uses the **existing interactive session infrastructure** — no
custom PTY bridge, no new IPC protocol. The GUI launches an Imu session as a
regular interactive session. The agent loops through `ask_user` calls,
each one holding for the user's next message. Output is structured
(chat bubbles, Markdown) rather than raw terminal stream.

This aligns with the "Zero new protocols" goal: interactive mode,
ask_user bridge, session WebSocket, and ConversationView are all
already implemented.

Message flow per turn:

1. User types a message in the Bot Imu chat panel → submitted as an
   `ask_user_response` if the current session is waiting, or spawns
   a new interactive session if none is active.
2. The Imu session's agent processes the request, calls `ask_user`
   with its reply.
3. The file-based bridge writes `ask_user_pending_*.json`; the session
   WebSocket delivers an `ask_user` message to the frontend.
4. The chat panel renders the agent's reply as a chat bubble and waits
   for the user's next input.
5. User replies → `ask_user_response` sent over the WebSocket → bridge
   writes `ask_user_response_*.json` → agent continues.

#### Backend: Global Conversation (project_id = 0)

The existing `conversations` table already supports any `project_id`.
Bot Imu uses `project_id = 0` — a **virtual global project** — to
hold its conversation outside any user project scope.

A virtual project row is ensured at startup in `db.py`:

```sql
INSERT OR IGNORE INTO projects (id, name, directory, created_at)
VALUES (0, 'Bot Imu', '~/.strawpot', datetime('now'));
```

Bot Imu's sessions are stored at `~/.strawpot/.strawpot/sessions/`
(the virtual project uses `~/.strawpot` as its working directory).

**New endpoint (single addition):**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/imu/conversations` | GET | List Bot Imu conversations (project_id=0), newest first. Returns `[{ id, title, created_at, session_count }]`. |
| `POST /api/imu/conversations` | POST | Create a new Bot Imu conversation. Returns `{ conversation_id }`. |

All other operations reuse the existing conversation and session APIs
unchanged — the `project_id = 0` distinction is transparent:

| Operation | Existing API |
|-----------|-------------|
| Submit a message (new session) | `POST /api/conversations/{id}/tasks` |
| Read conversation + sessions | `GET /api/conversations/{id}` |
| Live session updates | `GET /ws/sessions/{run_id}` |
| Reply to ask_user | `ask_user_response` over the session WS |
| Load more history | `GET /api/conversations/{id}?before_id=...` |

#### Frontend: Dedicated Page

Bot Imu is a **dedicated page** at `/imu/:conversationId`, accessible
via the "Bot Imu" entry in the global left navigation bar. When the
user navigates to Bot Imu, the standard left sidebar is replaced by a
conversation list — mirroring the same layout pattern as project
`ConversationView`. This gives Bot Imu full screen real estate for
longer conversations and natural history browsing.

The main content area directly reuses the existing `ConversationView`
component (built for item 12 — chat-mode sessions), scoped to
`project_id = 0`. No new message rendering code is needed — the same
`UserMessage`, chat bubble, `AgentMessage`, and `AskUserPanel`
components render Imu's conversation identically to any project
conversation.

```
┌─────────────────────────────────────────────────────────────┐
│  StrawPot    Dashboard  Projects  Schedules  Registry       │
├──────────────────┬──────────────────────────────────────────┤
│ Bot Imu          │                                          │
│                  │  > What schedules are active?            │
│ + New Conversation│                                          │
│                  │  You have 2 active schedules:            │
│ Today            │  • daily-github-triage                   │
│  10:23am         │    (weekdays 9am — last run: today ✓)    │
│  Managing sche..│  • weekly-report                         │
│                  │    (Fridays 5pm — last run: Mar 7 ✓)    │
│ Yesterday        │                                          │
│  3:15pm          │  > Disable the weekly report             │
│  Install github-│                                          │
│                  │  Done. "weekly-report" is now disabled.  │
│ Mar 9            │                                          │
│  11:02am         │                                          │
│  Review failed .│                                          │
│                  ├──────────────────────────────────────────┤
│                  │ [Type a message...]                      │
└──────────────────┴──────────────────────────────────────────┘
```

**Routes:**

- `/imu` — redirects to the most recent Bot Imu conversation
  (or shows a "Start a conversation" empty state if none exists).
- `/imu/:conversationId` — displays the conversation via
  `ConversationView` (`project_id = 0`).

**Left sidebar (conversation list):**

- Shows all Bot Imu conversations, grouped by date (Today, Yesterday,
  earlier dates), newest first.
- Each entry shows the first user message as a title and a timestamp.
- "New Conversation" button at the top creates a new conversation via
  `POST /api/imu/conversations` and navigates to it.
- Active conversation is highlighted; clicking another navigates to it.
- Conversation list uses `GET /api/imu/conversations` and refreshes
  via the same SSE invalidation as project conversations.

**Page behavior:**

- **Auto-start**: Submitting the first message in a new conversation
  launches the first session. A brief "Launching Bot Imu..." spinner
  shows during start.
- **Reconnect**: The existing `useSessionWS` auto-reconnect handles
  WebSocket drops with exponential backoff.
- **History**: `useConversationInfinite` loads recent sessions for the
  current conversation. `chat_messages.jsonl` persists the full chat
  history across GUI restarts.

**Message rendering:**

- User messages: right-aligned bubbles.
- Agent `ask_user` replies: left-aligned, rendered as Markdown.
- Session outputs (agent summary): rendered via the existing
  `AgentMessage` component when a session completes.
- Pending ask_user: input box active (same `AskUserPanel` component
  used on SessionDetail).
### Bot Imu Session Discovery

The GUI session sync scans `~/.strawpot/.strawpot/sessions/` for Bot
Imu session history. These appear under the "Bot Imu" virtual project
(project_id = 0, auto-created at startup alongside
`mark_orphaned_sessions_stopped`).

The conversation sidebar's infinite scroll (`useConversationInfinite`)
loads sessions newest-first, identical to any project conversation.

### Schedule Management from Bot Imu

Bot Imu manages schedules by calling the GUI REST API directly (the
GUI server is always running when the chat panel is open). The
`strawpot-schedules` skill documents the API endpoints.

When Bot Imu runs from the terminal CLI and the GUI is not running,
it can start the GUI server:

```bash
strawpot gui --port 8741 &
```

Future improvement: extract schedule CRUD into a shared library so
both the GUI router and Bot Imu can operate on `gui.db` directly.

---

## Implementation Plan

### Phase 1: Role & Skills

No code changes. Just Markdown files.

1. **Create the `imu` role** at `~/.strawpot/roles/imu/ROLE.md`.
2. **Create the five skills** at `~/.strawpot/skills/<name>/SKILL.md`.

After this phase, `strawpot start --role imu` works from any terminal.

### Phase 2: GUI Chat Backend

Minimal backend additions — existing session and conversation
infrastructure handles most of the work.

3. **Virtual Bot Imu project** (id=0, name='Bot Imu') — ensure the
   row exists at `db.py` startup alongside `mark_orphaned_sessions_stopped`.
4. **`GET /api/imu/conversations`** and **`POST /api/imu/conversations`** —
   list and create Bot Imu conversations (project_id=0).
5. **Bot Imu session storage path** — IMU sessions use `~/.strawpot` as
   the working directory, stored in `~/.strawpot/.strawpot/sessions/`.

No `IMUManager`, no PTY, no `/api/imu/ws` — all handled by existing
`/ws/sessions/{run_id}` and `/api/conversations/{id}/tasks`.

### Phase 3: GUI Chat Frontend

Build the dedicated Bot Imu page using existing conversation UI components.

6. **Bot Imu nav link** — permanent "Bot Imu" entry in the global left
   navigation sidebar, below `Registry` (or similar position).
7. **Dedicated page** (`/imu` and `/imu/:conversationId`) — left sidebar
   shows conversation list + "New Conversation" button; main content
   renders the selected conversation via `ConversationView`
   (`project_id = 0`). Redirects `/imu` to latest conversation.
8. **Submit input** — text input sends via existing
   `POST /api/conversations/{id}/tasks` (new session) or
   `respond()` from `useSessionWS` (active ask_user reply).
9. **Connection management** — reuses `useSessionWS` auto-reconnect;
   "Launching Bot Imu..." spinner shown while first session starts.

### Phase 4: Session History & Schedules

11. **Bot Imu session discovery** — `sync_sessions()` already handles
    `project_id = 0`; no extra scan needed. "Bot Imu" nav link
    shows a badge when a session is active.
12. **Session list in sidebar** — Bot Imu conversation history
    is automatically loaded via `useConversationInfinite`; each
    session's trace is accessible from the AgentMessage component.
13. **`strawpot schedule` CLI commands** (optional) — `list`, `create`,
    `update`, `enable`, `disable`, `delete`, `history` for terminal
    users who don't want to curl the GUI API.

### Phase 5: Persistent Context

Give Bot Imu memory across sessions.

14. **Enable memory provider** for the `imu` role so it remembers
    prior conversations, user preferences, and recurring tasks.

---

## Example Interactions

### Launch a session

```
> Launch a headless session on strawpot to run tests with the test-runner role

I'll launch that session now.

$ strawpot start --working-dir /Users/woong/projects/strawpot \
    --headless --role test-runner --task "run the full test suite"

Session run_a1b2c3d4e5f6 started. The test-runner agent is working
in headless mode. You can check progress with:

  $ cat /Users/woong/projects/strawpot/.strawpot/sessions/run_a1b2c3d4e5f6/agents/agent_xyz/.log
```

### Create a cron schedule

```
> Set up a daily job to check GitHub issues on strawpot, weekdays at 9am

I'll create a schedule for that. Let me confirm:
- Project: strawpot (id: 1)
- Task: "Review open GitHub issues, triage by priority, and post a summary"
- Schedule: weekdays at 9:00 AM (cron: 0 9 * * 1-5)
- Role: default (orchestrator)

Proceed?

> yes

$ curl -s -X POST http://127.0.0.1:8741/api/schedules \
    -H "Content-Type: application/json" \
    -d '{"name":"daily-github-triage","project_id":1,"task":"Review open GitHub issues, triage by priority, and post a summary","cron_expr":"0 9 * * 1-5","enabled":true}'

Created schedule "daily-github-triage" (id: 3). Next run: tomorrow at 9:00 AM.
```

### Install a package

```
> Install the github-issues skill globally

$ strawhub install skill github-issues

Installed github-issues@1.0.2 globally.
Dependencies resolved: git-basics (already installed).
```

### Manage schedules from GUI chat panel

```
> Show me all active schedules

You have 3 active schedules:

  1. daily-github-triage (strawpot)
     Cron: 0 9 * * 1-5 (weekdays at 9:00 AM)
     Last run: today at 9:00 AM — completed
     Next run: tomorrow at 9:00 AM

  2. nightly-tests (strawpot)
     Cron: 0 2 * * * (daily at 2:00 AM)
     Last run: today at 2:00 AM — failed
     Next run: tomorrow at 2:00 AM

  3. weekly-report (strawpot)
     Cron: 0 17 * * 5 (Fridays at 5:00 PM)
     Last run: Mar 7 at 5:00 PM — completed
     Next run: Mar 14 at 5:00 PM

> The nightly tests failed — what went wrong?

Checking the last session for nightly-tests (run_c3d4e5f6a7b8)...

The test-runner agent failed with exit code 1 after 4m 12s.
The error was a flaky integration test in test_auth.py:

  FAILED tests/test_auth.py::test_token_refresh - TimeoutError

This test has failed in the last 3 nightly runs. You might want to
either fix the test or add a retry. Want me to launch a session to
investigate?

> Yes, launch a session on strawpot to fix that flaky test

Launching:
- Project: strawpot
- Role: implementer
- Task: "Fix flaky test in tests/test_auth.py::test_token_refresh — TimeoutError in last 3 nightly runs"

Session run_e5f6a7b8c9d0 started. You can monitor it in the
Sessions tab.
```

### Review a failed session

```
> What happened in the last session on strawpot?

$ ls /Users/woong/projects/strawpot/.strawpot/archive/
run_f7e8d9c0b1a2

$ cat .strawpot/sessions/run_f7e8d9c0b1a2/session.json

Session run_f7e8d9c0b1a2 ran 12 minutes ago.
- Role: implementer
- Task: "add pagination to the API"
- Status: failed (exit code 1)
- Duration: 3m 42s

The agent spawned 2 sub-agents. The backend-engineer sub-agent
failed with exit code 1. Checking its log...

The error was a missing `GITHUB_TOKEN` env var when the agent
tried to create a PR. You can fix this by setting it in config:

  strawpot config set skills.git-workflow.env.GITHUB_TOKEN "ghp_..."
```

---

## Implementation Status

| # | Item | Phase | Status |
|---|------|-------|---------|
| 1 | Create `imu` role (`ROLE.md`) | 1 — Role & Skills | Done |
| 2 | Create six skills (`strawpot-cli`, `strawpot-gui-api`, `strawpot-config`, `strawpot-schedules`, `strawhub-cli`, `strawpot-sessions`) | 1 — Role & Skills | Done |
| 3 | Virtual Bot Imu project (id=0) in `db.py` startup | 2 — Backend | Planned |
| 4 | `GET /api/imu/conversations` and `POST /api/imu/conversations` | 2 — Backend | Planned |
| 5 | Bot Imu session storage path (`~/.strawpot`) | 2 — Backend | Planned |
| 6 | "Bot Imu" nav link in left sidebar | 3 — Frontend | Planned |
| 7 | Dedicated page (`/imu`, `/imu/:conversationId`) with conversation list sidebar | 3 — Frontend | Planned |
| 8 | Submit input (new session or ask_user reply) | 3 — Frontend | Planned |
| 9 | Connection management + "Launching Bot Imu…" spinner | 3 — Frontend | Planned |
| 10 | Active session badge on Bot Imu nav link | 4 — History | Planned |
| 11 | Conversation history via `useConversationInfinite` + AgentMessage access | 4 — History | Planned |
| 12 | `strawpot schedule` CLI commands (optional) | 4 — History | Planned |
| 13 | Memory provider for cross-session context | 5 — Memory | Planned |

---

## Open Questions

1. ~~**Project discovery.**~~ **Resolved.** Bot Imu calls
   `GET /api/projects` (documented in the `strawpot-gui-api` skill)
   to list all registered projects with their `id`, `name`, and
   `directory`. No filesystem scanning or user-specified paths needed.

2. ~~**Terminal output vs structured messages.**~~ **Resolved.** Bot Imu
   uses the ask_user bridge (structured JSON messages), not raw PTY
   output. No ANSI parsing needed; agent replies render as Markdown
   chat bubbles via existing `chat_messages.jsonl` → session WS.

3. ~~**Chat panel vs dedicated page.**~~ **Resolved.** Bot Imu uses a
   **dedicated page** (`/imu/:conversationId`) with a conversation list
   sidebar — the same layout pattern as project `ConversationView`.
   This provides full screen real estate, natural history browsing,
   and consistent UX with established chat interfaces.

4. ~~**Session continuity across GUI restarts.**~~ **Resolved.** On
   GUI startup `mark_orphaned_sessions_stopped()` marks any
   `running`/`starting` sessions as `stopped` — Bot Imu sessions
   included. The next user message spawns a fresh interactive session.
   `chat_messages.jsonl` persists the full chat history across
   restarts. Memory provider handles long-term context continuity.
