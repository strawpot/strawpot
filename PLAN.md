# Loguetown — Design Plan

> Plan. Execute. Review. Merge—with a record.

---

## 0. Goal and Non-Goals

### Goal

Build a local-first system for solo developers that can:

- Generate a plan (DAG of tasks) from a natural-language objective
- Spawn multiple specialized agents (Planner / Implementer / Reviewer / Fixer) working in parallel on a monorepo using git worktrees
- Run deterministic checks (lint / typecheck / tests) automatically
- Produce review artifacts and a configurable merge gate
- Support configurable merge approval policies (auto-merge, require human, risk-based)
- Record a full trace (append-only event log) for every run, visible in a GUI cockpit
- Manage agents via hot-reloadable YAML Charters (role, skills, memory, instructions)
- Enable structured agent-to-agent communication

### Design Philosophy: CLI-First, GUI-Complete

**The CLI is the primary interface.** Every operation — creating roles, editing agents, managing memory, running plans, approving tasks — is doable from the terminal without ever opening a browser.

**The GUI is a full management interface** with three purposes:
1. **Visualization** — things genuinely better as visuals: DAG graph, diff viewer, interleaved run timeline
2. **Management** — create, edit, and delete agents, roles, skill files, and memory chunks with live feedback (retrieval preview, similarity scores, role inheritance)
3. **Human moderation + conversation** — approve/reject merge gate and memory; chat directly with the orchestrator or any individual agent; inspect full conversation transcripts

If an action can be expressed as a command, it lives in the CLI. The GUI calls the same underlying API — it adds richer interaction (forms, diffs, chat UI) not exclusive data.

### Non-Goals (v0 / v1)

- Multi-tenant SaaS, remote/distributed workers, team RBAC
- GitHub Issues / PR automation *(deferred to v1.2)*
- Fully autonomous auto-merge for risky diffs
- IDE plugin *(deferred to v2)*
- Distributed runners

---

## 1. User Experience

### Primary Flow (CLI-driven)

```bash
cd my-project
lt init                                    # scaffold .loguetown/ in the repo
lt role create documenter                  # optional: add a custom role
lt agent create --name charlie --role implementer
lt run "Add OAuth2 login with Google and GitHub"
                                           # Planner runs, produces DAG, prints task list
lt plan show                               # inspect the plan before execution starts
lt plan start                              # begin execution (or: lt run --auto-start)
lt status                                  # watch progress in the terminal
lt chronicle --tail 50                     # stream live events
lt tasks list                              # see which tasks are awaiting approval
lt tasks approve tk-xyz34                  # approve a merge after reviewing the diff
```

The GUI (`lt gui`) can be opened at any point for richer visualization, but every step above is fully operational from the terminal.

**Steps that benefit from the GUI:**
- Reviewing diffs with inline reviewer findings before approving
- Watching the live DAG as tasks unblock and complete
- Browsing episodic memory and approving/rejecting proposed chunks

### GUI Screens

The GUI is a **full management interface**. It calls the same API as the CLI and adds richer interaction.

| Screen | Type | CLI equivalent |
|---|---|---|
| **Dashboard** | Visualization + moderation | `lt escalate list`, `lt status` |
| **Plan / DAG** | Visualization | `lt plan show`, `lt status` |
| **Run Timeline** | Visualization | `lt chronicle --task <id>` |
| **Diff & Review** | Visualization + moderation | `lt diff <task-id>`, `lt tasks approve/reject` |
| **Merge Gate** | Moderation | `lt tasks approve/reject <id>` |
| **Memory** | Management + moderation | `lt memory list/show/promote/reject/deprecate` |
| **Agents** | Management | `lt agent list/create/edit/spawn` |
| **Roles & Skills** | Management | `lt role list/create/edit`, `lt skills list/add/edit` |
| **Chat** | Conversation | `lt chat [--agent <name>]` |
| **Settings** | Configuration | `lt init`, edit `.loguetown/project.yaml` |

---

## 2. Architecture Overview

Local control plane + local execution plane + GUI, all on one machine.

