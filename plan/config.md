# Loguetown — Configuration and File Layout

## File Layout

```
loguetown/                          # this repo (the tool)
├── packages/
│   ├── daemon/                     # Control plane (Node.js / TypeScript)
│   │   ├── src/
│   │   │   ├── api/                # REST + WebSocket server (Fastify)
│   │   │   │   ├── routes/
│   │   │   │   │   ├── projects.ts
│   │   │   │   │   ├── plans.ts
│   │   │   │   │   ├── tasks.ts
│   │   │   │   │   ├── runs.ts
│   │   │   │   │   ├── agents.ts
│   │   │   │   │   ├── memory.ts
│   │   │   │   │   ├── escalations.ts
│   │   │   │   │   ├── conversations.ts
│   │   │   │   │   └── chronicle.ts
│   │   │   │   └── ws.ts           # WebSocket: stream Chronicle events
│   │   │   ├── scheduler/
│   │   │   │   ├── loop.ts         # main scheduling loop
│   │   │   │   ├── dag.ts          # DAG unblock logic
│   │   │   │   ├── retry.ts        # bounded retry policy
│   │   │   │   └── patrol.ts       # health monitor loop (stale runs, escalations, notifications)
│   │   │   ├── dispatch/
│   │   │   │   ├── bus.ts          # message queue (SQLite)
│   │   │   │   ├── router.ts       # route to agent inboxes
│   │   │   │   └── validator.ts    # validate typed envelopes
│   │   │   ├── merge/
│   │   │   │   ├── gate.ts         # gate policy evaluation
│   │   │   │   └── executor.ts     # git merge operations
│   │   │   ├── chronicle/
│   │   │   │   ├── writer.ts       # append to JSONL + SQLite index
│   │   │   │   └── query.ts        # Chronicle queries for GUI
│   │   │   └── storage/
│   │   │       ├── db.ts           # SQLite connection + migrations
│   │   │       ├── schema.ts       # table definitions
│   │   │       └── migrations/
│   │   └── package.json
│   │
│   ├── runner/                     # Execution plane (Node.js subprocess)
│   │   ├── src/
│   │   │   ├── session.ts          # build agent context (Charter + skills + memory)
│   │   │   ├── executor.ts         # run agent loop (Anthropic SDK)
│   │   │   ├── worktree.ts         # create/cleanup git worktrees
│   │   │   ├── checks.ts           # run check pipeline commands
│   │   │   ├── memory/
│   │   │   │   ├── injector.ts     # retrieve + inject memory into system prompt
│   │   │   │   ├── writer.ts       # propose new memory chunks
│   │   │   │   ├── providers/
│   │   │   │   │   ├── local.ts    # Markdown files + sqlite-vec (default)
│   │   │   │   │   ├── mem0.ts     # Mem0 provider adapter
│   │   │   │   │   └── custom.ts   # dynamic loader for user-supplied providers
│   │   │   │   └── embedder.ts     # embed text via @xenova/transformers or OpenAI
│   │   │   ├── models/
│   │   │   │   ├── providers/
│   │   │   │   │   ├── claude.ts   # Anthropic SDK
│   │   │   │   │   ├── openai.ts   # OpenAI SDK
│   │   │   │   │   └── ollama.ts   # Ollama REST API
│   │   │   │   └── registry.ts     # resolve provider by name, load custom
│   │   │   ├── skills/
│   │   │   │   ├── loader.ts       # scan .loguetown/skills/, read .md files
│   │   │   │   └── retriever.ts    # vector search over skill files
│   │   │   └── events.ts           # stream events back to daemon
│   │   └── package.json
│   │
│   └── gui/                        # React + Vite frontend
│       ├── src/
│       │   ├── pages/
│       │   │   ├── Dashboard.tsx
│       │   │   ├── PlanDAG.tsx
│       │   │   ├── TaskDetail.tsx
│       │   │   ├── RunTimeline.tsx
│       │   │   ├── DiffReview.tsx
│       │   │   ├── MergeGate.tsx
│       │   │   ├── Memory.tsx
│       │   │   ├── Agents.tsx
│       │   │   ├── RolesSkills.tsx
│       │   │   ├── Chat.tsx
│       │   │   └── Settings.tsx
│       │   ├── components/
│       │   │   ├── DAGGraph.tsx     # task dependency graph (React Flow)
│       │   │   ├── EventFeed.tsx    # live Chronicle stream
│       │   │   ├── DiffViewer.tsx   # code diff with findings overlay
│       │   │   ├── MessageTrace.tsx # A2A message thread view
│       │   │   ├── MemoryCard.tsx   # entry with promote/reject actions
│       │   │   ├── AgentCard.tsx
│       │   │   └── CharterEditor.tsx # in-browser YAML editor (Monaco)
│       │   └── lib/
│       │       ├── ws.ts            # WebSocket client
│       │       └── api.ts           # REST client
│       └── package.json
│
├── cli/                            # lt CLI — primary interface (Commander.js)
│   └── src/
│       ├── client.ts               # thin REST client wrapping the daemon API
│       ├── output.ts               # formatted terminal output (tables, trees, colors)
│       ├── commands/
│       │   ├── init.ts             # lt init
│       │   ├── plan.ts             # lt plan create/show/start/stop
│       │   ├── run.ts              # lt run <objective>
│       │   ├── status.ts           # lt status
│       │   ├── role.ts             # lt role list/create/edit/show
│       │   ├── agent.ts            # lt agent create/list/edit/spawn
│       │   ├── skills.ts           # lt skills list/add/edit/reindex
│       │   ├── memory.ts           # lt memory list/show/promote/reject/deprecate/reindex
│       │   ├── tasks.ts            # lt tasks list/show/approve/reject
│       │   ├── diff.ts             # lt diff <task-id>  (prints unified diff to stdout)
│       │   ├── review.ts           # lt review show <task-id>  (print reviewer findings)
│       │   ├── chronicle.ts        # lt chronicle (tail / filter)
│       │   ├── escalate.ts         # lt escalate list/show/ack/resolve
│       │   ├── chat.ts             # lt chat [--agent <name>] [--history]
│       │   └── gui.ts              # lt gui  (start browser UI server)
│       └── main.ts
│
└── .loguetown/                     # per-project config (committed to project repo)
    ├── project.yaml                # check pipelines, merge strategy, policies, embeddings
    ├── roles/                      # role definitions (user-manageable)
    │   ├── planner.yaml
    │   ├── implementer.yaml
    │   ├── reviewer.yaml
    │   ├── fixer.yaml
    │   └── documenter.yaml         # example custom role
    ├── agents/                     # Charter YAML files (one per agent instance)
    │   ├── charlie.yaml
    │   └── diana.yaml
    ├── skills/                     # *.md skill files (git-tracked)
    │   ├── implementer/
    │   │   ├── typescript-patterns.md
    │   │   ├── testing-conventions.md
    │   │   └── git-workflow.md
    │   ├── reviewer/
    │   │   ├── code-review-checklist.md
    │   │   └── security-checklist.md
    │   ├── documenter/
    │   │   └── api-docs-style.md
    │   ├── planner/
    │   │   └── decomposition-heuristics.md
    │   └── shared/
    │       ├── commit-style.md
    │       └── project-overview.md
    └── memory/                     # memory chunk files per agent (git-tracked)
        └── {agent-name}/
            ├── episodic/
            │   ├── 2025-01-15-oauth-state-csrf.md
            │   └── 2025-01-20-db-migration-rollback.md
            ├── semantic_local/
            │   └── my-service/
            │       ├── auth-architecture.md
            │       └── api-error-format.md
            └── semantic_global/ -> ~/.loguetown/memory/{agent}/semantic_global/
```

