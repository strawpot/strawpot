# Loguetown — Configuration and File Layout

## File Layout

```
loguetown/                          # this repo (the tool) — Python
├── core/                           # core Python library
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── agent.py                # Agent class (run/stream for API, spawn for sessions)
│   │   ├── context.py              # ContextBuilder + SessionContext
│   │   ├── manager.py              # AgentManager (provider registry + agent lifecycle)
│   │   ├── provider.py             # AgentProvider + AgentSessionProvider protocols
│   │   ├── session.py              # AgentSession (tmux wrapper)
│   │   ├── types.py                # Charter, ModelConfig, Message, AgentResponse
│   │   └── providers/
│   │       ├── claude_api.py       # Anthropic AsyncAnthropic SDK
│   │       ├── claude_session.py   # tmux + claude --dangerously-skip-permissions
│   │       └── claude_subprocess.py # claude --print (non-interactive fallback)
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── loader.py               # SkillsLoader: scans skill pool directories
│   │   ├── manager.py              # SkillManager: pool resolver (global/project/agent)
│   │   └── types.py                # SkillFile, SkillPool, PoolScope
│   ├── prime.py                    # lt prime --hook (SessionStart context injection)
│   └── __init__.py
│
├── daemon/                         # Control plane (Python, asyncio + SQLite)   [Phase 3+]
│   ├── api/                        # REST + WebSocket server (FastAPI or Starlette)
│   │   └── routes/
│   │       ├── projects.py
│   │       ├── plans.py
│   │       ├── tasks.py
│   │       ├── runs.py
│   │       ├── agents.py
│   │       ├── escalations.py
│   │       ├── conversations.py
│   │       └── chronicle.py
│   ├── scheduler/
│   │   ├── loop.py                 # main scheduling loop
│   │   ├── dag.py                  # DAG unblock logic
│   │   ├── retry.py                # bounded retry policy
│   │   └── patrol.py               # health monitor (stale sessions, escalations)
│   ├── dispatch/
│   │   ├── bus.py                  # A2A message queue (SQLite)
│   │   ├── router.py               # route to agent inboxes
│   │   └── validator.py            # validate typed envelopes
│   ├── merge/
│   │   ├── gate.py                 # gate policy evaluation
│   │   └── executor.py             # git merge operations
│   ├── chronicle/
│   │   ├── writer.py               # append to JSONL + SQLite index
│   │   └── query.py                # Chronicle queries for GUI
│   └── storage/
│       ├── db.py                   # SQLite connection + migrations
│       └── schema.py               # table definitions
│
├── gui/                            # React + Vite frontend                      [Phase 7+]
│   └── src/
│       ├── pages/
│       │   ├── Dashboard.tsx
│       │   ├── PlanDAG.tsx
│       │   ├── RunTimeline.tsx
│       │   ├── DiffReview.tsx
│       │   ├── MergeGate.tsx
│       │   ├── Memory.tsx
│       │   ├── Agents.tsx
│       │   ├── RolesSkills.tsx
│       │   ├── Chat.tsx
│       │   └── Settings.tsx
│       └── components/
│           ├── DAGGraph.tsx
│           ├── EventFeed.tsx
│           ├── DiffViewer.tsx
│           ├── CharterEditor.tsx   # Monaco YAML editor
│           └── SkillEditor.tsx     # Monaco Markdown editor
│
├── tests/
│   └── core/
│       ├── agents/
│       │   ├── test_agent.py
│       │   ├── test_context_and_prime.py
│       │   ├── test_manager.py
│       │   ├── test_providers.py
│       │   ├── test_session_provider.py
│       │   └── test_types.py
│       └── skills/
│           ├── test_loader.py
│           └── test_skill_manager.py
│
├── pyproject.toml
└── .loguetown/                     # per-project config (committed to project repo)
    ├── project.yaml                # check pipelines, merge policy, embeddings config
    ├── roles/                      # role definitions (user-manageable YAML)
    │   ├── planner.yaml
    │   ├── implementer.yaml
    │   ├── reviewer.yaml
    │   ├── fixer.yaml
    │   └── documenter.yaml
    ├── agents/                     # Charter YAML files (one per agent instance)
    │   ├── charlie.yaml
    │   └── diana.yaml
    ├── skills/                     # project-wide skill modules (git-tracked, folder-based)
    │   ├── project-overview/       # each sub-folder is one skill module
    │   │   └── architecture.md
    │   ├── commit-conventions/
    │   │   └── guide.md
    │   └── charlie/                # agent-specific skill pool for "charlie"
    │       ├── typescript-patterns/
    │       │   └── patterns.md
    │       ├── testing-conventions/
    │       │   └── guide.md
    │       └── git-workflow/
    │           └── guide.md
~/.loguetown/                       # global (developer-wide, all projects)
└── skills/                         # global skill pool — applies in every project
    ├── personal-coding-style/      # each sub-folder is one skill module
    │   └── style.md
    └── security-baseline/
        └── checklist.md
```

