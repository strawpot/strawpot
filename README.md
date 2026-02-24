# Loguetown

> Plan. Execute. Review. Merge — with a record.

A local-first, CLI-first multi-agent coding assistant. Specialized AI agents (Planner, Implementer, Reviewer, Fixer) work in isolated git worktrees while a full Chronicle audit trail captures everything.

**Phase 6 (current):** Merge agent + patrol loop — agent commits are automatically cherry-picked onto the default branch after each successful run; `lt patrol` recovers orphaned tasks and re-enqueues stalled plans.

---

## Requirements

- Go 1.22+
- Node.js 18+ (for GUI only)
- Ollama (default) or OpenAI API key (for embedding features)
- `claude` CLI on `$PATH` (for the default `claude-code` runner provider)

---

## Install

```bash
git clone https://github.com/juhgiyo/loguetown
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

# 5. Orchestrate tasks conversationally
lt chat
# > Create a plan to add OAuth login
# > Start it
# > What's the status?

# 6. Or run non-interactively (blocking; commits land on default branch when done)
lt run "Add input validation to the login form"
lt run "Refactor the auth module" --dry-run   # preview the plan only

# 7. Recover a stalled plan (e.g. after a crash)
lt patrol --once   # reset orphaned tasks, re-run, merge
lt patrol          # keep watching indefinitely

# 8. Spawn a single agent to execute one task
lt agent spawn charlie "Add input validation to the login form"

# 9. Run the check pipeline manually
lt checks run
lt checks run lint typecheck    # run specific steps only

# 10. Inspect the results
lt plan list
lt tasks list
lt tasks show <task-id>

# 11. Open the GUI
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

Manages the skills knowledge-base. Skill files are Markdown documents split on `## ` headings into searchable chunks. Three scopes are supported:

| Scope | Directory | Indexed as |
|---|---|---|
| **agent** | `.loguetown/skills/agents/<name>/` | agent-specific skills |
| **project** | `.loguetown/skills/<role>/` and `.loguetown/skills/shared/` | shared within the project |
| **global** | `~/.loguetown/skills/global/` | cross-project (all repos) |

| Subcommand | Description |
|---|---|
| `lt skills reindex` | Embed all scopes (global + project); skips unchanged files |
| `lt skills reindex --global` | Only re-embed `~/.loguetown/skills/global/` |
| `lt skills reindex --project` | Only re-embed `.loguetown/skills/` |
| `lt skills reindex --agent <name>` | Only re-embed `.loguetown/skills/agents/<name>/` |
| `lt skills search <query>` | Semantic search across all scopes; results show scope column |

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

### `lt checks <subcommand>`

| Subcommand | Description |
|---|---|
| `lt checks list` | Table of all configured check steps (name, command, timeout, on-fail) |
| `lt checks run [<name>...]` | Run all checks (or named subset) in the project root |

**`lt checks run` flags:**

| Flag | Description |
|---|---|
| `--base <sha>` | Enable path routing — only skip checks when all changes since this commit match routing patterns |

---

### `lt chat [--conv <id>]`

Interactive conversational entry point. Starts an Orchestrator agent session backed by the Anthropic API.

```bash
lt chat                      # start a new conversation
lt chat --conv <id>          # resume an existing conversation
```

The Orchestrator uses a tool-use loop to:
- **Create a plan** — calls the Planner to decompose your objective into a task DAG and stores it in SQLite.
- **Start execution** — enqueues the plan in the Scheduler goroutine, which spawns runners as task dependencies are resolved.
- **Check status** — lists plans/tasks with current status.
- **View chronicle** — returns recent audit events.
- **Search memory** — semantic recall via embeddings.
- **Re-queue a task** — manually re-trigger a failed task.

The Orchestrator will ask for confirmation before starting plan execution. Type `Ctrl+C` to exit and stop the Scheduler gracefully.

Conversation history is persisted in the `conversations` / `conversation_turns` SQLite tables and survives across sessions.

---

### `lt run <objective> [--dry-run]`

Non-interactive scripting shortcut — useful for CI or one-shot automation.