---

## Project Config (`.loguetown/project.yaml`)

```yaml
project:
  name: my-service
  repo_path: .              # relative to this file
  default_branch: main

orchestrator:
  model:
    provider: claude
    id: claude-opus-4-6
  max_tasks_per_plan: 20
  stale_run_timeout_minutes: 20

scheduler:
  max_parallel_runs: 3
  max_fix_attempts: 3       # per task before escalating to human

embeddings:
  provider: local           # local | openai | custom
  model: all-MiniLM-L6-v2  # for local provider; ~23MB, runs on-device
  dimensions: 384
  # provider: openai
  # model: text-embedding-3-small

memory:
  episodic_retention:
    max_entries: 100
    max_days: 90
  retrieval:
    top_k: 5               # chunks per layer retrieved per session
    min_similarity: 0.65
  max_tokens_injected: 6000

checks:
  setup:
    run: "npm ci"
  lint:
    run: "npx eslint src"
  typecheck:
    run: "npx tsc --noEmit"
  test_fast:
    run: "npm test -- --testPathPattern=unit"
    timeout_seconds: 60
  test_full:
    run: "npm test"
    timeout_seconds: 300
    retry_on_flake: 1

merge:
  approval_policy: require_human   # require_human | auto | risk_based
  auto_merge_max_risk_score: 0.3   # used when approval_policy: risk_based (0.0–1.0)
  strategy: squash                 # squash | ff
  require_checks: [lint, typecheck, test_full]
  require_review: true
  restricted_paths: []             # always require_human if these paths are touched

escalation:
  auto_bump_after_minutes: 30    # bump severity after this time if unacknowledged
  critical_task_threshold: 3     # escalate to critical when ≥ N tasks need-human

notifications:
  # At least one channel must be configured for push alerts to work.
  # All channels are optional; leave section empty to disable notifications.
  on_needs_human:
    desktop: true                  # macOS/Linux desktop notification
    # webhook: https://hooks.slack.com/... # POST JSON payload to this URL
  on_escalation_bumped:
    desktop: true
  on_merge_ready:
    desktop: true

gui:
  port: 4242
  auth: false
```