### Runtime files (per workdir, gitignored)

```
<workdir>/.loguetown/runtime/
    agent.json      ← {"name": "charlie", "role": "implementer"}
    work.txt        ← current task description (written by daemon before spawn)
    session.json    ← {"session_id": "...", "source": "startup", "transcript_path": "..."}

<workdir>/.claude/
    settings.json   ← hook config + allowed tools (written by ClaudeSessionProvider)
```

---

## Project Config (`.loguetown/project.yaml`)

```yaml
project:
  name: my-service
  repo_path: .
  default_branch: main

orchestrator:
  model:
    provider: claude_session
    id: claude-opus-4-6
  max_tasks_per_plan: 20
  stale_session_timeout_minutes: 20

scheduler:
  max_parallel_sessions: 3
  max_fix_attempts: 3

checks:
  setup:
    run: "pip install -e .[dev]"
  lint:
    run: "ruff check ."
  typecheck:
    run: "mypy src"
  test_fast:
    run: "pytest tests/unit -x"
    timeout_seconds: 60
  test_full:
    run: "pytest tests/"
    timeout_seconds: 300

merge:
  approval_policy: require_human
  strategy: squash
  require_checks: [lint, typecheck, test_full]
  require_review: true
  restricted_paths: []

escalation:
  auto_bump_after_minutes: 30
  critical_task_threshold: 3
```

---

## Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Language** | Python 3.11+ | Single-language stack; `asyncio` for concurrent agent sessions |
| **Agent sessions** | `claude --dangerously-skip-permissions` in tmux | Full tool access (read/write/bash); session attach/detach; resume via `--resume` |
| **Completion API** | `anthropic` Python SDK (`AsyncAnthropic`) | Programmatic batch tasks, context building, background completions |
| **Context injection** | `lt prime --hook` (SessionStart hook) | Gastown-style: charter + skills injected at session start via Claude Code hook |
| **Skills** | Folder-based modules in git (global/project/agent scopes) | Agent discovers via Glob/Read, generates CLAUDE.md; human-readable and diffable |
| **Charter / Role config** | YAML (`pyyaml`) | `Charter.from_yaml()` / `to_yaml()`; hot-reloadable; editable in GUI (Monaco) |
| **Backend (daemon)** | Python + FastAPI + asyncio | Same language as core; async-first for concurrent session management |
| **Local DB** | SQLite (`aiosqlite` or `sqlite3`) | Zero-infra, fast queries |
| **Event log** | JSONL files | Append-only, immutable, human-readable |
| **Worktree management** | `gitpython` or `subprocess` | git worktree add/remove |
| **Session management** | `tmux` (via subprocess) | Named sessions; attach/detach; crash-resilient |
| **GUI framework** | React + Vite | Fast dev, large component ecosystem |
| **GUI styling** | Tailwind CSS | Utility-first, dark-mode-ready |
| **GUI DAG renderer** | React Flow | Purpose-built dependency graph |
| **GUI code editor** | Monaco Editor | Charter YAML + skill `.md` editing in-browser |
| **Real-time transport** | WebSocket | Chronicle streaming to GUI |
| **Config format** | YAML | Human-friendly Charters, roles, project config |
| **GitHub integration** | `PyGithub` or `httpx` (v1.2) | Deferred |