```
┌──────────────────────────────────────────────────────────────────┐
│                      CLI  (lt ...)  — Python                     │
└───────────────────────┬──────────────────────────────────────────┘
                        │ REST / WebSocket
┌───────────────────────▼──────────────────────────────────────────┐
│                   Daemon (Control Plane) — Python                 │
│  • Owns canonical state (SQLite)                                  │
│  • Validates A2A message schemas                                  │
│  • Writes append-only trace events (JSONL + SQLite index)         │
│  • Schedules runs, handles retries, manages merge gate            │
│  • Serves REST API + WebSocket to GUI                             │
└────────┬──────────────────────────────────────┬───────────────────┘
         │ ClaudeSessionProvider.spawn()          │ REST / WS
         │ (tmux + lt prime --hook)               │
┌────────▼─────────────────────┐    ┌────────────▼─────────────────┐
│   Agent Session (tmux)       │    │      GUI (React / Vite)       │
│  • claude --dangerously-...  │    │  • DAG, timelines, diffs      │
│  • SessionStart hook fires   │    │  • Merge gate, memory browser │
│  • lt prime --hook injects:  │    │  • Real-time event stream     │
│    - Charter identity        │    │  • Charter YAML editor        │
│    - Role instructions       │    └──────────────────────────────┘
│    - Skills (all *.md)       │
│    - Current work item       │
│  • Agent runs with full      │
│    Claude tool access        │
│  • Session resumable via     │
│    --resume <session-id>     │
└──────────────────────────────┘
```

### Agent Session Startup Flow

```
AgentManager.spawn(charter, workdir, context)
    │
    ├─ Write .loguetown/runtime/agent.json    (identity)
    ├─ Write .loguetown/runtime/work.txt      (current task)
    ├─ Write .claude/settings.json            (hook + allowed tools)
    └─ tmux new-session: claude --dangerously-skip-permissions
           │
           └─ SessionStart hook → lt prime --hook
                  ├─ Reads agent.json → resolves charter YAML
                  ├─ SkillsLoader.load(role)
                  │     global/ → shared/ → <role>/
                  ├─ ContextBuilder.build()
                  │     # Identity + Role Instructions + Skills + Current Work
                  ├─ Persists session_id → .loguetown/runtime/session.json
                  └─ Prints markdown context → injected into Claude's context
```

### Components

| Component | Responsibility |
|---|---|
| **CLI** | Primary interface for all operations; thin client over the daemon REST API |
| **Daemon** | State authority, scheduler, event logger, REST + WebSocket API server |
| **AgentManager** | Provider registry + agent lifecycle; spawns sessions via `AgentSessionProvider` |
| **ClaudeSessionProvider** | Starts `claude --dangerously-skip-permissions` in a named tmux session; writes hook config |
| **`lt prime`** | SessionStart hook command; builds and prints charter + skills context at session start |
| **SkillsLoader** | Scans `~/.loguetown/skills/global/`, `.loguetown/skills/shared/`, `.loguetown/skills/<role>/` |
| **ContextBuilder** | Assembles identity + instructions + skills + work into injected markdown |
| **Chronicle** | Append-only JSONL event log (canonical) + SQLite index (queryable) |
| **Dispatch** | A2A message bus; daemon validates envelopes, routes to agent inboxes |
| **GUI** | Full management interface (visualization + management + moderation + chat); served at `localhost:PORT`; calls the same API as the CLI |

---

## Detail Documents

| Document | Contents |
|---|---|
| [plan/concepts.md](plan/concepts.md) | Agent Charter, Skills, Roles, Memory (layers, retrieval, lifecycle), Task, Integration Branch, Dispatch (A2A), Chronicle (events), Escalation |
| [plan/architecture.md](plan/architecture.md) | Model Provider Abstraction, SQLite Data Model (all tables + indexes), End-to-End Data Flow |
| [plan/runtime.md](plan/runtime.md) | Git / Worktree Strategy, Check Pipelines, Orchestration + Scheduler Loop + Patrol Loop, Merge Gate (approval policies), Security |
| [plan/config.md](plan/config.md) | Full File Layout (monorepo + `.loguetown/`), Project Config (`project.yaml` reference), Technology Stack |
| [plan/cli.md](plan/cli.md) | Complete CLI reference — all `lt` commands with flags and descriptions |
| [plan/gui.md](plan/gui.md) | GUI Deep Dive — all screens: DAG, Timeline, Diff & Review, Merge Gate, Memory, Agents, Roles & Skills, Chat |
| [plan/roadmap.md](plan/roadmap.md) | Implementation Phases (1–8), Extensibility Roadmap (v1.1, v1.2, v2), Key Differences from Gastown, Open Questions |
