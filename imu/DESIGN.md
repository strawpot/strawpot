# IMU — StrawPot Self-Operation Agent

IMU is a cross-project chat session that operates StrawPot itself. Where
normal sessions run agents that work on a project's code, IMU runs an
agent that manages StrawPot: launching sessions, configuring projects,
installing packages, managing cron schedules, and reviewing traces — all
through natural language.

## Goals

1. **Cross-project control plane.** Operate on any registered project
   and on global StrawPot state from a single persistent chat session.
2. **Cron management.** Create, edit, enable/disable, and monitor
   scheduled tasks through conversation.
3. **Self-operation skills.** Teach the agent StrawPot's own CLI,
   config format, and package management via reusable SKILL.md files.
4. **Zero new protocols.** Build on existing session infrastructure —
   interactive mode, roles, skills, DenDen. No new IPC or server.

## Non-Goals

- Running arbitrary code on projects. IMU manages StrawPot; it does
  not directly edit project source code (though it can launch sessions
  that do).

---

## Architecture

IMU is not a special subsystem — it's just a role with skills, launched
like any other session. No custom CLI subcommand, no special protocol.

### Entry Points

**Terminal (CLI):**

```bash
strawpot start --role imu
```

Launches an interactive IMU session in the current terminal. The
working directory doesn't matter — the agent operates on global
StrawPot state via shell commands regardless of where it runs.

**GUI (embedded chat panel):**

The GUI spawns the same session via its existing `launch_session`
infrastructure, bridged to a chat panel through a PTY + WebSocket.

### Session Storage

IMU sessions use the standard session storage path. When launched
from the CLI, sessions go under the current directory's
`.strawpot/sessions/`. When launched from the GUI, the IMU manager
uses `~/.strawpot` as the working directory, so sessions go to
`~/.strawpot/.strawpot/sessions/`.

### No Isolation

IMU always runs with `isolation: none`. It needs to read and write real
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
description: StrawPot self-operation agent — manages projects, sessions, schedules, and packages
metadata:
  strawpot:
    dependencies:
      skills:
        - strawpot-cli
        - strawpot-config
        - strawpot-schedules
        - strawhub-cli
        - strawpot-sessions
    default_agent: strawpot-claude-code
---

# IMU — StrawPot Operator

You are IMU, the self-operation agent for StrawPot. You manage StrawPot
itself: projects, sessions, scheduled tasks, roles, skills, agents, and
configuration.

## What You Can Do

- **Projects**: List registered projects, check their status, view
  installed resources.
- **Sessions**: Launch new sessions on any project, monitor running
  sessions, review completed session traces and logs.
- **Schedules**: Create, update, enable, disable, and delete cron
  schedules. View schedule history and next-run times.
- **Packages**: Search, install, and manage roles, skills, agents, and
  memory providers from StrawHub.
- **Configuration**: View and edit global and per-project
  `strawpot.toml` settings.

## What You Should Not Do

- Do not directly edit project source code. If code changes are needed,
  launch a session with an appropriate role.
- Do not modify StrawPot's own source code (the cli/ or gui/ packages).
- Do not delete session history or artifacts unless explicitly asked.

## Interaction Style

- Be concise. Show command output when relevant, summarize when not.
- When launching sessions, confirm the project, role, and task before
  proceeding.
- When creating schedules, show the cron expression in human-readable
  form and confirm before saving.
- Proactively surface problems: stale sessions, missing credentials,
  failed schedules.
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

Find the session PID from `session.json` and send SIGTERM:

```bash
kill <pid>
```

## Session Status

Check `.strawpot/running/` for active sessions and `.strawpot/sessions/<run_id>/session.json` for details.

## Recovery

Stale sessions (PID dead but still in running/) are cleaned up automatically on next `strawpot start`.
```

### 2. `strawpot-config`

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

### 3. `strawpot-schedules`

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

### 4. `strawhub-cli`

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

### 5. `strawpot-sessions`

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
IMU sessions are stored at `~/.strawpot/.strawpot/sessions/<run_id>/`
(IMU uses `~/.strawpot` as its working directory).

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

IMU is embedded in the GUI as a persistent chat panel. Users can also
run it from the terminal with `strawpot start --role imu`.

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
IMU Session (interactive mode — ask_user loop)
```

