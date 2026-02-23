# Loguetown

> Plan. Execute. Review. Merge — with a record.

A local-first, CLI-first multi-agent coding assistant. Specialized AI agents (Planner, Implementer, Reviewer, Fixer) work in isolated git worktrees while a full Chronicle audit trail captures everything.

**Phase 1 (current):** CLI + GUI for project/role/agent management and Chronicle event viewing.

---

## Requirements

- Go 1.22+
- Node.js 18+ (for GUI only)

---

## Install

```bash
git clone https://github.com/steveyegge/loguetown
cd loguetown
go build ./cmd/lt
```

This produces a single `lt` binary. Move it somewhere on your `$PATH`:

```bash
mv lt /usr/local/bin/lt
```

---

## Quick Start

```bash
# 1. Initialise a project (run from inside a git repo)
cd my-project
lt init

# 2. See what was created
lt role list
lt agent list

# 3. Create an agent
lt agent create --name charlie --role implementer

# 4. Open the GUI
lt gui   # → http://localhost:4242
```

---

## CLI Reference

### `lt init [--force]`

Scaffolds `.loguetown/` inside the current git repository:

```
.loguetown/
  project.yaml          # project config, ID, orchestrator settings
  roles/                # planner.yaml, implementer.yaml, reviewer.yaml, fixer.yaml
  agents/               # empty — create with lt agent create
  skills/               # stub .md files for each role
  memory/               # empty
```

Registers the project in `~/.loguetown/db.sqlite` and emits a `PROJECT_INITIALIZED` Chronicle event.

---

### `lt role <subcommand>`

| Subcommand | Description |
|---|---|
| `lt role list` | Table of all roles (name, description, model, skill count, tools) |
| `lt role show <name>` | Print the full role YAML |
| `lt role create <name>` | Scaffold a new role YAML and open in `$EDITOR` |
| `lt role edit <name>` | Open role in `$EDITOR`, re-validate on save |
| `lt role delete <name>` | Remove the role file |

**Built-in roles** (created by `lt init`):

| Role | Model | Tools |
|---|---|---|
| `planner` | claude-opus-4-6 | read |
| `implementer` | claude-opus-4-6 | read, write, bash |
| `reviewer` | claude-opus-4-6 | read |
| `fixer` | claude-opus-4-6 | read, write, bash |

---

### `lt agent <subcommand>`

| Subcommand | Description |
|---|---|
| `lt agent list` | Table of all agents (name, role, model) |
| `lt agent show <name>` | Print the resolved charter (with inherited role defaults) |
| `lt agent create --name <n> --role <r>` | Scaffold a new agent charter YAML |
| `lt agent edit <name>` | Open charter in `$EDITOR`, re-validate on save |

Agent charters live in `.loguetown/agents/<name>.yaml` and inherit defaults from their role. Charter fields override role defaults; `extra_skills` appends to the role's skill list.

---

### `lt gui [--port 4242]`

Starts the web GUI and serves it at `http://localhost:<port>`.

| Page | What it shows |
|---|---|
| Dashboard | Project info, stat cards, recent chronicle events |
| Roles | Role table with detail panel; delete |
| Agents | Agent table with detail panel; create and delete |
| Chronicle | Full event feed; filter by type, actor, limit; expand payload JSON |

---

## Global Data

```
~/.loguetown/
  db.sqlite                          # SQLite — all projects (schema v1)
  data/
    projects/<project-id>/
      events.jsonl                   # Chronicle — append-only JSONL
```

The database schema covers all future phases: projects, plans, tasks, runs, artifacts, messages, memory chunks, skill files, conversations, escalations, and the Chronicle index.

---

## Project Config (`.loguetown/project.yaml`)

```yaml
project:
  id: abc123def456
  name: my-project
  repo_path: .
  default_branch: main

orchestrator:
  model:
    provider: claude
    id: claude-opus-4-6

scheduler:
  max_parallel_runs: 3
  max_fix_attempts: 3
```

---

## Building the GUI

The `lt` binary embeds the compiled React app. After cloning, the placeholder frontend is already embedded. To get the full UI:

```bash
cd web && npm install && npm run build
cd ..  && go build ./cmd/lt
```

### Dev mode (hot-reload)

```bash
# Terminal 1 — Go API server
lt gui

# Terminal 2 — Vite dev server (proxies /api → :4242)
cd web && npm run dev   # http://localhost:5173
```

---

## Repository Layout

```
cmd/lt/              # binary entry point
internal/
  agents/            # Charter YAML loader + role resolution
  chronicle/         # JSONL + SQLite event writer and query
  cmd/               # Cobra CLI commands (init, role, agent, gui)
  config/            # project.yaml loader, git root finder
  roles/             # Role YAML loader and built-in defaults
  server/            # HTTP server + REST API handlers
  storage/           # SQLite schema (v1) and connection singleton
  tui/               # Terminal output helpers (lipgloss)
web/
  src/               # React + TypeScript source
  dist/              # Built frontend (gitignored; rebuild with npm run build)
  embed.go           # Embeds dist/ into the Go binary
plan/                # Design documents for all 8 phases
```

---

## Roadmap

- [x] Phase 1 — Foundation: SQLite schema, Chronicle, roles/agents CLI + GUI
- [ ] Phase 2 — Worktrees: isolated git worktrees per run
- [ ] Phase 3 — Runner: agent subprocess execution via Claude Code
- [ ] Phase 4 — Memory: episodic + semantic retrieval
- [ ] Phase 5 — Orchestrator: plan DAG, task scheduling
- [ ] Phase 6 — Checks & Review: CI integration, merge gates
- [ ] Phase 7 — Full GUI: DAG viewer, diff review, memory browser, chat
- [ ] Phase 8 — Polish: escalation UI, notifications, multi-project
