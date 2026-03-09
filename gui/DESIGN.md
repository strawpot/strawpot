# StrawPot Web GUI — Design

Local web dashboard for managing strawpot projects, monitoring agent
sessions, and reviewing history. Distributed as a separate Python package
(`strawpot-gui`) and launched via `strawpot gui`.

## Goals

1. Register and manage multiple projects (each a working directory with `strawpot.toml`).
2. Launch, monitor, and review sessions per project.
3. See what agents are doing *right now* — live output, not just metadata.
4. Browse and install roles, skills, agents, and memory providers.
5. Edit project and global configuration through the UI.
6. Provide real-time agent delegation tree and log streaming.
7. Extensible trigger system for external event sources (Slack, GitHub, etc.).
8. Feel like a product, not an ops dashboard — fast, responsive, polished.

---

## Design Philosophy & Wedges

StrawPot's GUI is not a generic admin panel or a chat interface. It has
a distinct identity built on six wedges — unique value propositions that
guide every design decision.

### 1. Local-first, zero-config

`strawpot gui` and you're in. No accounts, no cloud, no Docker, no
database migration. SQLite on disk, bound to 127.0.0.1, single process.
This removes an entire category of UX friction that plagues hosted
platforms. The tradeoff (no collaboration, no remote access) is
intentional — StrawPot is a developer's personal control plane.

### 2. Agent delegation tree

No other tool shows a live, interactive tree of how agents delegate to
each other. The delegation tree is our *primary* visualization — it
belongs front-and-center on the session detail page, not buried in a tab.
Pending delegations appear as dashed outlines, denied delegations flash
and show reasons, completed agents show exit codes and durations. The
tree updates in real time as new agents spawn and complete.

This visualization directly answers: "What is my swarm doing right now,
and how did it get there?"

### 3. Fire-and-observe

Sessions launched from the GUI run in autonomous mode
(`permission_mode: auto`). The user provides a task, picks a role, and
watches the agents work. The GUI is an observation deck, not a steering
wheel. This is fundamentally different from chat-based AI tools where
the user drives every turn.

Interactive mode (chat panel via `ask_user` bridge) is planned as a
future extension but is not the default experience.

### 4. Trace-based debugging

Every session produces a structured trace (`trace.jsonl`) with span
IDs, parent spans, and content-addressed artifact references. The GUI
renders this as a timeline where any `*_ref` field is clickable —
revealing the full context prompt, memory cards, task description, or
output that was exchanged. This is StrawPot's answer to "what went
wrong?" — not grepping through logs, but navigating a structured span
tree.

### 5. StrawHub ecosystem integration

The GUI is the primary interface for discovering and installing reusable
roles, skills, agents, and memory providers from StrawHub. Search the
public registry, one-click install scoped to a project or global, browse
what's installed. This turns the GUI into a package manager UI, not just
a monitoring dashboard.

### 6. Trigger-driven autonomy

External events (GitHub issues, Slack messages, cron schedules)
automatically spawn sessions through the trigger adapter system. The GUI
is the control plane for configuring, monitoring, and debugging triggers.
This makes StrawPot a persistent autonomous agent platform, not just a
one-shot task runner.

---

## Tech Stack

| Layer | Current | Planned |
|-------|---------|---------|
| Backend | FastAPI (Python) | — (no change) |
| Frontend | React 19 + Vite 6 (TypeScript) | — (no change) |
| Styling | Custom CSS (index.css) | Tailwind CSS 4 + shadcn/ui |
| Data fetching | Custom `useApi` hook | TanStack Query v5 |
| Icons | None | lucide-react |
| Toasts | None | sonner (via shadcn) |
| Command palette | None | cmdk (via shadcn) |
| Real-time | SSE (file polling, 1.5s interval) | SSE (watchfiles, ~100ms) |
| Tree visualization | React Flow (@xyflow/react) | — (no change) |
| GUI state | SQLite (`~/.strawpot/gui.db`) | — (no change) |
| Backend file watching | `asyncio.sleep` + `os.stat` mtime | `watchfiles` (OS-native) |