IMU uses the **existing interactive session infrastructure** — no
custom PTY bridge, no new IPC protocol. The GUI launches IMU as a
regular interactive session. The agent loops through `ask_user` calls,
each one holding for the user's next message. Output is structured
(chat bubbles, Markdown) rather than raw terminal stream.

This aligns with the "Zero new protocols" goal: interactive mode,
ask_user bridge, session WebSocket, and ConversationView are all
already implemented.

Message flow per turn:

1. User types a message in the IMU chat panel → submitted as an
   `ask_user_response` if the current session is waiting, or spawns
   a new interactive session if none is active.
2. The IMU session's agent processes the request, calls `ask_user`
   with its reply.
3. The file-based bridge writes `ask_user_pending_*.json`; the session
   WebSocket delivers an `ask_user` message to the frontend.
4. The chat panel renders the agent's reply as a chat bubble and waits
   for the user's next input.
5. User replies → `ask_user_response` sent over the WebSocket → bridge
   writes `ask_user_response_*.json` → agent continues.

#### Backend: IMU Virtual Project & Conversation

IMU sessions are stored under a virtual project (id = 0):

```sql
INSERT OR IGNORE INTO projects (id, name, directory, created_at)
VALUES (0, 'IMU', '~/.strawpot', datetime('now'));
```

IMU uses a single persistent conversation (auto-created on first use)
in the `conversations` table with `project_id = 0`. One new session
is spawned per user "submit" if no session is currently waiting for
input. All session WebSocket and ask_user bridge infrastructure is
reused as-is — no new backend modules needed.