```bash
lt run "Add OpenAPI documentation to all REST endpoints"
lt run "Refactor the auth module" --dry-run   # print the plan, don't execute
```

1. Calls the **Planner** to produce a task DAG (one Anthropic API call with forced `tool_choice`).
2. Prints a table: `ID | Title | Deps | Agent`.
3. If `--dry-run` is not set: persists tasks in SQLite and calls `scheduler.RunAll()` (blocking until all tasks reach `done` or `failed`).
4. Prints a final status table and exits with a summary.

---

### `lt patrol [--once]`

Recovers from a crashed scheduler and resumes in-flight plans.

```bash
lt patrol          # runs indefinitely — picks up any plans from lt chat / lt run
lt patrol --once   # single scheduling pass then exit (useful in scripts / CI)
```

On startup `lt patrol`:
1. **Resets orphaned tasks** — tasks stuck in `"running"` (left behind by a killed scheduler) are reset to `"todo"` so they are re-picked.
2. **Re-enqueues running plans** — finds all plans with `status="running"` and enqueues them in the Scheduler.
3. **Starts the Scheduler** — processes queued tasks using the configured runner, merging agent commits when done.

**Task lifecycle with merge agent:**

| Status | Meaning |
|---|---|
| `todo` | Waiting for dependencies or not yet started |
| `running` | Agent goroutine active |
| `done` | Agent succeeded but made no commits (nothing to merge) |
| `merged` | Agent commits successfully cherry-picked onto the default branch |
| `merge_conflict` | Cherry-pick failed — needs human resolution; plan marked `failed` |
| `failed` | Run exhausted retries or encountered a fatal error |

Successful cherry-picks emit a `TASK_MERGED` Chronicle event; conflicts emit `TASK_MERGE_CONFLICT` and leave the working tree clean (cherry-pick is aborted automatically).

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
| `GET` | `/api/conversations` | List conversations (`project_id` param) |
| `GET` | `/api/conversations/{id}/turns` | List turns for a conversation (ordered by `created_at ASC`) |

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

## Orchestrator Configuration

Controls the Scheduler and multi-agent execution. Configure in `.loguetown/project.yaml`:

```yaml
orchestrator:
  max_parallel: 3        # max concurrent agent runs (default: 3)
  max_fix_attempts: 2    # Fixer retry attempts before marking a task failed (default: 2)
  poll_interval_sec: 10  # how often the Scheduler checks for unblocked tasks (default: 10)
```

The Scheduler polls the SQLite `tasks` table for tasks whose dependencies are all in `done` status. It spawns up to `max_parallel` runner goroutines at a time. Failed runs are retried via the Fixer pipeline up to `max_fix_attempts` times before the task is marked `failed`.

**Dependency resolution**: Task DAGs are stored as a `deps_json` JSON array of task IDs per task row. `ListReadyTasks()` resolves deps in Go — no complex SQL required.

---

## Check Pipelines

Define per-project check commands in `.loguetown/project.yaml`. Checks run automatically after `lt agent spawn` completes (when execution succeeds) and can also be triggered manually.

```yaml
checks:
  - name: build
    run: "go build ./..."
  - name: test
    run: "go test ./..."
    timeout_seconds: 120
    retry_on_flake: 1       # retry once on non-zero exit (for flaky tests)
  - name: lint
    run: "golangci-lint run"
    on_fail: warn           # "warn" continues the pipeline; "block" (default) stops it
```

### `lt checks list`

Print all configured check steps with timeout and on-fail policy.

### `lt checks run [<name>...]`

Run the full check pipeline (or named steps) in the current project directory.

| Flag | Description |
|---|---|
| `--base <sha>` | Enable path routing — compare changed files since this commit |

**Path routing** skips named checks when all changed files match a pattern set:

```yaml
path_routing:
  docs_only:
    patterns: ["docs/**", "*.md", "README*"]
    skip: [lint, test]
```

Supported glob patterns: `dir/**` (all files under dir), `**/<suffix>` (suffix at any depth), `*.ext` (base-name match).

