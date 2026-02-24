# Strawpot — Architecture

## Provider Abstraction

Strawpot has **two provider protocols** serving different use cases. Both are Python `Protocol` classes in `core/agents/provider.py` (structural typing — no inheritance required).

### AgentSessionProvider — Interactive sessions

The primary execution model. Agents run as `claude --dangerously-skip-permissions` in tmux sessions with full tool access. Context (charter + skills + work) is injected at startup via the `SessionStart` hook.

```python
# core/agents/provider.py
class AgentSessionProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def spawn(
        self,
        charter: Charter,
        workdir: Path,
        context: SessionContext,
    ) -> AgentSession: ...

    async def resume(
        self,
        session_name: str,
        workdir: Path,
    ) -> AgentSession: ...
```

**Built-in implementations:**

| Provider key | Class | Description |
|---|---|---|
| `claude_session` | `ClaudeSessionProvider` | Spawns `claude --dangerously-skip-permissions` in a named tmux session. Default. |

**Future:** `openai_session` (Codex CLI), `gemini_session`, or any other agentic CLI wrapper.

### AgentProvider — Programmatic completions

For background tasks, context building, and batch operations where direct message-level control is needed (no tmux, no tool use loop).

```python
class AgentProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 8096,
    ) -> AgentResponse: ...

    def stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 8096,
    ) -> AsyncIterator[str]: ...
```

**Built-in implementations:**

| Provider key | Class | Description |
|---|---|---|
| `claude_api` | `ClaudeAPIProvider` | Anthropic `AsyncAnthropic` SDK. Full message control, no tmux. |
| `claude_subprocess` | `ClaudeSubprocessProvider` | `claude --print` non-interactive mode. Scripted completions. |

### Charter Configuration

```yaml
# .strawpot/agents/charlie.yaml
name: charlie
role: implementer

model:
  provider: claude_session     # claude_session | claude_api | claude_subprocess
  id: claude-opus-4-6          # model ID passed to the agent CLI / API

max_tokens: 8096

tools:
  allowed: [Bash, Read, Write, Edit, Glob, Grep]

instructions: |
  You are an expert implementer. Write clean, well-tested code.
  Always run the test suite before marking a task complete.

```

Charter files are loaded/saved with `Charter.from_yaml(path)` / `charter.to_yaml(path)`.

### Project Context Resolution

All `lt` commands resolve the project working directory automatically — no `--project` flag needed:

1. Walk up from `$CWD` until a `.strawpot/` directory is found (same as `git` finding `.git/`)
2. If `$LT_WORKDIR` is set, use that path instead
3. If neither is found, fail with `not in a strawpot project (no .strawpot/ found)`

`lt prime` is always called by Claude Code from the agent's working directory, so the workdir is always the project root.

### `lt prime` — Session Context Injection

When a session starts, Claude Code fires the `SessionStart` hook defined in `.claude/settings.json`:

```json
{
  "permissions": { "allow": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"] },
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "lt prime --hook"}]}]
  }
}
```

`lt prime --hook` receives JSON on stdin (`session_id`, `transcript_path`, `source`) then:

1. Reads `.strawpot/runtime/agent.json` → resolves agent name + role
2. Loads charter from `.strawpot/agents/<name>.yaml` (falls back to bare runtime identity)
3. `SkillManager.from_charter(charter, workdir)` → resolves three `SkillPool` directories (global / project / agent)
4. Reads `.strawpot/runtime/work.txt` if present
5. `ContextBuilder.build(SessionContext(...))` → structured markdown
6. Persists `session_id` to `.strawpot/runtime/session.json` (for resume support)
7. Prints the markdown → Claude Code prepends it to the agent's context window

