# StrawPot Web GUI — Design

Local web dashboard for managing strawpot projects, monitoring agent
sessions, and reviewing history. Distributed as a separate Python package
(`strawpot-gui`) and launched via `strawpot gui`.

## Goals

1. Register and manage multiple projects (each a working directory with `strawpot.toml`).
2. Launch, monitor, and review sessions per project.
3. Browse and install roles, skills, agents, and memory providers.
4. Edit project and global configuration through the UI.
5. Provide real-time agent delegation tree and log streaming.
6. Extensible trigger system for external event sources (Slack, GitHub, etc.).

## Tech Stack

| Layer | Choice |
|-------|--------|
| Backend | FastAPI (Python) |
| Frontend | React + Vite (TypeScript) |
| Real-time | Server-Sent Events (SSE) |
| Tree visualization | React Flow |
| GUI state | SQLite (`~/.strawpot/gui.db`) |

## Deployment

Single Python package. No separate Node runtime at deploy time.

```
strawpot gui [--port PORT]
  → starts FastAPI on 127.0.0.1:PORT (default 8741)
  → serves React SPA from bundled static files
  → opens http://localhost:PORT in default browser
  → Ctrl+C stops the server
```

- Frontend is built to static files at package time (`npm run build`
  during `strawpot-gui` release). The built assets are included in the
  Python package and served via FastAPI `StaticFiles`.
- Binds to `127.0.0.1` only. Local-only access — no authentication
  required.
- Single process, single command. Vite dev server is used only during
  frontend development (CORS enabled in FastAPI dev mode for
  cross-origin requests from the Vite port).
- **Single instance only.** On startup, check whether the port is
  already in use. If so, open the browser to the existing instance
  instead of starting a second server. Avoids SQLite write contention
  and SSE duplication.
- If a native desktop window is desired later, the same React frontend
  can be wrapped in Tauri (~5 MB) without rewriting.
- Health check: `GET /api/health` returns `{"status": "ok"}`.
  Used by the single-instance check and external monitoring.

## Architecture

```
Browser (React SPA)
  │
  ▼
FastAPI server                              ← strawpot-gui package
  │
  ├─ /api/projects/*                        CRUD projects (gui.db + dirs)
  ├─ /api/projects/:id/config               read/write strawpot.toml
  ├─ /api/sessions/*                        list / detail / launch / stop
  ├─ /api/sessions/:id/tree                 SSE  real-time agent tree
  ├─ /api/sessions/:id/logs/:agent_id       SSE  agent log stream
  ├─ /api/sessions/:id/trace                SSE  trace event stream
  ├─ /api/sessions/:id/artifacts/:hash      read artifact content
  ├─ /api/sessions/:id/changed-files        changed file list (worktree)
  ├─ /api/registry/*                        browse installed items
  ├─ /api/registry/install                  install via strawpot CLI
  ├─ /api/registry/search                   search StrawHub
  ├─ /api/config/global                     read/write global config
  ├─ /api/health                            health check
  ├─ /api/triggers/*                        CRUD + start/stop triggers
  └─ /api/triggers/:id/logs                 SSE  trigger adapter logs

Data sources
  ├─ ~/.strawpot/gui.db                     projects, session history, triggers
  ├─ ~/.strawpot/strawpot.toml              global config
  ├─ <project>/strawpot.toml                project config
  ├─ <project>/.strawpot/sessions/*/        live + archived session data
  ├─ <project>/.strawpot/files/             project files (uploaded via GUI)
  ├─ <project>/.strawpot/{roles,skills,agents,memory}/
  └─ DenDen gRPC Status()                   live agent count + uptime
```

Read-only observer by default. Actions (launch sessions, install packages)
are executed through the strawpot CLI subprocess, never by writing to
runtime state directly.

---

## Data Sources

### session.json

Location: `.strawpot/sessions/<run_id>/session.json`

```json
{
  "run_id": "a1b2c3d4e5f6",
  "working_dir": "/path/to/project",
  "isolation": "none | worktree",
  "runtime": "strawpot-claude-code",
  "denden_addr": "127.0.0.1:9700",
  "started_at": "2026-01-01T12:00:00+00:00",
  "pid": 12345,
  "base_branch": "main",
  "worktree": "/path/to/worktree",
  "worktree_branch": "strawpot/a1b2c3d4e5f6",
  "agents": {
    "agent_abc123": {
      "role": "orchestrator",
      "runtime": "strawpot-claude-code",
      "parent": null,
      "started_at": "2026-01-01T12:00:01+00:00",
      "pid": 12346
    }
  }
}
```