**New endpoint:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/imu/conversation` | GET | Return (or create) the IMU conversation. Returns `{ conversation_id }`. |

All other operations use the existing conversation and session APIs:
`POST /api/conversations/{id}/tasks`, `GET /api/conversations/{id}`,
`/ws/sessions/{run_id}`.

#### Frontend: Chat Panel

The IMU chat is a **slide-over panel** accessible from anywhere in the
GUI via a persistent button in the global navigation bar. It does not
navigate away from the current page — the user can monitor sessions
while chatting with IMU.

```
┌─────────────────────────────────────────────────────────────┐
│  StrawPot    Dashboard  Projects  Schedules  Registry  [IMU]│
├───────────────────────────────────────┬─────────────────────┤
│                                       │ IMU                 │
│  (current page content)               │                     │
│                                       │ > What schedules    │
│  Dashboard / Project Detail /         │   are active?       │
│  Session Monitoring / etc.            │                     │
│                                       │ You have 2 active   │
│                                       │ schedules:          │
│                                       │ • daily-github...   │
│                                       │ • weekly-report...  │
│                                       │                     │
│                                       │ > Disable the       │
│                                       │   weekly report     │
│                                       │                     │
│                                       │ Done. "weekly-..."  │
│                                       │ is now disabled.    │
│                                       │                     │
│                                       ├─────────────────────┤
│                                       │ [Type a message...] │
└───────────────────────────────────────┴─────────────────────┘
```

The panel embeds a trimmed `ConversationView`-equivalent component
(the same interleaved-sessions view already implemented for item 12),
scoped to the IMU conversation.

**Panel behavior:**

- **Toggle**: Click the `[IMU]` nav button to slide the panel open
  or closed. Panel width: 400px (resizable).
- **Persist**: Panel state (open/closed) persists across page
  navigations and page refreshes (localStorage).
- **Auto-start**: Submitting the first message creates the IMU
  conversation and launches the first session. A brief "Launching
  IMU..." spinner shows during start.
- **Reconnect**: The existing `useSessionWS` auto-reconnect handles
  WebSocket drops with exponential backoff.
- **History**: `useConversationInfinite` loads recent sessions and
  their chat messages on panel open. `chat_messages.jsonl` persists
  the full conversation across GUI restarts.

**Message rendering:**

- User messages: right-aligned bubbles.
- Agent `ask_user` replies: left-aligned, rendered as Markdown.
- Session outputs (agent summary): rendered via the existing
  `AgentMessage` component when a session completes.
- Pending ask_user: input box active (same `AskUserPanel` component
  used on SessionDetail).

**Quick actions (optional, future):**

Contextual shortcuts above the input box based on the current GUI
page:

- On project detail: "Launch session on {project}"
- On schedules page: "Create new schedule"
- On session detail: "What happened in this session?"

These pre-fill the input box with a suggested message.

### IMU Session Discovery

The GUI session sync scans `~/.strawpot/.strawpot/sessions/` for IMU
session history. These appear in the GUI under the "IMU" virtual
project (project_id = 0, auto-created at startup).

The virtual project row is ensured in `db.py` at startup (same place
as `mark_orphaned_sessions_stopped`). IMU sessions reference
`project_id = 0`.

### Schedule Management from IMU

IMU manages schedules by calling the GUI REST API directly (the GUI
server is always running when the chat panel is open). The
`strawpot-schedules` skill documents the API endpoints.

When IMU runs from the terminal CLI and the GUI is not running, it
can start the GUI server:

```bash
strawpot gui --port 8741 &
```

Future improvement: extract schedule CRUD into a shared library so
both the GUI router and IMU can operate on `gui.db` directly.

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

3. **Virtual IMU project** (id=0) — ensure the row exists in `db.py`
   startup (same place `mark_orphaned_sessions_stopped` runs).
4. **`GET /api/imu/conversation`** — get or create the IMU
   conversation (project_id=0). Returns `{ conversation_id }`.
5. **IMU session storage path** — IMU sessions use `~/.strawpot` as
   the working directory, stored in `~/.strawpot/.strawpot/sessions/`.

No `IMUManager`, no PTY, no `/api/imu/ws` — all handled by existing
`/ws/sessions/{run_id}` and `/api/conversations/{id}/tasks`.

### Phase 3: GUI Chat Frontend

Build the slide-over panel that wraps the existing conversation UI.

6. **IMU nav button** — persistent `[IMU]` button in the global
   navigation bar.
7. **Slide-over chat panel** — resizable side panel that renders the
   IMU conversation using `useConversationInfinite` + `useSessionWS`.
   Persists open/closed state in localStorage.
8. **Submit input** — text input sends via existing
   `POST /api/conversations/{id}/tasks` (new session) or
   `respond()` from `useSessionWS` (active ask_user reply).
9. **Connection management** — reuses `useSessionWS` auto-reconnect;
   "Launching IMU..." spinner shown while first session starts.

### Phase 4: Session History & Schedules

11. **IMU session discovery** — scan IMU sessions in `sync_sessions()`,
    IMU badge in the GUI.
12. **Session list in chat panel** — dropdown to browse past IMU
    sessions and view their traces.
13. **`strawpot schedule` CLI commands** (optional) — `list`, `create`,
    `update`, `enable`, `disable`, `delete`, `history` for terminal
    users who don't want to curl the GUI API.

### Phase 5: Persistent Context

Give IMU memory across sessions.

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

## Open Questions

1. **Project discovery.** When IMU launches a session on a project, it
   needs the project's directory path. Should IMU discover projects
   from `gui.db`, from scanning directories, or require the user to
   specify a path? For MVP, the user specifies the path or name.

2. ~~**Terminal output vs structured messages.**~~ **Resolved.** IMU
   uses the ask_user bridge (structured JSON messages), not raw PTY
   output. No ANSI parsing needed; agent replies render as Markdown
   chat bubbles via existing `chat_messages.jsonl` → session WS.

3. **Chat panel vs dedicated page.** The slide-over panel keeps IMU
   accessible alongside other pages but has limited width. Should
   there also be a full-page IMU view for longer conversations?
   Start with the panel; add a "pop out" button if users want more
   space.

4. ~~**Session continuity across GUI restarts.**~~ **Resolved.** On
   GUI startup `mark_orphaned_sessions_stopped()` marks any
   `running`/`starting` sessions as `stopped` — IMU sessions
   included. The next user message spawns a fresh interactive session.
   `chat_messages.jsonl` persists the full chat history across
   restarts. Memory provider handles long-term context continuity.