**Check output** (stdout + stderr) is saved to `~/.loguetown/data/projects/<id>/artifacts/<runID>/checks/<name>.txt` and recorded in the `artifacts` SQLite table. Chronicle events `COMMAND_STARTED` and `COMMAND_FINISHED` are emitted for every check step.

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
  db.sqlite                          # SQLite — all projects (schema v5)
  skills/global/                     # Cross-project global skills (indexed once, used everywhere)
  memory/global/
    semantic_global/                 # Cross-project memory (follows you across all repos)
  data/
    projects/<project-id>/
      events.jsonl                   # Chronicle — append-only JSONL
      worktrees/<run-id>/            # Isolated git worktrees (cleaned up after each run)
      artifacts/<run-id>/
        checks/<name>.txt            # stdout+stderr from each check step

.loguetown/                          # per-project (inside the git repo)
  skills/
    shared/                          # Skills available to all roles in this project
    <role>/                          # Role-specific skills (project scope)
    agents/<agent>/                  # Agent-specific skills (agent scope)
  memory/
    <agent>/
      episodic/                      # Past run experiences (agent-scoped)
      semantic_local/                # Project facts and conventions
```

The schema covers all phases: projects, plans, tasks (with `deps_json` + `agent_name`), runs, artifacts, messages (A2A dispatch bus), memory chunks (with embedding BLOBs), skill files (with embedding BLOBs, content hashes, scope, and agent name), conversations + conversation turns, escalations, and the Chronicle index.

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
  checks/            # Check pipeline executor (run, timeout, retry, artifact store, path routing)
  chronicle/         # JSONL + SQLite event writer and query
  cmd/               # Cobra CLI commands (init, role, agent, gui, skills, memory, plan, tasks, checks, chat, run, patrol)
  config/            # project.yaml loader (EmbeddingsConfig, MemoryConfig, RunnerConfig, CheckStep, OrchestratorConfig)
  conversation/      # Conversation + turn CRUD (conversations / conversation_turns tables)
  dispatch/          # A2A message bus (messages table; Send / Poll / MarkDelivered)
  embeddings/        # Provider interface, Ollama + OpenAI clients, cosine similarity
  memory/            # memory_chunks CRUD and vector retrieval
  merge/             # MergeRun: cherry-pick agent commits onto default branch after success
  orchestrator/      # Planner (forced tool_use → task DAG), tool implementations, chat loop
  plans/             # Plan, Task, Run CRUD against SQLite; ListReadyTasks dep resolution
  roles/             # Role YAML loader and built-in defaults
  runner/            # Pluggable provider interface; Claude Code + Anthropic API providers
  scheduler/         # Background polling goroutine; Enqueue / Start / Stop / RunAll
  server/            # HTTP server + REST API handlers
  session/           # System prompt builder (role + skills + memory + context)
  skills/            # Skill file indexer (chunking, embedding, 3-scope) and search
  storage/           # SQLite schema (v5) and connection singleton
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
- [x] Phase 2 — Skills + Memory: global + project-local skill scopes, pluggable embeddings, semantic search, multi-layer memory (global/local/episodic)
- [x] Phase 3 — Runner: session builder, git worktree isolation, pluggable runner providers (Claude Code + Anthropic API), plan/task/run lifecycle, episodic memory proposals
- [x] Phase 4 — Check Pipelines: per-project check commands (lint, typecheck, test), timeout + retry + warn/block policy, path-based routing, stdout/stderr artifact store
- [x] Phase 5 — Orchestration (Chat-First): conversational Orchestrator agent (`lt chat`), Planner → task DAG, background Scheduler with dep resolution, Reviewer + Fixer retry pipeline, A2A dispatch (`messages` table), `lt run` scripting shortcut, conversation persistence
- [x] Phase 6 (simplified) — Merge Agent + Patrol Loop: cherry-pick agent commits onto default branch after success (`merged`/`merge_conflict` task states), `lt patrol` for orphan recovery and plan re-enqueue
- [ ] Phase 6 (remaining) — Full Merge Gate + Escalation: approval policies, integration branches, escalation system, notification channels
- [ ] Phase 7 — Full GUI: Plan/DAG viewer, diff & review, memory browser, orchestrator chat screen
- [ ] Phase 8 — Polish: mem0 adapter, custom memory providers, failure summaries, GUI auth