**Injected context structure:**
```markdown
# Identity
You are **charlie**, a implementer agent.

# Role Instructions
<charter.instructions>

# Skill Pools

Your skill documentation lives in the directories below.
Each sub-folder is a skill module. Use `Glob` and `Read` to explore,
then synthesise the applicable guidelines into `CLAUDE.md`.
Claude Code will pick up `CLAUDE.md` automatically in future sessions.

| Scope   | Path                                      |
|---------|-------------------------------------------|
| global  | /home/user/.strawpot/skills              |
| project | /path/to/repo/.strawpot/skills           |
| agent   | /path/to/repo/.strawpot/skills/charlie   |

# Current Work
<content of .strawpot/runtime/work.txt>
```

### Session Resume

When a session crashes or is killed, the daemon can respawn it with `claude --resume <session_id>` (the ID is stored in `.strawpot/runtime/session.json`). Claude Code restores its compressed context. `lt prime` re-injects only identity + current work (lighter pass — skills are in the compressed transcript).

---

## Skills Loading

Skills are **folder-based modules** resolved across three pool scopes. `lt prime` does not read or inject skill content — it passes the pool paths and instructs the agent to discover skills organically.

**Pool scope resolution:**

```
~/.strawpot/skills/                          ← global: developer-wide, all projects
<workdir>/.strawpot/skills/                  ← project: all agents in this project
<workdir>/.strawpot/skills/<agent-name>/     ← agent: this agent only
```

`SkillManager.from_charter(charter, workdir)` resolves the three `SkillPool` objects. Only pools whose directories exist on disk are passed to the agent.

**Agent discovery at session start:**

1. Agent receives the pool path table in its injected context
2. Agent uses `Glob` and `Read` to explore each skill module directory
3. Agent identifies modules relevant to the current task
4. Agent synthesises guidelines into `CLAUDE.md` in the working directory
5. Claude Code auto-loads `CLAUDE.md` in all future sessions — no re-reading required

Skills remain discovery-based throughout all phases — no vector embeddings needed.

---

## Data Model (SQLite)

