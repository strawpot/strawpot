# Loguetown

> Plan. Execute. Review. Merge — with a record.

A local-first, CLI-first multi-agent coding assistant. Specialized AI agents (Planner, Implementer, Reviewer, Fixer) work in isolated git worktrees while a full Chronicle audit trail captures everything.

**Phase 3 (current):** Single-agent runtime — session builder, git worktree isolation, pluggable runner providers (Claude Code CLI + Anthropic API), plan/task/run lifecycle.

---

## Requirements

- Go 1.22+
- Node.js 18+ (for GUI only)
- Ollama (default) or OpenAI API key (for embedding features)
- `claude` CLI on `$PATH` (for the default `claude-code` runner provider)

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

# 4. Index skill files and search them
lt skills reindex
lt skills search "typescript error handling"

# 5. Spawn an agent to execute a task
lt agent spawn charlie "Add input validation to the login form"

# 6. Inspect the results
lt plan list
lt tasks list
lt tasks show <task-id>

# 7. Open the GUI
lt gui   # → http://localhost:4242
```

---

## CLI Reference

### `lt init [--force]`

Scaffolds `.loguetown/` inside the current git repository:

```
.loguetown/
  project.yaml          # project config, ID, embeddings, memory settings
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
| `lt agent spawn <name> "<task>"` | Execute a task using the named agent |

**`lt agent spawn` flags:**

| Flag | Default | Description |
|---|---|---|
| `--base <branch>` | default branch | Base branch for the git worktree |
| `--no-worktree` | false | Run in the repo root instead of an isolated worktree |

`lt agent spawn` creates a plan + task in SQLite, builds a context-rich system prompt (role identity → skills → memory), creates an isolated git worktree (`lt/<planID>/<taskID>/a1`), executes the task via the configured runner provider, proposes an episodic memory chunk, and cleans up the worktree.

Agent charters live in `.loguetown/agents/<name>.yaml` and inherit defaults from their role. Charter fields override role defaults; `extra_skills` appends to the role's skill list.

---

### `lt skills <subcommand>`

Manages the skills knowledge-base. Skill files are Markdown documents in `.loguetown/skills/` split on `## ` headings into searchable chunks.

| Subcommand | Description |
|---|---|
| `lt skills reindex` | Embed all `.md` files and upsert into the DB; skips unchanged files |
| `lt skills search <query>` | Semantic search; returns top-K chunks sorted by cosine similarity |

**`lt skills search` flags:**

| Flag | Default | Description |
|---|---|---|
| `-k`, `--top` | `5` | Maximum results to return |
| `-s`, `--min-sim` | `0.3` | Minimum cosine similarity score (0–1) |

Embeddings are stored as raw BLOBs (little-endian float32) in SQLite — no CGo or external extensions required. Content hashing (SHA-256) ensures files are re-embedded only when their content changes.

---

### `lt memory <subcommand>`

Manages memory chunks stored by agents across four layers: `episodic`, `semantic_local`, `semantic_global`, `working`.

| Subcommand | Description |
|---|---|
| `lt memory list` | Table of chunks; filter with `--layer`, `--agent`, `--status` |
| `lt memory show <id>` | Full content and metadata of a chunk |
| `lt memory promote <id>` | Approve a proposed chunk (`MEMORY_PROMOTED` Chronicle event) |
| `lt memory reject <id>` | Reject a proposed chunk; `--reason "..."` |

---

### `lt plan <subcommand>`

| Subcommand | Description |
|---|---|
| `lt plan list` | Table of all plans for the current project (ID, status, objective, created) |
| `lt plan show <id>` | Plan details with full task breakdown |

---

### `lt tasks <subcommand>`

| Subcommand | Description |
|---|---|
| `lt tasks list [--plan <id>]` | Table of tasks; defaults to the most recent plan |
| `lt tasks show <id>` | Task details including all runs |

---

### `lt gui [--port 4242]`

Starts the web GUI and serves it at `http://localhost:<port>`.

| Page | What it shows |
|---|---|
| Dashboard | Project info, stat cards, recent chronicle events |
| Roles | Role table with detail panel; delete |
| Agents | Agent table with detail panel; create and delete |
| Chronicle | Full event feed; filter by type, actor, limit; expand payload JSON |