---

## Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Default agent runtime | `@anthropic-ai/sdk` (Claude) | Native tool use, streaming, Claude 4.x; TypeScript-first |
| Alt model: OpenAI | `openai` npm package | ModelProvider adapter for GPT/o1 |
| Alt model: local | Ollama REST API | ModelProvider adapter for on-device models |
| Backend (daemon) | Node.js + TypeScript + Fastify | Same language as SDK; Fastify is fast and schema-validating |
| Runner subprocess | Node.js + TypeScript | Shares types with daemon; spawned as child process |
| Local DB | SQLite (`better-sqlite3`) | Zero-infra, sync writes, fast queries |
| Vector search | `sqlite-vec` extension | In-process vector similarity search over memory + skills embeddings |
| Embeddings (default) | `@xenova/transformers` (`all-MiniLM-L6-v2`) | On-device, no API key, ~23MB, 384-dim |
| Embeddings (alt) | OpenAI `text-embedding-3-small` | Higher quality, requires API key |
| Event log | JSONL files | Append-only, immutable, human-readable |
| Memory + Skills | Markdown files in git | Human-readable, diffable, per-chunk files |
| Worktree management | `simple-git` + `child_process` | git operations from Node |
| GUI framework | React + Vite | Fast dev, large component ecosystem |
| GUI styling | Tailwind CSS | Utility-first, dark-mode-ready |
| GUI DAG renderer | React Flow | Purpose-built dependency graph visualization |
| GUI code editor | Monaco Editor | In-browser Charter YAML and skill `.md` editing |
| Real-time transport | WebSocket (`ws`) | Low-latency Chronicle streaming to GUI |
| CLI framework | Commander.js | Mature, composable |
| Config format | YAML | Human-friendly Charters, roles, and project config |
| GitHub integration | Octokit (`@octokit/rest`) | v1.2 only |