### trace.jsonl

Location: `.strawpot/sessions/<run_id>/trace.jsonl` (append-only)

Each line is a `TraceEvent`:

```json
{
  "ts": "2026-01-01T12:00:00.000000+00:00",
  "event": "<event_name>",
  "trace_id": "a1b2c3d4e5f6",
  "span_id": "x1y2z3a4b5c6",
  "parent_span": null,
  "data": {}
}
```

Event types and their `data` fields:

| Event | Data fields |
|-------|-------------|
| `session_start` | `run_id`, `role`, `runtime`, `isolation` |
| `session_end` | `merge_strategy`, `duration_ms` |
| `delegate_start` | `role`, `context_ref`, `parent_span` |
| `delegate_end` | `exit_code`, `summary`, `duration_ms` |
| `delegate_denied` | `role`, `reason`, `parent_span` |
| `agent_spawn` | `agent_id`, `runtime`, `pid` |
| `agent_end` | `exit_code`, `output_ref`, `duration_ms` |
| `memory_get` | `provider`, `cards_ref`, `card_count` |
| `memory_dump` | `provider`, `entries_ref`, `entry_count` |

Fields ending in `_ref` are SHA256[:12] content-addressed artifact hashes.
Artifacts are stored in `.strawpot/sessions/<run_id>/artifacts/<hash>`.

### Agent logs

Location: `.strawpot/sessions/<run_id>/agents/<agent_id>/`

- `.pid` — process ID (text)
- `.log` — stdout + stderr combined (plain text)

### DenDen gRPC Status

`Status()` RPC returns `uptime_seconds` and `active_agents`.

### Configuration

Global: `~/.strawpot/strawpot.toml`
Project: `<project>/strawpot.toml` (overrides global)

`StrawPotConfig` fields:

| Field | Type | Default |
|-------|------|---------|
| `runtime` | str | `"strawpot-claude-code"` |
| `isolation` | str | `"none"` |
| `denden_addr` | str | `"127.0.0.1:9700"` |
| `orchestrator_role` | str | `"orchestrator"` |
| `max_depth` | int | `3` |
| `permission_mode` | str | `"default"` |
| `agent_timeout` | int \| None | `None` |
| `max_delegate_retries` | int | `0` |
| `agents` | dict | `{}` |
| `skills` | dict | `{}` |
| `roles` | dict | `{}` |
| `memory` | str \| None | `None` |
| `memory_config` | dict | `{}` |
| `merge_strategy` | str | `"auto"` |
| `pull_before_session` | str | `"prompt"` |
| `pr_command` | str | `"gh pr create ..."` |
| `trace` | bool | `true` |

---

## Features

### 1. Dashboard

Home page showing everything at a glance.

- Active projects with running session counts
- Running sessions across all projects
- Active triggers with status indicators
- Recent completed sessions (last N)

### 2. Project Management

**Project list** — all registered projects with directory path, runtime,
isolation mode.

**Project detail page:**

| Tab | Contents |
|-----|----------|
| Sessions | Active + archived sessions for this project |
| Config | Form-based editor for project `strawpot.toml` |
| Files | Drag-and-drop upload, file list with delete |
| Registry | Installed roles / skills / agents / memories scoped to this project |
| Triggers | Triggers bound to this project |

**Project registration** — point at a working directory. The GUI reads
the existing `strawpot.toml` or creates one with defaults.

**Stale project detection** — on project list load, check whether each
registered directory still exists. If the directory is missing, show a
warning badge on the project card. Do not auto-delete — the directory
may be on an unmounted volume or temporarily moved.

**Launch session** — pick a role (from installed roles), provide an
optional task description, optionally override config fields, then
start via `strawpot start` subprocess. The `POST /api/sessions`
endpoint returns immediately with a session ID and `status: "starting"`.
The frontend subscribes to the session's SSE tree endpoint, which emits
a `session_start` event once `session.json` appears. If the subprocess
exits before producing `session.json`, the endpoint emits an error
event with stderr output.

Sessions launched from the GUI run in **autonomous mode**
(`permission_mode: auto`). The agent works without calling `ask_user`
and the GUI provides a fire-and-observe experience: watch the agent
tree, stream logs, and review results on completion.