**REST API** (also used by the GUI):

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/project` | Project config |
| `GET/POST/DELETE` | `/api/roles[/{name}]` | Role CRUD |
| `GET/POST/DELETE` | `/api/agents[/{name}]` | Agent CRUD |
| `GET` | `/api/chronicle` | Chronicle feed (`event_type`, `actor`, `limit` params) |
| `GET` | `/api/skills` | List indexed skill chunks (no embedding bytes) |
| `POST` | `/api/skills/reindex` | Trigger skill reindex |
| `GET` | `/api/memory` | List memory chunks (`layer`, `agent`, `status` params) |
| `PATCH` | `/api/memory/{id}` | Update chunk status (`approved` / `rejected`) |
| `GET` | `/api/plans` | List plans (`project_id` param) |
| `GET` | `/api/plans/{id}` | Get plan by ID |
| `GET` | `/api/tasks` | List tasks (`plan_id` param; defaults to latest plan) |
| `GET` | `/api/tasks/{id}` | Get task by ID |
| `GET` | `/api/runs` | List runs (`task_id` param, required) |
| `GET` | `/api/runs/{id}` | Get run by ID |

---

## Embedding Configuration

Loguetown uses pluggable embedding providers for semantic search. Configure in `.loguetown/project.yaml`:

```yaml
embeddings:
  provider: ollama            # or: openai
  model: nomic-embed-text     # or: text-embedding-3-small, all-MiniLM-L6-v2
  base_url: ""                # default: http://localhost:11434 (ollama) or https://api.openai.com
  dimensions: 768             # must match model output
  api_key: ""                 # or set OPENAI_API_KEY env var
```

**Ollama** (default): Start with `ollama serve` and pull `ollama pull nomic-embed-text`.

**OpenAI**: Set `provider: openai` and either `api_key` in the config or the `OPENAI_API_KEY` environment variable.

---

## Runner Configuration

The runner determines how agents execute tasks. Configure in `.loguetown/project.yaml`:

```yaml
runner:
  provider: claude-code      # claude-code | anthropic-api
  model: claude-opus-4-6     # used by anthropic-api provider
  api_key: ""                # or ANTHROPIC_API_KEY env var (anthropic-api only)
  max_turns: 50              # safety cap for the agentic tool-use loop
  timeout_minutes: 20        # kill subprocess / loop after this many minutes
```

**`claude-code`** (default): Spawns `claude -p "<prompt>" --output-format text` as a subprocess in the worktree directory. Requires the `claude` CLI to be installed and on `$PATH`.

**`anthropic-api`**: Calls `POST https://api.anthropic.com/v1/messages` directly with a tool-use agentic loop. Tools available to the agent: `read_file`, `write_file`, `run_bash`, `list_directory`. The loop runs until the model signals `end_turn` or `max_turns` is reached. Set `api_key` or export `ANTHROPIC_API_KEY`.

---

## Memory Configuration

```yaml
memory:
  episodic_retention:
    max_entries: 500
    max_days: 30
  retrieval:
    top_k: 5
    min_similarity: 0.3
  max_tokens_injected: 2000
```

---

## Global Data

```
~/.loguetown/
  db.sqlite                          # SQLite — all projects (schema v2)
  data/
    projects/<project-id>/
      events.jsonl                   # Chronicle — append-only JSONL
      worktrees/<run-id>/            # Isolated git worktrees (cleaned up after each run)
```

The schema covers all phases: projects, plans, tasks, runs, artifacts, messages, memory chunks (with embedding BLOBs), skill files (with embedding BLOBs and content hashes), conversations, escalations, and the Chronicle index.

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
  cmd/               # Cobra CLI commands (init, role, agent, gui, skills, memory, plan, tasks)
  config/            # project.yaml loader (incl. EmbeddingsConfig, MemoryConfig, RunnerConfig)
  embeddings/        # Provider interface, Ollama + OpenAI clients, cosine similarity
  memory/            # memory_chunks CRUD and vector retrieval
  plans/             # Plan, Task, Run CRUD against SQLite
  roles/             # Role YAML loader and built-in defaults
  runner/            # Pluggable provider interface; Claude Code + Anthropic API providers
  server/            # HTTP server + REST API handlers
  session/           # System prompt builder (role + skills + memory + context)
  skills/            # Skill file indexer (chunking, embedding) and search
  storage/           # SQLite schema (v2) and connection singleton
  tui/               # Terminal output helpers (lipgloss)
  worktree/          # Git worktree lifecycle (create, remove, HEAD SHA)
web/
  src/               # React + TypeScript source
  dist/              # Built frontend (gitignored; rebuild with npm run build)
  embed.go           # Embeds dist/ into the Go binary
plan/                # Design documents for all 8 phases
```

---

## Roadmap

- [x] Phase 1 — Foundation: SQLite schema, Chronicle, roles/agents CLI + GUI
- [x] Phase 2 — Skills + Memory: pluggable embedding providers, skill indexing, semantic search, memory chunk management
- [x] Phase 3 — Runner: session builder, git worktree isolation, pluggable runner providers (Claude Code + Anthropic API), plan/task/run lifecycle, episodic memory proposals
- [ ] Phase 4 — Orchestrator: plan DAG, multi-task scheduling, agent handoffs
- [ ] Phase 5 — Checks & Review: CI integration, merge gates, reviewer agent workflow
- [ ] Phase 6 — Full GUI: DAG viewer, diff review, memory browser, chat
- [ ] Phase 7 — Polish: escalation UI, notifications, multi-project
