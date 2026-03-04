# StrawPot Web GUI — Design

Local web dashboard for managing strawpot projects, monitoring agent
sessions, and reviewing history. Distributed as a separate Python package
(`strawpot-gui`) and launched via `strawpot gui`.

## Features

- **Project Management** — register projects, view config, quick-launch sessions
- **Session Monitoring** — real-time dashboard, agent tree visualization, log streaming
- **Session History** — browse past sessions, view logs, filter by project/date/role
- **EM Replay** — timeline view of event memory, delegation chain visualization

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: React + Vite (TypeScript)
- **Real-time**: Server-Sent Events (SSE)

## Architecture

```
Browser (React SPA)
  │
  ▼
FastAPI server                         ← strawpot-gui package
  │
  ├─ reads .strawpot/sessions/*/session.json       (live session state)
  ├─ reads .strawpot/sessions/*/agents/*/.log       (agent stdout/stderr)
  ├─ reads strawpot.toml                            (project config)
  ├─ connects to denden gRPC server                 (live agent status)
  └─ executes strawpot CLI                          (launch sessions, install)
```

Read-only observer by default. Actions (launch sessions, install packages)
are executed through the strawpot CLI subprocess, never by writing to
runtime state directly.