The frontend framework (React + Vite) and backend framework (FastAPI)
are not changing. The migration targets the component layer (shadcn
replaces custom CSS), the data layer (TanStack Query replaces manual
fetch hooks), and the real-time layer (OS file watchers replace polling).

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
  ├─ /api/sessions/:id/events               SSE  trace event stream
  ├─ /api/sessions/:id/artifacts/:hash      read artifact content
  ├─ /api/sessions/:id/changed-files        changed file list (worktree)
  ├─ /api/events                            SSE  global event bus (new)
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

- **Live agent activity feed** — when agents are running, the dashboard
  leads with a grid of live activity cards showing what each agent is
  doing right now. Each card displays the agent's role, runtime badge,
  elapsed time, and the last few lines of output with a pulsing activity
  indicator. Clicking a card navigates to the session detail. When no
  agents are running, the feed collapses and the dashboard shows the
  standard overview.
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

**Launch session dialog** — a modal dialog (not inline form) with:
- Auto-focusing task textarea
- Role selector from installed roles
- Collapsible advanced options (runtime, isolation, merge strategy)
- Loading state during launch, success/error toasts on completion
- Navigation to the new session on success

**Interactive mode (deferred)** — add a chat panel to the session detail
page where `ask_user` prompts appear and the user can respond inline.
This reuses the same `ask_user` bridge built for trigger ongoing
sessions and is deferred until that infrastructure exists.

### 3. Session Monitoring

**Session detail page** — organized into tabs to avoid the wall-of-
sections problem. The session header (status badge, role, runtime,
duration, stop button) is always visible above the tabs.

