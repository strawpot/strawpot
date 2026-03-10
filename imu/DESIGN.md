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
IMU sessions are stored at `~/.strawpot/imu/sessions/<run_id>/`.

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
`memory_get`, `memory_dump`.

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
  │  WebSocket: /api/imu/ws
  │
  ▼
FastAPI WebSocket endpoint
  │
  │  PTY read/write
  │
  ▼
IMU Agent Process (interactive mode)
```

The GUI backend manages a single IMU agent process. Communication
flows through a pseudo-terminal (PTY):

1. **Start**: When the user opens IMU chat (or sends the first
   message), the backend spawns the IMU agent via the wrapper's
   `build` command in interactive mode. The process is attached to a
   PTY so the agent behaves as if talking to a terminal.
2. **User → Agent**: User messages arrive via WebSocket, are written
   to the PTY's stdin.
3. **Agent → User**: Agent output is read from the PTY's stdout and
   streamed back over the WebSocket in real time.
4. **Lifecycle**: The agent process persists across messages within a
   session. Closing the chat panel does not kill the agent — it
   continues in the background. Reopening reconnects to the same
   session.

This approach is **agent-agnostic** — any wrapper's interactive mode
works. No wrapper-specific JSON streaming protocol required.

#### Backend: IMU Manager

A new module `gui/src/strawpot_gui/imu.py` manages the IMU agent
lifecycle:

```python
class IMUManager:
    """Manages the singleton IMU agent process."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._pty_master: int | None = None
        self._run_id: str | None = None
        self._websockets: set[WebSocket] = set()

    async def ensure_running(self) -> str:
        """Start the IMU agent if not already running. Return run_id."""
        if self._process and self._process.poll() is None:
            return self._run_id
        return await self._spawn()

    async def _spawn(self) -> str:
        """Spawn IMU agent with a PTY."""
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        master, slave = pty.openpty()

        # Build the agent command via wrapper
        cmd, cwd = build_imu_command(run_id)

        self._process = subprocess.Popen(
            cmd, cwd=cwd,
            stdin=slave, stdout=slave, stderr=slave,
            preexec_fn=os.setsid,
        )
        os.close(slave)
        self._pty_master = master
        self._run_id = run_id

        # Start background reader task
        asyncio.create_task(self._read_loop())
        return run_id

    async def send(self, message: str) -> None:
        """Write user message to PTY stdin."""
        os.write(self._pty_master, (message + "\n").encode())

    async def _read_loop(self) -> None:
        """Read PTY stdout and broadcast to connected WebSockets."""
        loop = asyncio.get_event_loop()
        while self._process and self._process.poll() is None:
            data = await loop.run_in_executor(
                None, os.read, self._pty_master, 4096
            )
            if not data:
                break
            text = data.decode(errors="replace")
            for ws in list(self._websockets):
                await ws.send_text(text)

    async def stop(self) -> None:
        """Gracefully stop the IMU agent."""
        if self._process:
            self._process.terminate()
            self._process.wait(timeout=10)
```

The `IMUManager` is instantiated once at app startup and shared across
requests (same pattern as the scheduler).

#### Backend: WebSocket Endpoint

```python
@router.websocket("/api/imu/ws")
async def imu_websocket(ws: WebSocket, manager: IMUManager = Depends()):
    await ws.accept()
    await manager.ensure_running()
    manager._websockets.add(ws)
    try:
        while True:
            message = await ws.receive_text()
            await manager.send(message)
    except WebSocketDisconnect:
        manager._websockets.discard(ws)
```

Multiple browser tabs can connect to the same IMU session. All see
the same conversation stream.

#### Backend: REST Endpoints

For non-WebSocket operations (session history, status):

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/imu/status` | GET | IMU agent status (running/stopped, run_id, uptime) |
| `POST /api/imu/start` | POST | Start IMU agent (no-op if already running) |
| `POST /api/imu/stop` | POST | Stop IMU agent |
| `GET /api/imu/sessions` | GET | List past IMU sessions |
| `GET /api/imu/sessions/{run_id}` | GET | IMU session detail |

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

**Panel behavior:**

- **Toggle**: Click the `[IMU]` nav button to slide the panel open
  or closed. Panel width: 400px (resizable).
- **Persist**: Panel state (open/closed) persists across page
  navigations and page refreshes (localStorage).
- **Auto-start**: Opening the panel auto-starts the IMU agent if not
  running. A brief "Starting IMU..." spinner shows during boot.
- **Reconnect**: If the WebSocket disconnects, auto-reconnect with
  exponential backoff. Show a subtle "Reconnecting..." indicator.
- **History**: On panel open, fetch recent messages from the current
  session's log for scroll-back context.

**Message rendering:**

- User messages: right-aligned bubbles (standard chat UI).
- Agent output: left-aligned, rendered as Markdown (code blocks,
  lists, links). Agent tool invocations (shell commands) shown in
  distinct styled blocks.
- Status indicators: typing/thinking indicator while agent is
  processing, timestamp on each message.
- Terminal output: raw terminal output from the agent rendered in a
  monospace font block with ANSI color support.

**Quick actions (optional, future):**

Contextual shortcuts above the input box based on the current GUI
page:

- On project detail: "Launch session on {project}"
- On schedules page: "Create new schedule"
- On session detail: "What happened in this session?"

These pre-fill the input box with a suggested message.

#### Terminal Output Handling

The PTY produces raw terminal output including ANSI escape codes.
The frontend needs to handle this:

1. **ANSI parsing**: Use a library like `xterm.js` or `anser` to
   convert ANSI escape codes to styled HTML.
2. **Message boundaries**: Agent output is a continuous stream, not
   discrete messages. The frontend accumulates output until the agent
   returns to its input prompt, then treats the accumulated text as
   one "message."
3. **Prompt detection**: Detect the agent's input prompt pattern
   (e.g., `> ` for Claude Code) to know when the agent is waiting
   for input. This signals the frontend to show the input box as
   active and stop the typing indicator.

Alternatively, if the agent wrapper supports structured JSON output
mode, the frontend can parse discrete message objects instead of raw
terminal output. This is a per-wrapper optimization — PTY mode is the
universal fallback.

### IMU Session Discovery

The GUI session sync also scans `~/.strawpot/imu/sessions/` for IMU
session history. These appear in the GUI under a special "IMU" virtual
project (auto-registered, not tied to a user project).

In `db.py`, ensure a virtual project row exists:

```sql
INSERT OR IGNORE INTO projects (id, name, directory, created_at)
VALUES (0, 'IMU', '~/.strawpot', datetime('now'));
```

IMU sessions reference `project_id = 0`.

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

Add the PTY-bridged WebSocket backend for GUI-embedded chat.

3. **`IMUManager` class** in `gui/src/strawpot_gui/imu.py` — PTY
   process management, WebSocket broadcast, lifecycle control.
4. **WebSocket endpoint** `/api/imu/ws` — bidirectional message
   relay between frontend and IMU agent process.
5. **REST endpoints** — `/api/imu/status`, `/api/imu/start`,
   `/api/imu/stop` for lifecycle control.
6. **App integration** — instantiate `IMUManager` at startup,
   graceful shutdown on exit.

### Phase 3: GUI Chat Frontend

Build the chat panel in the React frontend.

7. **IMU nav button** — persistent `[IMU]` button in the global
   navigation bar.
8. **Slide-over chat panel** — resizable side panel with WebSocket
   connection, auto-start on open, persist open/closed state.
9. **Message rendering** — Markdown rendering for agent output,
   ANSI color support for terminal output, user message bubbles.
10. **Connection management** — auto-reconnect with exponential
    backoff, typing/thinking indicator, "Starting IMU..." spinner.

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

2. **Terminal output vs structured messages.** The PTY bridge produces
   raw terminal output. Should we invest in a structured message
   protocol (JSON events for "thinking", "tool_use", "response") for
   richer rendering, or keep the universal PTY approach? PTY-first
   for MVP; structured mode as a per-wrapper optimization later.

3. **Chat panel vs dedicated page.** The slide-over panel keeps IMU
   accessible alongside other pages but has limited width. Should
   there also be a full-page IMU view for longer conversations?
   Start with the panel; add a "pop out" button if users want more
   space.

4. **Session continuity across GUI restarts.** When the GUI server
   restarts, the IMU agent process dies (child process). Should the
   agent persist independently (daemonized) or restart on next
   interaction? Restart is simpler; memory provider handles context
   continuity.