```sql
-- Projects
CREATE TABLE projects (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  repo_path    TEXT NOT NULL,
  default_branch TEXT NOT NULL DEFAULT 'main',
  config_json  TEXT,
  created_at   TEXT NOT NULL
);

-- Plans (one per lt run invocation)
CREATE TABLE plans (
  id                   TEXT PRIMARY KEY,
  project_id           TEXT NOT NULL REFERENCES projects(id),
  objective            TEXT NOT NULL,
  status               TEXT NOT NULL DEFAULT 'draft', -- draft|running|done|failed
  integration_branch   TEXT,
  integration_base     TEXT,
  integration_auto_land INTEGER NOT NULL DEFAULT 0,
  created_at           TEXT NOT NULL
);

-- Tasks (nodes in the plan DAG)
CREATE TABLE tasks (
  id           TEXT PRIMARY KEY,
  plan_id      TEXT NOT NULL REFERENCES plans(id),
  title        TEXT NOT NULL,
  description  TEXT,
  status       TEXT NOT NULL DEFAULT 'todo', -- todo|running|blocked|reviewing|done|failed|needs-human
  deps_json    TEXT,
  labels_json  TEXT,
  acceptance_json TEXT,
  risk_notes   TEXT,
  created_at   TEXT NOT NULL
);

-- Runs (one per agent session on a task)
CREATE TABLE runs (
  id           TEXT PRIMARY KEY,
  task_id      TEXT NOT NULL REFERENCES tasks(id),
  role         TEXT NOT NULL, -- planner|implementer|reviewer|fixer
  status       TEXT NOT NULL DEFAULT 'queued', -- queued|running|succeeded|failed|canceled
  attempt      INTEGER NOT NULL DEFAULT 1,
  agent_name   TEXT,
  session_name TEXT,           -- tmux session name (lt-<agent-name>)
  worktree_path TEXT,
  branch       TEXT,
  base_sha     TEXT,
  head_sha     TEXT,
  started_at   TEXT,
  ended_at     TEXT
);

-- Artifacts produced by runs
CREATE TABLE artifacts (
  id           TEXT PRIMARY KEY,
  run_id       TEXT NOT NULL REFERENCES runs(id),
  kind         TEXT NOT NULL, -- diff|log|junit|coverage|report|patch
  path         TEXT NOT NULL,
  meta_json    TEXT,
  created_at   TEXT NOT NULL
);

-- Dispatch: A2A messages
CREATE TABLE messages (
  id           TEXT PRIMARY KEY,
  plan_id      TEXT,
  task_id      TEXT,
  run_id       TEXT,
  from_actor   TEXT NOT NULL,
  to_actor     TEXT NOT NULL,
  type         TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  reply_to     TEXT,
  delivered    INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL
);

-- Skill pool registry (optional; used by daemon/GUI for enumeration)
CREATE TABLE skill_pools (
  id          TEXT PRIMARY KEY,
  scope       TEXT NOT NULL,   -- global|project|agent
  agent_name  TEXT,            -- set when scope=agent
  pool_path   TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

-- Conversations
CREATE TABLE conversations (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id),
  participant  TEXT NOT NULL,
  title        TEXT,
  created_at   TEXT NOT NULL,
  last_turn_at TEXT
);

CREATE TABLE conversation_turns (
  id              TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  role            TEXT NOT NULL,
  content         TEXT NOT NULL,
  plan_id         TEXT,
  task_id         TEXT,
  run_id          TEXT,
  created_at      TEXT NOT NULL
);

-- Escalations
CREATE TABLE escalations (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id),
  task_id      TEXT REFERENCES tasks(id),
  run_id       TEXT REFERENCES runs(id),
  severity     INTEGER NOT NULL DEFAULT 1,  -- 1=warn, 2=error, 3=critical
  reason       TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'open',
  auto_bump_after_minutes INTEGER,
  created_at   TEXT NOT NULL,
  bumped_at    TEXT,
  resolved_at  TEXT
);

-- Chronicle index (mirrors JSONL, queryable)
CREATE TABLE chronicle (
  id           TEXT PRIMARY KEY,
  ts           TEXT NOT NULL,
  project_id   TEXT,
  plan_id      TEXT,
  task_id      TEXT,
  run_id       TEXT,
  actor        TEXT NOT NULL,
  event_type   TEXT NOT NULL,
  payload_json TEXT
);

CREATE INDEX idx_chronicle_task ON chronicle(task_id);
CREATE INDEX idx_chronicle_run  ON chronicle(run_id);
CREATE INDEX idx_chronicle_type ON chronicle(event_type);
CREATE INDEX idx_chronicle_ts   ON chronicle(ts);

```

---

## Data Flow (End-to-End)

```
User: lt run "Add OAuth2 login"
         │
         ▼
  Daemon creates Plan record
         │
         ▼
  Scheduler: spawn Planner session (ClaudeSessionProvider)
    • lt prime injects: planner charter + planning skills + objective
    • Agent reads repo structure, outputs task DAG
    • Daemon reads output → persists tasks, emits PLAN_CREATED
         │
         ▼
  Scheduler Loop:
    finds unblocked tasks → spawns Implementer sessions (up to max_parallel)
         │
    ┌────┴────────────────────────────────────┐
    ▼                                         ▼
  Session: charlie (implementer) on T1     Session: diana (implementer) on T4
    • lt prime injects: charter + skills     • lt prime injects: charter + skills
      + work item T1                           + work item T4
    • Agent commits code                     • Checks pass
    • checks pass → requests review          • Requests review
         │                                         │
         ▼                                         ▼
  Session: Reviewer on T1 diff             Session: Reviewer on T4 diff
    • 1 blocking finding                     • No blockers
         │                                         │
         ▼                                         ▼
  Session: Fixer on T1                    Merge gate: AWAITING_HUMAN
    • Fixes blocker, re-runs checks
    • Reviewer re-reviews: no blockers
    • Merge gate: AWAITING_HUMAN
         │
         ▼
  GUI: both T1 and T4 show "Ready for approval"
  Human approves → Daemon merges → T2, T3 unblock → cycle continues
```