| Tab | Contents |
|-----|----------|
| **Overview** | Task description, summary (on completion), detail grid (status, role, runtime, isolation, started/ended, exit code) |
| **Agent Tree** | Real-time delegation tree (see [Real-Time Agent Tree](#real-time-agent-tree)) — the primary tab for active sessions |
| **Logs** | Agent selector + terminal-style log viewer (see [Agent Log Streaming](#agent-log-streaming)) |
| **Trace Events** | Span timeline from `trace.jsonl` with durations and clickable artifact refs |
| **Artifacts** | Expandable list of all content-addressed artifacts from the session |

**Result section** — once the session completes, a prominent banner at
the top of the Overview tab showing summary, exit code, and duration.
Quick link to the full output artifact.

**Stop session** — kill the orchestrator process (SIGTERM to session PID)
with confirmation dialog.

**Auto-tab selection** — when navigating to an active session, default
to the Agent Tree tab. When navigating to a completed session, default
to the Overview tab.

### 4. Live Agent Activity Feed

The live agent activity feed is the centerpiece of the running-session
experience. It answers the "20 terminals open" problem: one unified view
of what every running agent is doing, across all active sessions.

**Dashboard integration:** When any session is active, the dashboard
leads with a responsive grid of activity cards (1–4 columns depending
on viewport width).

**Activity card anatomy:**

```
┌──────────────────────────────────────────┐
│ ● implementer         strawpot-claude    │
│   Session: run_a1b2c3  ·  2m 14s        │
│                                          │
│ > Reading src/auth/login.ts...           │
│ > Editing src/auth/login.ts              │
│ > Running npm test                       │
│                                          │
│                          ▸ View Session  │
└──────────────────────────────────────────┘
```

- **Pulsing dot** — green when receiving new output, dims after 5s idle
- **Role + runtime** — identifies the agent
- **Session link** — run_id prefix + elapsed time
- **Output preview** — last 3–5 lines of the agent's `.log` file,
  rendered in monospace. Auto-scrolls as new output arrives.
- **Click-through** — card links to the session detail page (Logs tab)

**Data flow:**

1. The global SSE connection (see [Real-Time Engine](#real-time-engine))
   notifies the frontend when agents spawn or complete.
2. For each active agent, the frontend opens a per-agent log SSE
   connection (see [Agent Log Streaming](#agent-log-streaming)) to
   receive output lines.
3. Activity cards manage their own SSE connection lifecycle — opening
   when the card mounts, closing on unmount or agent completion.

**Limits:** Maximum 8 activity cards visible simultaneously. If more
agents are running, show a "+N more" indicator with a link to the
sessions list.

### 5. Notifications

In-app toast notifications for session lifecycle events. No browser
Notifications API dependency — toasts appear within the React app using
the `sonner` library.

**Events and toast styles:**

| Event | Style | Content |
|-------|-------|---------|
| Session completed (exit 0) | Success (green) | "Session {id} completed" + summary preview |
| Session failed (exit ≠ 0) | Error (red) | "Session {id} failed" + exit code |
| Delegation denied | Warning (amber) | "Delegation denied: {role}" + reason |
| Session launched | Info (blue) | "Session {id} started" |

**Rate limiting:** Maximum 3 toasts per 10-second window per event
type. After reconnection, suppress toasts for 2 seconds to avoid a
flood of stale notifications.

**Toast actions:** Each toast includes a clickable link to the relevant
session detail page.

**Data source:** Toasts are fired from the global SSE event hook. The
global SSE connection already receives session lifecycle events — the
toast system consumes these without additional API calls.

### 6. Session History

Sessions are preserved after completion (see [Session Archival](#session-archival))
so the GUI can browse past sessions with full trace and log data.

- Filter by project, date range, role, exit code
- Session list shows: run_id, role, runtime, started_at, duration, exit code, summary
- Click through to full session detail (same view as live sessions, read-only)

### 7. Config Management

**Project config** — form-based editor on the project detail page.
Writes to `<project>/strawpot.toml`.

**Global config** — separate settings page. Writes to
`~/.strawpot/strawpot.toml`.

Both editors show the merged effective config (global + project) with
indicators showing which values come from which source.

### 8. Resource Browsers (Roles, Skills, Agents, Memory)

Four dedicated browser pages — one for each resource type — accessible
from the sidebar. Each browser provides a unified view across global
and per-project installed items.

| Resource | Project path | Global path |
|----------|-------------|-------------|
| Roles | `.strawpot/roles/` | `~/.strawpot/roles/` |
| Skills | `.strawpot/skills/` | `~/.strawpot/skills/` |
| Agents | `.strawpot/agents/` | `~/.strawpot/agents/` |
| Memory | `.strawpot/memory/` | `~/.strawpot/memory/` |

Each item displays: name, version, description (from frontmatter),
install scope (project or global), and actions (install/uninstall).

**Browse**: List all installed items with scope indicator (project vs
global). Filter by name, tag, or scope.

**Install from StrawHub**: Search field queries the StrawHub registry.
Install triggers `strawpot install <slug>` subprocess with a scope
flag (`--project` or `--global`).

**Uninstall**: Remove button triggers `strawpot uninstall <slug>`
subprocess. Confirmation dialog before removal.

**View details**: Click an item to see its full definition (YAML/MD
frontmatter), usage instructions, and which projects reference it.

### 9. Project Files

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

### 10. Command Palette & Keyboard Shortcuts

**Command palette (Cmd+K / Ctrl+K)** — global search overlay for
navigating sessions, projects, agents, and triggering actions.

Groups:

| Group | Items |
|-------|-------|
| Navigation | Dashboard, Projects, each project by name, active sessions |
| Actions | Launch Session (opens dialog), Stop Session (if running) |
| Settings | Toggle Dark Mode |

Powered by `cmdk` via the shadcn `<Command>` component. Searches across
projects and sessions with fuzzy matching.

**Keyboard shortcuts:**

| Shortcut | Action |
|----------|--------|
| `Cmd+K` / `Ctrl+K` | Open command palette |
| `g d` | Go to Dashboard |
| `g p` | Go to Projects |
| `g s` | Go to Sessions |
| `n s` | New Session (opens launch dialog) |
| `?` | Show keyboard shortcuts help |

Shortcuts are suppressed when focus is inside an input, textarea, or
contenteditable element. A help dialog (triggered by `?`) lists all
available shortcuts.

### 11. Trigger Management (Deferred)

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

## Real-Time Engine

The current SSE implementation polls files at 1.5-second intervals using
`asyncio.sleep` + `os.stat().st_mtime`. This creates noticeable lag and
wastes CPU on idle sessions. The new real-time engine replaces polling
with OS-native file watchers and adds a global event bus for efficient
cache invalidation.

### File watching with watchfiles

Replace `asyncio.sleep(_POLL_INTERVAL)` loops in the SSE router with
`watchfiles.awatch()`, which uses FSEvents (macOS), inotify (Linux), or
ReadDirectoryChangesW (Windows) for near-instant change detection.

```python
from watchfiles import awatch

async def watch_session_files(session_dir: str, stop_event: asyncio.Event):
    """Yield changes as they occur (~100ms latency)."""
    async for changes in awatch(
        session_dir,
        stop_event=stop_event,
        step=100,  # 100ms debounce
    ):
        yield changes
```

Impact: Average latency drops from ~750ms (half the 1.5s polling
interval) to ~100ms. No frontend changes needed.

### Global SSE event bus

A new endpoint `GET /api/events` provides a single SSE connection that
broadcasts lightweight notification events across all active sessions.
The frontend uses these notifications to invalidate TanStack Query
caches, triggering targeted refetches instead of blind polling.

**Why a global connection?** StrawPot is local-only, single-user. A
single SSE stream is simpler than per-page connections and avoids the
browser's 6-connection-per-origin limit for EventSource.

**Event types:**

```json
{"type": "session_created", "run_id": "...", "project_id": 3}
{"type": "session_updated", "run_id": "...", "project_id": 3}
{"type": "session_ended",   "run_id": "...", "project_id": 3, "exit_code": 0, "summary": "..."}
{"type": "agent_spawned",   "run_id": "...", "agent_id": "...", "role": "implementer"}
{"type": "agent_ended",     "run_id": "...", "agent_id": "...", "exit_code": 0}
{"type": "tree_changed",    "run_id": "..."}
{"type": "trace_appended",  "run_id": "...", "count": 5}
{"type": "log_appended",    "run_id": "...", "agent_id": "..."}
```

**Backend architecture:** A central event multiplexer maintains one
`asyncio.Queue` per connected SSE client. Per-session file watchers
push lightweight events into the multiplexer, which fans them out to
all connected clients. The multiplexer is created on first client
connection and shut down when the last client disconnects.

```python
class EventBus:
    """Multiplexes session watcher events to SSE clients."""

    def __init__(self):
        self._clients: list[asyncio.Queue] = []
        self._watchers: dict[str, asyncio.Task] = {}

    async def subscribe(self) -> AsyncIterator[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._clients.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._clients.remove(queue)

    def publish(self, event: dict):
        for queue in self._clients:
            queue.put_nowait(event)
```

**Frontend integration:** A single `useGlobalSSE()` hook connects to
`/api/events` at the layout level (always active). On each event, it
calls `queryClient.invalidateQueries()` with the relevant query keys:

```typescript
case "session_ended":
  queryClient.invalidateQueries({ queryKey: ["sessions"] });
  queryClient.invalidateQueries({ queryKey: ["sessions", event.project_id, event.run_id] });
  notifySessionComplete(event.run_id, event.summary);  // toast
  break;
case "session_created":
  queryClient.invalidateQueries({ queryKey: ["projects", event.project_id, "sessions"] });
  queryClient.invalidateQueries({ queryKey: ["sessions"] });
  break;
```

### Incremental trace SSE

The current trace events SSE endpoint sends the entire `all_events`
array on every update. For long sessions with hundreds of events, this
becomes increasingly wasteful.

**New protocol:**

- **First message (snapshot):** `{"type": "snapshot", "events": [...]}`
  — full event list on initial connection
- **Subsequent messages (append):** `{"type": "append", "events": [...]}`
  — only new events since the last message

The frontend's `useTraceSSE` hook handles both:
- On `snapshot`: replace state with `data.events`
- On `append`: append `data.events` to existing state

### Per-session SSE connections

The global event bus handles cache invalidation for REST-fetched data.
Per-session SSE connections (`/sessions/:id/tree`, `/sessions/:id/events`)
remain for the SessionDetail page where continuous streaming is needed.
These also switch from polling to `watchfiles`.

---

## Agent Log Streaming

The ability to see what agents are doing *right now* — not just metadata
trace events, but actual CLI output — is the biggest gap in the current
GUI. This section designs the full stack from backend endpoint to
frontend viewer.

### Backend: SSE endpoint

```
GET /api/sessions/{run_id}/logs/{agent_id}
```

Streams the agent's `.log` file as SSE events.

**Protocol:**

1. **Initial load:** Read the log file, send the last 500 lines as the
   first event:
   ```json
   {"type": "snapshot", "lines": ["line1", "line2", ...], "offset": 45678}
   ```

2. **Live tail:** Watch the log file with `watchfiles.awatch()`. On
   change, read new bytes from the last offset and send as a delta:
   ```json
   {"type": "append", "lines": ["new line1", "new line2"], "offset": 46012}
   ```

3. **Completion:** When the agent's session reaches a terminal state,
   send a final event and close the stream:
   ```json
   {"type": "done"}
   ```

**Error handling:**
- If the log file does not exist yet (agent just spawned), send an
  empty snapshot and wait for the file to appear.
- If the session directory is missing, return 404.

**REST companion endpoint:**

```
GET /api/sessions/{run_id}/logs/{agent_id}/full
```

Returns the complete log file as `text/plain`. Used by the "Download"
button in the log viewer.

### Frontend: Agent log viewer

A terminal-style component for viewing streaming agent output.

**Visual design:**

```
┌─────────────────────────────────────────────────────────┐
│ Agent: [orchestrator ▾]          🔍 Search   ⬇ Download │
├─────────────────────────────────────────────────────────┤
│   1 │ Starting session...                               │
│   2 │ Resolving role: implementer                       │
│   3 │ Spawning agent: strawpot-claude-code              │
│   4 │ Agent implementer started (pid 12345)             │
│   5 │ Delegating: reviewer                              │
│   6 │ ...                                               │
│     │                                    ▼ Auto-scroll  │
└─────────────────────────────────────────────────────────┘
```

**Features:**

- **Agent selector** — dropdown listing all agents in the session (from
  `session.json` agents map). Switching agents reconnects the log SSE.
- **Dark terminal theme** — dark background, monospace font, light text.
  Distinct from the rest of the UI to signal "this is raw output."
- **Line numbers** — gutter showing line numbers.
- **Auto-scroll** — follows the tail by default. When the user scrolls
  up, auto-scroll pauses and a "Jump to bottom" button appears. Resumes
  on click or when the user scrolls back to the bottom.
- **Search** — text filter bar (Ctrl+F within viewer). Highlights
  matching lines and shows match count.
- **Download** — downloads the full log via the REST endpoint.
- **Virtual scrolling** — for performance with large logs (thousands of
  lines), render only visible lines based on scroll position.

**Data flow:**

```
SSE: /api/sessions/{runId}/logs/{agentId}
  ↓
useAgentLogSSE hook
  ↓ lines[]
AgentLogViewer component
  ↓ renders visible lines
Virtual scroll viewport
```

The hook maintains a line buffer capped at 10,000 lines (oldest lines
evicted). The component renders only the visible window.

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

**CLI-launched session detection:** When using `watchfiles` for the
real-time engine, also watch each project's `.strawpot/sessions/`
directory for new subdirectories. When a new session directory appears,
index it in `gui.db` and push a `session_created` event through the
global event bus. This closes the gap where sessions launched via
`strawpot start` from the CLI while the GUI is open were not detected
until restart.

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
| GET | `/api/sessions/:id` | Session detail (session.json snapshot + agent list) |
| GET | `/api/sessions/:id/tree` | SSE: real-time agent tree |
| GET | `/api/sessions/:id/logs/:agent_id` | SSE: agent log stream (snapshot + live tail) |
| GET | `/api/sessions/:id/logs/:agent_id/full` | Full log file download (text/plain) |
| GET | `/api/sessions/:id/events` | SSE: trace event stream (snapshot + incremental) |
| GET | `/api/sessions/:id/artifacts/:hash` | Read artifact content |
| GET | `/api/sessions/:id/changed-files` | List of changed files with status (added/modified/deleted). Worktree sessions only; returns empty list for non-worktree sessions. |
| POST | `/api/sessions/:id/stop` | Stop session (SIGTERM to orchestrator PID) |

### Global Events

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/events` | SSE: global event bus (session lifecycle, agent spawn/end, change notifications) |

### Registry

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/registry/:type` | List installed items (type = roles/skills/agents/memories). Returns `[{ name, version, description, source, path }]`. |
| GET | `/api/registry/:type/:name` | Item detail (frontmatter + body) |
| GET | `/api/registry/:type/:name/config` | Env/params schema from manifest + saved values from `strawpot.toml`. Returns `{ env_schema, env_values, params_schema, params_values }`. For roles, synthesizes `default_agent` as a param. |
| PUT | `/api/registry/:type/:name/config` | Save env var and param values. Body: `{ env_values, params_values }`. Type-coerces params per schema. Roles save to `[roles.<name>]`. |
| POST | `/api/registry/install` | Install from StrawHub via `strawhub install -y <type> <name> --global`. Returns `{ exit_code, stdout, stderr }`. |
| DELETE | `/api/registry/:type/:name` | Uninstall via `strawhub uninstall <type> <name> --global`. Returns `{ exit_code, stdout, stderr }`. |

### Config

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config/global` | Read global config |
| PUT | `/api/config/global` | Write global `strawpot.toml` |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Returns `{"status": "ok"}` |

### Filesystem

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/fs/browse` | List directory contents (for project registration) |
| POST | `/api/fs/mkdir` | Create directory |

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

## Tech Stack Evolution

The frontend migration is organized into four phases. Each phase
delivers standalone value — the GUI is functional after every phase,
not just after the final one.

### Phase 1 — Foundation

**Goal:** Replace the custom CSS + manual fetch approach with a modern
component and data layer. Every subsequent feature benefits from this.

| Change | Why |
|--------|-----|
| Tailwind CSS 4 + `@tailwindcss/vite` | Utility-first styling, no more 753-line CSS file |
| shadcn/ui components | Consistent, accessible component library (button, card, dialog, table, tabs, badge, skeleton, etc.) |
| TanStack Query v5 | Automatic caching, background refetching, deduplication, loading/error states |
| lucide-react | Consistent icon set across the UI |
| `@/` path aliases | Clean imports (`@/components/...` instead of `../../../`) |

**Scope:**
- Initialize Tailwind + shadcn in the existing Vite project
- Install ~20 shadcn components (button, card, badge, table, dialog,
  input, select, textarea, label, separator, skeleton, tooltip,
  dropdown-menu, tabs, scroll-area, sheet, command, sonner, breadcrumb,
  accordion)
- Set up TanStack Query with centralized `queryKeys` and query hooks
- Redesign the layout: collapsible sidebar with icons, top header bar
  with breadcrumbs
- Migrate all 5 existing pages to shadcn components + query hooks
- Delete `index.css` custom styles and `useApi` hook

**New npm dependencies:**
```
tailwindcss @tailwindcss/vite @tanstack/react-query lucide-react
```
Plus shadcn transitive deps: `class-variance-authority`, `clsx`,
`tailwind-merge`, `@radix-ui/react-*`, `cmdk`, `sonner`.

### Phase 2 — Real-Time Engine

**Goal:** Make real-time updates feel instant and add agent log
streaming.

| Change | Why |
|--------|-----|
| `watchfiles` (backend) | OS-native file watching, ~100ms latency vs 1.5s polling |
| Global SSE endpoint `/api/events` | Single connection for all session lifecycle notifications |
| Agent log SSE endpoint | Stream agent `.log` files to the frontend |
| Incremental trace SSE | Stop sending full event arrays on every update |
| TanStack Query invalidation from SSE | Targeted cache busting instead of blind polling |

**New pip dependencies:**
```
watchfiles>=1.0
```

**Scope:**
- Replace `asyncio.sleep` polling loops with `watchfiles.awatch()` in
  the SSE router
- Implement the `EventBus` class and `/api/events` global SSE endpoint
- Implement `/api/sessions/:id/logs/:agent_id` SSE endpoint
- Implement `/api/sessions/:id/logs/:agent_id/full` REST endpoint
- Add `useGlobalSSE()` hook to the frontend layout
- Modify `useTraceSSE` for incremental snapshot+append protocol
- Add CLI-launched session detection via directory watching

### Phase 3 — Product UX

**Goal:** The features that make the GUI feel like a product rather
than an ops tool.

| Feature | Why |
|---------|-----|
| Live agent activity feed | "What are my agents doing?" answered at a glance |
| Agent log viewer | Terminal-style streaming output per agent |
| Toast notifications | Background awareness of session lifecycle events |
| Launch session dialog | Polished modal instead of inline form |
| Skeleton loaders | Perceived performance, no layout shift |

**Scope:**
- `ActiveAgentsPanel` + `AgentActivityCard` components on Dashboard
- `AgentLogViewer` component with dark theme, auto-scroll, search
- `useAgentLogSSE` hook connecting to the log SSE endpoint
- Session detail page reorganized into tabs (Overview / Agent Tree /
  Logs / Trace / Artifacts)
- Toast notification system via `sonner` + global SSE events
- Launch dialog component replacing inline form
- Page-specific skeleton components for loading states

### Phase 4 — Navigation & Polish

**Goal:** Power-user features and visual polish.

| Feature | Why |
|---------|-----|
| Command palette (Cmd+K) | Fast navigation without clicking through menus |
| Breadcrumb navigation | Orientation and easy back-navigation |
| Keyboard shortcuts | Power-user efficiency |
| Dark mode | Developer preference, reduce eye strain |

**Scope:**
- `CommandPalette` component using shadcn `<Command>` (cmdk)
- `Breadcrumbs` component derived from route + query cache
- `useKeyboardShortcuts` hook with key sequence detection
- `ThemeToggle` component with light/dark/system options
- CSS variables for dark theme (built into shadcn)
- Class-based dark mode variant for Tailwind v4

### Phase 5 — Config & Resource Management

**Goal:** Let users browse, install, and uninstall roles, skills,
agents, and memory providers — and edit project/global configuration
through the UI.

| Feature | Why |
|---------|-----|
| Role browser | Browse/install/uninstall roles per project or globally |
| Skill browser | Browse/install/uninstall skills per project or globally |
| Agent browser | Browse/install/uninstall agent definitions |
| Memory browser | Browse/install/uninstall memory providers |
| Config editor | Edit project and global `strawpot.toml` via forms |

**Backend API endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/resources/{type}` | GET | List installed resources (roles/skills/agents/memory) |
| `/api/v1/resources/{type}/{name}` | GET | Get resource detail (content, frontmatter) |
| `/api/v1/resources/{type}/{name}` | DELETE | Uninstall a resource |
| `/api/v1/resources/install` | POST | Install from StrawHub registry |
| `/api/v1/config/project/{id}` | GET/PUT | Read/write project config |
| `/api/v1/config/global` | GET/PUT | Read/write global config |

**Scope:**
- Backend: resource scanner reading `~/.strawpot/` directories, parsing
  frontmatter for metadata. Version read from `.version` file first,
  then frontmatter fallback
- Backend: install/uninstall endpoints wrapping `strawhub install -y`
  and `strawhub uninstall` subprocesses (stdin=DEVNULL for non-interactive)
- Backend: per-resource config endpoints (GET/PUT) combining manifest
  env/params schema with saved values from `strawpot.toml`. Roles expose
  `default_agent` as a configurable parameter; agents/memories expose
  `params` and `env`; skills expose `env` only
- Frontend: four resource browser pages (Roles, Skills, Agents, Memory)
  with list view, detail panel, install/uninstall actions
- Frontend: sidebar navigation with resource browser links + command palette
- Frontend: resource detail sheet with env var editing (masked inputs,
  required badges) and parameter editing (typed inputs per schema)
- Frontend: config editor page with form-based editing for project
  and global `strawpot.toml` (planned)

### Not Planned

| Feature | Reason |
|---------|--------|
| Multi-user / auth | StrawPot is local-first, single-user |
| PostgreSQL migration | SQLite is sufficient for local use |
| WebSocket (replacing SSE) | SSE is simpler and sufficient for our one-directional monitoring. Bidirectional communication (for interactive sessions) will use the existing DenDen gRPC bridge, not WebSocket. |
| Agent adapter config forms | Per-resource env/param editing now available in resource detail sheet |
| Kanban / task management | Not our domain; users have existing tools |
| Cost / token tracking | Requires agent-specific output parsing; deferred until wrapper protocol includes structured cost reporting |

---

## Implementation Status

| # | Scope | Status |
|---|-------|--------|
| 1 | Backend: project CRUD, global config API, SQLite setup | **Done** |
| 2 | Backend: session list/detail/launch/stop | **Done** |
| 3 | Frontend: dashboard, project pages, session list | **Done** |
| 4 | Backend + frontend: real-time agent tree (SSE + React Flow) | **Done** |
| 5 | Backend + frontend: trace timeline, artifact inspector | **Done** |
| 5.5 | Frontend: agent log viewer, launch dialog, skeleton loaders | **Done** (Phase 3) |
| 5.6 | Frontend: dashboard activity feed, live agent output | **Done** (Phase 3) |
| 5.7 | Frontend: command palette, keyboard shortcuts, dark mode | **Done** (Phase 4) |
| 6 | Backend + frontend: resource browsers (roles, skills, agents, memory) + StrawHub install/uninstall | **Done** (Phase 5) |
| 6.5 | Backend + frontend: per-resource env var and parameter configuration | **Done** (Phase 5) |
| 7 | Backend + frontend: config editor (project + global) | **Done** (Phase 5) |
| 7.5 | Backend + frontend: project files upload | **Done** (Phase 5) |
| 8 | Trigger manager + adapter protocol + CRUD API | Deferred |
| 9 | Built-in trigger adapters (cron, GitHub) | Deferred |
| 10 | Ongoing session support (ask_user bridge) | Deferred |
| 11 | Interactive GUI sessions (chat panel) | Deferred |

**Next:** Deferred features or Phase 6 — Triggers.

**Deferred features:**

- Session re-run — "Run again" button on archived sessions pre-filling
  launch dialog with the same role, task, and config overrides.
- Archive retention policy — configurable max age or count per project.
- Changed files view — file list from `git diff --name-status`.
- Chat-style trace view — render session trace events as a chat dialogue
  instead of a table. Delegation requests appear as outgoing messages,
  delegation returns as incoming messages with summary and clickable
  artifact refs. Memory events, agent spawns, and lifecycle events
  render as system messages between chat bubbles.
- Session attachments — allow attaching files directly to a task prompt
  when launching a session. Unlike project-level files which persist
  across sessions, session attachments are one-off context files stored
  in the session directory and referenced in the agent's system prompt.
- Activity charts — visual charts for run patterns over time (runs per
  day, success rate, duration distribution).
- Cost / token tracking — per-agent and per-project token usage and cost
  breakdowns.