**TODO:** Interactive mode — add a chat panel to the session detail
page where `ask_user` prompts appear and the user can respond inline.
This reuses the same `ask_user` bridge built for trigger ongoing
sessions (Phase 8+) and is deferred until that infrastructure exists.

### 3. Session Monitoring

**Session detail page:**

- **Result** — prominent section at the top showing summary, exit code, and duration once the session completes. Quick link to the full output artifact.
- **Agent Tree** — real-time delegation tree (see [Real-Time Agent Tree](#real-time-agent-tree))
- **Log Viewer** — streaming `.log` per agent with search/filter. Initial load is capped (last 1000 lines) with a "load more" button for earlier content. Live tail via SSE appends new lines.
- **Trace Timeline** — span tree from `trace.jsonl` with durations
- **Artifact Inspector** — click any `*_ref` in the trace to view content
- **Changed Files** — list of files added, modified, or deleted during the session (from `git diff --name-status` for worktree isolation). Shows file paths and change type only, not content diffs. Deferred to a later phase.
- **Status** — PID liveness, DenDen gRPC status
- **Stop Session** — kill the orchestrator process (SIGTERM to session PID) with confirmation dialog

### 4. Notifications

Browser notifications (via the Notifications API) for session lifecycle
events. No external dependencies.

- Session completed (success) — green notification with summary
- Session failed (non-zero exit) — red notification with error info
- Delegation denied — warning notification

Triggered by SSE events the frontend is already consuming from the
trace stream. Opt-in via browser permission prompt on first use.

### 5. Session History

Sessions are preserved after completion (see [Session Archival](#session-archival))
so the GUI can browse past sessions with full trace and log data.

- Filter by project, date range, role, exit code
- Session list shows: run_id, role, runtime, started_at, duration, exit code, summary
- Click through to full session detail (same view as live sessions, read-only)

### 6. Config Management

**Project config** — form-based editor on the project detail page.
Writes to `<project>/strawpot.toml`.

**Global config** — separate settings page. Writes to
`~/.strawpot/strawpot.toml`.

Both editors show the merged effective config (global + project) with
indicators showing which values come from which source.

### 7. Registry Browser

Unified view across global and per-project installed items.

| Tab | Project path | Global path |
|-----|-------------|-------------|
| Roles | `.strawpot/roles/` | `~/.strawpot/roles/` |
| Skills | `.strawpot/skills/` | `~/.strawpot/skills/` |
| Agents | `.strawpot/agents/` | `~/.strawpot/agents/` |
| Memories | `.strawpot/memory/` | `~/.strawpot/memory/` |

Each item displays: name, version, description (from frontmatter),
install scope (project or global).

**Install from StrawHub** — search field queries the StrawHub registry.
Install triggers `strawpot install <slug>` subprocess with a scope flag.

### 8. Project Files

Drag-and-drop file upload so users can provide reference documents,
specs, data files, or other context that agents can access during
sessions.

**Storage**: `<project>/.strawpot/files/`. Flat or nested — uploaded
directory structure is preserved. Path components are validated on
upload: reject names containing `..`, absolute paths, or symlinks to
prevent writing outside the files directory.

**Agent access**: The delegation handler appends the file listing and
absolute path to the agent's system prompt so agents know where to
find uploaded files. For worktree sessions the path points back to the
original project's `.strawpot/files/` (not the worktree copy).

**Frontend**: Drag-and-drop zone on the project detail page (new Files
tab). Shows uploaded files with name, size, and upload date. Supports
delete.

### 9. Trigger Management (Lower Priority)

Triggers are external event sources that automatically create or feed
sessions. The trigger system is designed as a plugin architecture for
extensibility, but implementation is deferred. The features above
(projects, sessions, config, registry) are designed so they do not
block or conflict with adding triggers later.

See [Trigger Architecture](#trigger-architecture) for the full design.

---

## Real-Time Agent Tree

### Data flow

```
session.json (file watch)  ─┐
                             ├──▶  SSE: /api/sessions/:id/tree
trace.jsonl  (tail-follow)  ─┘
```

The backend watches `session.json` for agent additions and tail-follows
`trace.jsonl` for lifecycle events. On any change it pushes an SSE event
with the full tree state.

### SSE reconnection

All SSE endpoints follow the same reconnection protocol:

1. Each SSE event includes an `id` field (monotonic counter per stream).
2. On reconnect, the browser's `EventSource` sends `Last-Event-ID`.
3. The server replays events after that ID. For `trace.jsonl` this is
   a line offset; for agent tree it resends the full current state;
   for logs it resends from the byte offset.
4. If `Last-Event-ID` is missing (first connect), the server sends the
   full current state followed by live updates.

### SSE payload

```json
{
  "nodes": [
    {
      "agent_id": "agent_abc123",
      "role": "orchestrator",
      "runtime": "strawpot-claude-code",
      "status": "running",
      "exit_code": null,
      "started_at": "2026-01-01T12:00:01+00:00",
      "duration_ms": null,
      "parent": null
    },
    {
      "agent_id": "agent_def456",
      "role": "implementer",
      "runtime": "strawpot-claude-code",
      "status": "completed",
      "exit_code": 0,
      "started_at": "2026-01-01T12:00:10+00:00",
      "duration_ms": 30000,
      "parent": "agent_abc123"
    }
  ],
  "pending_delegations": [
    {
      "role": "reviewer",
      "requested_by": "agent_abc123",
      "span_id": "span_xyz"
    }
  ],
  "denied_delegations": [
    {
      "role": "admin",
      "reason": "DENY_ROLE_NOT_ALLOWED",
      "span_id": "span_uvw"
    }
  ]
}
```

### Frontend rendering

React Flow tree where each node shows role name, status badge
(green/yellow/red), and elapsed time. Nodes appear with animation
when agents spawn. Pending delegations render as dashed outline nodes.
Denied delegations flash briefly and show reason on hover.

```
orchestrator (running, 45s)
├── implementer (completed, 30s, exit 0)
│   └── reviewer (running, 12s)
└── implementer-2 (running, 8s)
    └── [pending: fixer]
```

---

## Session Archival

**CLI change**: on session cleanup, move
`.strawpot/sessions/<run_id>/` to `.strawpot/sessions/archive/<run_id>/`
instead of deleting. This preserves `session.json`, `trace.jsonl`,
artifacts, and agent logs for the GUI to browse.

The GUI reads both `sessions/` (active) and `sessions/archive/` (history).
Session history is also indexed in `gui.db` for fast querying across
projects.

---

## GUI Database

SQLite at `~/.strawpot/gui.db`. Owned exclusively by the GUI server;
the CLI never reads or writes it.

### Schema

```sql
CREATE TABLE projects (
    id          INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    working_dir TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE sessions (
    run_id      TEXT PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    runtime     TEXT NOT NULL,
    isolation   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'starting',  -- starting | running | completed | failed | archived
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    duration_ms INTEGER,
    exit_code   INTEGER,
    session_dir TEXT NOT NULL, -- absolute path to session directory
    task        TEXT,          -- task description provided at launch
    summary     TEXT           -- from delegate_end trace event
);

CREATE INDEX idx_sessions_project ON sessions(project_id, started_at DESC);
CREATE INDEX idx_sessions_status  ON sessions(status);

CREATE TABLE trigger_instances (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    adapter     TEXT NOT NULL,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,               -- role to launch sessions with
    config      TEXT NOT NULL DEFAULT '{}',  -- JSON (adapter-specific settings)
    status      TEXT NOT NULL DEFAULT 'stopped',  -- running | stopped | error
    last_error  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

The projects table is the source of truth for which directories are
registered. Session rows are populated by scanning session directories
and kept as a queryable index — the session files remain the primary
data source.

**Session index sync:** On GUI startup, scan all registered project
session directories and upsert rows into the `sessions` table. For
each session directory, read `session.json` for core fields (`run_id`,
`role`, `runtime`, `isolation`, `started_at`, `session_dir`) and parse
`trace.jsonl` for completion fields (`exit_code`, `summary`,
`duration_ms`, `ended_at` from `session_end` / `delegate_end` events).
During runtime, session rows are created on launch and updated via SSE
events (status transitions, exit code, summary).

**TODO:** Detect CLI-launched sessions while the GUI is running. The
startup scan catches sessions created before the GUI starts, but
sessions launched via `strawpot start` from the CLI while the GUI is
open are not detected until the next restart. A filesystem watcher on
each project's `.strawpot/sessions/` directory would close this gap.

**Session status transitions:**

```
starting → running     (session.json appears / session_start trace)
running  → completed   (root delegate_end trace with exit_code 0)
running  → failed      (root delegate_end trace with exit_code ≠ 0, or process dies)
*        → archived    (CLI moves session dir to archive/)
```

---

## Trigger Architecture

> Lower priority. Designed here for completeness so the rest of the
> system does not make choices that block future trigger support.

### Concept

Triggers are adapter plugins that bridge external event sources to
strawpot sessions. Each adapter is a Python module with a standard
protocol, discovered and loaded dynamically — the same pattern used
by memory providers.

### Two session modes

| Mode | Examples | Behavior |
|------|----------|----------|
| **One-shot** | GitHub issue, email, cron | Event → new session → agent works → session ends → result posted back |
| **Ongoing** | Slack, Telegram | Persistent session receiving messages continuously via the adapter |

### Plugin structure

```
~/.strawpot/triggers/trigger-slack/
├── TRIGGER.md          ← manifest (YAML frontmatter + docs)
└── adapter.py          ← implements TriggerAdapter protocol
```

Manifest example:

```yaml
---
name: trigger-slack
description: Creates sessions from Slack messages
version: 0.1.0
mode: ongoing
env_schema:
  SLACK_BOT_TOKEN:
    required: true
params:
  channel:
    type: string
---
```

### Adapter protocol

```python
class TriggerAdapter(Protocol):
    name: str
    mode: Literal["one_shot", "ongoing"]

    async def start(self, config: dict, callback: TriggerCallback) -> None:
        """Start listening. Call callback on each event."""
        ...

    async def stop(self) -> None:
        """Graceful shutdown."""
        ...

    async def send(self, session_id: str, message: str) -> None:
        """Send response back to source (ongoing mode only)."""
        ...

@dataclass
class TriggerEvent:
    source_id: str          # e.g. Slack channel+thread ID
    sender: str
    text: str
    metadata: dict          # source-specific (issue URL, email headers)

TriggerCallback = Callable[[TriggerEvent], Awaitable[None]]
```

### Trigger manager

Runs inside the GUI's async event loop (FastAPI is already async).
Manages adapter lifecycle: start, stop, configure, restart on error.

```
External Source          Trigger Adapter              StrawPot
─────────────────        ───────────────              ────────
Slack message    ──→    trigger-slack    ──→    session (ongoing)
GitHub issue     ──→    trigger-github   ──→    strawpot start (one-shot)
Email            ──→    trigger-email    ──→    strawpot start (one-shot)
Cron schedule    ──→    trigger-cron     ──→    strawpot start (one-shot)
```

### Ongoing sessions via ask_user

For ongoing triggers (Slack, Telegram), the adapter reuses the existing
DenDen `ask_user` RPC. No protocol changes are needed.

**How it works:**

1. The orchestrator agent's role prompt instructs it to call `ask_user`
   in a conversational loop.
2. The `Session.on_ask_user` handler checks whether this is a
   trigger-bound session.
3. If yes, it pulls the next message from the trigger adapter's queue
   (blocking until a message arrives) instead of prompting a terminal.
4. The agent's response is routed back through the trigger adapter
   to the external source.

```python
class TriggerSessionBridge:
    """Bridges a trigger adapter to a session's ask_user handler."""

    def __init__(self, adapter: TriggerAdapter, source_id: str):
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._adapter = adapter
        self._source_id = source_id

    async def on_ask_user(self, prompt: str) -> str:
        """Called by Session when agent calls ask_user."""
        return await self._queue.get()

    async def on_incoming(self, event: TriggerEvent) -> None:
        """Called by trigger adapter when external message arrives."""
        await self._queue.put(event.text)

    async def send_response(self, text: str) -> None:
        """Send agent output back to external source."""
        await self._adapter.send(self._source_id, text)
```

The agent does not know whether it is talking to a terminal or a Slack
channel. The session layer handles routing.

### Configuration

**Source of truth:** `gui.db` owns trigger instance state (running,
stopped, last error). `strawpot.toml` is used only as an optional
seed — on first GUI startup, any `[[triggers]]` entries in the config
are imported into `gui.db`. After that, the GUI API is the sole
interface for creating and managing triggers. The TOML entries are
not kept in sync.

Triggers are configured in `strawpot.toml` (seed only):

```toml
[[triggers]]
name = "slack-support"
adapter = "trigger-slack"
project = "/path/to/project"
role = "support-agent"
mode = "ongoing"
config = { channel = "#support", bot_token_env = "SLACK_BOT_TOKEN" }

[[triggers]]
name = "github-issues"
adapter = "trigger-github"
project = "/path/to/project"
role = "issue-resolver"
mode = "one-shot"
config = { repo = "org/repo", labels = ["strawpot"], poll_interval = "5m" }
```

---

## API Endpoints

### Projects

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/projects` | List registered projects |
| POST | `/api/projects` | Register a project (working_dir, display_name) |
| GET | `/api/projects/:id` | Project detail |
| PATCH | `/api/projects/:id` | Update project metadata (display_name) |
| DELETE | `/api/projects/:id` | Unregister project |
| GET | `/api/projects/:id/config` | Read merged project config |
| PUT | `/api/projects/:id/config` | Write project `strawpot.toml` |
| GET | `/api/projects/:id/files` | List uploaded files (name, size, modified) |
| POST | `/api/projects/:id/files` | Upload files (multipart, preserves directory structure) |
| DELETE | `/api/projects/:id/files/:path` | Delete an uploaded file |

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sessions` | List sessions (filter by project, status, date). Paginated: `?page=1&per_page=20`. |
| POST | `/api/sessions` | Launch new session (project_id, role, task, overrides) |
| GET | `/api/sessions/:id` | Session detail (session.json snapshot) |
| GET | `/api/sessions/:id/tree` | SSE: real-time agent tree |
| GET | `/api/sessions/:id/logs/:agent_id` | SSE: agent log stream |
| GET | `/api/sessions/:id/trace` | SSE: trace event stream |
| GET | `/api/sessions/:id/artifacts/:hash` | Read artifact content |
| GET | `/api/sessions/:id/changed-files` | List of changed files with status (added/modified/deleted). Worktree sessions only; returns empty list for non-worktree sessions. |
| POST | `/api/sessions/:id/stop` | Stop session (SIGTERM to orchestrator PID) |

### Registry

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/registry/:type` | List installed items (type = roles/skills/agents/memories). Optional `?project_id=X` returns project + global items with scope indicator; without it returns global only. |
| GET | `/api/registry/:type/:slug` | Item detail (frontmatter + body) |
| POST | `/api/registry/install` | Install from StrawHub (slug, scope: project or global) |
| GET | `/api/registry/search` | Search StrawHub (query string) |

### Config

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config/global` | Read global config |
| PUT | `/api/config/global` | Write global `strawpot.toml` |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Returns `{"status": "ok"}` |

### Triggers (future)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/triggers` | List trigger instances |
| POST | `/api/triggers` | Create trigger |
| PUT | `/api/triggers/:id` | Update trigger config |
| DELETE | `/api/triggers/:id` | Remove trigger |
| POST | `/api/triggers/:id/start` | Start adapter |
| POST | `/api/triggers/:id/stop` | Stop adapter |
| GET | `/api/triggers/:id/logs` | SSE: adapter logs |

---

## Implementation Phases

| Phase | Scope | Depends on |
|-------|-------|------------|
| **1** | Backend: project CRUD, global config API, SQLite setup | — |
| **2** | Backend: session list/detail/launch/stop, session archival CLI change | Phase 1 |
| **3** | Frontend: dashboard, project pages, session list | Phases 1–2 |
| **4** | Backend + frontend: real-time agent tree (SSE + React Flow) | Phase 2 |
| **5** | Backend + frontend: log viewer, trace timeline, artifact inspector | Phase 2 |
| **6** | Backend + frontend: registry browser + StrawHub install | Phase 1 |
| **7** | Backend + frontend: config editor (project + global) | Phase 1 |
| **7.5** | Backend + frontend: project files upload + agent prompt injection | Phase 1 |
| **8** | Trigger manager + adapter protocol + CRUD API | Phases 1–2 |
| **9** | Built-in trigger adapters (cron, GitHub) | Phase 8 |
| **10** | Ongoing session support (ask_user bridge) + Slack/Telegram adapters | Phases 8–9 |
| **11** | Interactive GUI sessions (chat panel reusing ask_user bridge) | Phase 10 |

**Deferred:**

- Session re-run — "Run again" button on archived sessions pre-filling
  launch dialog with the same role, task, and config overrides.
- Archive retention policy — configurable max age or count per project.
- Changed files view — file list from `git diff --name-status`.
