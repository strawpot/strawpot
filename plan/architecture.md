# Loguetown — Architecture

## Model Provider Abstraction

The system defaults to Claude Code (Anthropic SDK) but is designed to swap model backends per-agent or per-role.

### Provider Interface

```typescript
interface ModelProvider {
  name: string;
  complete(
    messages: ChatMessage[],
    options: CompletionOptions
  ): Promise<CompletionResponse>;
  stream(
    messages: ChatMessage[],
    options: CompletionOptions
  ): AsyncGenerator<CompletionChunk>;
  supportsTools(): boolean;
}
```

The Runner resolves the provider from the agent's Charter `model.provider` field and instantiates the appropriate implementation.

### Built-in Providers

| Provider key | Implementation | Models |
|---|---|---|
| `claude` | `@anthropic-ai/sdk` | claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5 |
| `openai` | `openai` npm package | gpt-4o, gpt-4-turbo, o1, etc. |
| `ollama` | Ollama REST API | llama3, mistral, qwen2.5-coder, etc. (local) |
| `custom` | User-supplied module at `path:` | Any model with a compatible interface |

### Charter Configuration

```yaml
model:
  provider: claude          # selects the provider
  id: claude-opus-4-6       # model ID within that provider
  options:
    max_tokens: 16000
    temperature: 0          # deterministic for coding tasks
```

For a local Ollama model:

```yaml
model:
  provider: ollama
  id: qwen2.5-coder:32b
  options:
    base_url: http://localhost:11434
```

For a custom provider:

```yaml
model:
  provider: custom
  path: ./providers/my-provider.ts   # must export default class implementing ModelProvider
  id: my-model-v1
```

### Tool Use Compatibility

Not all providers support structured tool use. The Runner checks `provider.supportsTools()` and falls back to a prompt-based tool simulation layer for providers that do not (primarily useful for Ollama models).

### Embeddings Provider (for Memory + Skills retrieval)

Separate from the chat model, the memory system needs an embeddings model:

```yaml
# .loguetown/project.yaml
embeddings:
  provider: local           # local | openai | custom
  # local: uses @xenova/transformers with all-MiniLM-L6-v2 (23MB, no API key)
  # openai: uses text-embedding-3-small via OpenAI API
  model: all-MiniLM-L6-v2
  dimensions: 384
```

The default `local` embeddings provider runs entirely on-device using `@xenova/transformers` — no API key, no network required, ~23MB model download on first use.

---

## Data Model (SQLite)

```sql
-- Projects
CREATE TABLE projects (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  repo_path    TEXT NOT NULL,
  default_branch TEXT NOT NULL DEFAULT 'main',
  config_json  TEXT,          -- check commands, ignore patterns, path routing
  created_at   TEXT NOT NULL
);

-- Plans (one per lt run invocation)
CREATE TABLE plans (
  id                   TEXT PRIMARY KEY,
  project_id           TEXT NOT NULL REFERENCES projects(id),
  objective            TEXT NOT NULL,
  status               TEXT NOT NULL DEFAULT 'draft', -- draft|running|done|failed
  integration_branch   TEXT,    -- set if plan uses an integration branch
  integration_base     TEXT,    -- base branch for final land (default: project.default_branch)
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
  deps_json    TEXT,          -- JSON array of task IDs
  labels_json  TEXT,          -- skill tags, risk tags
  acceptance_json TEXT,       -- structured acceptance criteria
  risk_notes   TEXT,
  created_at   TEXT NOT NULL
);

-- Runs (one per agent invocation on a task)
CREATE TABLE runs (
  id           TEXT PRIMARY KEY,
  task_id      TEXT NOT NULL REFERENCES tasks(id),
  role         TEXT NOT NULL, -- planner|implementer|reviewer|fixer
  status       TEXT NOT NULL DEFAULT 'queued', -- queued|running|succeeded|failed|canceled
  attempt      INTEGER NOT NULL DEFAULT 1,
  agent_name   TEXT,
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

-- Memory chunks (one row per .md file; embeddings stored in sqlite-vec virtual table)
CREATE TABLE memory_chunks (
  id               TEXT PRIMARY KEY,
  agent_name       TEXT NOT NULL,
  layer            TEXT NOT NULL,  -- episodic|semantic_local|semantic_global
  project_id       TEXT,            -- NULL for semantic_global
  file_path        TEXT NOT NULL,   -- relative path to the .md file on disk
  title            TEXT,            -- first H2 heading or frontmatter title
  tags_json        TEXT,            -- JSON array of tags
  outcome          TEXT,            -- episodic only: success|failure|warning
  status           TEXT NOT NULL DEFAULT 'proposed', -- proposed|approved|promoted|rejected|deprecated
  rejection_reason TEXT,
  provenance_json  TEXT,            -- {run_id, task_id, commit_sha}
  last_validated_at TEXT,
  created_at       TEXT NOT NULL
);
CREATE INDEX idx_memory_agent   ON memory_chunks(agent_name);
CREATE INDEX idx_memory_layer   ON memory_chunks(layer);
CREATE INDEX idx_memory_project ON memory_chunks(project_id);
CREATE INDEX idx_memory_status  ON memory_chunks(status);

-- Skill file index (for vector search over .md skill files)
CREATE TABLE skill_files (
  id          TEXT PRIMARY KEY,
  role        TEXT NOT NULL,
  file_path   TEXT NOT NULL,   -- relative path within .loguetown/skills/
  title       TEXT,
  tags_json   TEXT,
  created_at  TEXT NOT NULL
);

-- Conversations (one per chat session: orchestrator or agent)
CREATE TABLE conversations (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id),
  participant  TEXT NOT NULL,  -- "orchestrator" or agent name (e.g. "charlie")
  title        TEXT,           -- optional label set by human
  created_at   TEXT NOT NULL,
  last_turn_at TEXT
);

-- Individual turns in a conversation
CREATE TABLE conversation_turns (
  id              TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  role            TEXT NOT NULL,  -- "human" | "assistant"
  content         TEXT NOT NULL,  -- message text
  plan_id         TEXT,           -- linked plan if the turn was about a specific plan
  task_id         TEXT,           -- linked task if the turn was about a specific task
  run_id          TEXT,           -- linked run if the turn was about a specific run
  created_at      TEXT NOT NULL
);
CREATE INDEX idx_conv_turns_conv ON conversation_turns(conversation_id);

-- Escalations (created when tasks require human attention beyond needs-human)
CREATE TABLE escalations (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id),
  task_id      TEXT REFERENCES tasks(id),
  run_id       TEXT REFERENCES runs(id),
  severity     INTEGER NOT NULL DEFAULT 1,  -- 1=warn, 2=error, 3=critical
  reason       TEXT NOT NULL,               -- human-readable summary
  status       TEXT NOT NULL DEFAULT 'open', -- open|acknowledged|resolved
  auto_bump_after_minutes INTEGER,          -- bump severity after this many minutes if unacknowledged
  created_at   TEXT NOT NULL,
  bumped_at    TEXT,
  resolved_at  TEXT
);
CREATE INDEX idx_esc_status ON escalations(status);

-- Vector embeddings stored via sqlite-vec extension
-- (virtual table created at runtime; shown here for reference)
-- CREATE VIRTUAL TABLE vec_memory USING vec0(embedding FLOAT[384]);
-- CREATE VIRTUAL TABLE vec_skills USING vec0(embedding FLOAT[384]);

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
CREATE INDEX idx_chronicle_task   ON chronicle(task_id);
CREATE INDEX idx_chronicle_run    ON chronicle(run_id);
CREATE INDEX idx_chronicle_type   ON chronicle(event_type);
CREATE INDEX idx_chronicle_ts     ON chronicle(ts);
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
  Runner: Planner session
    • loads planner Charter + skill bundle + memory
    • reads repo structure
    • outputs DAG: tasks T1…T6 with deps + acceptance criteria
         │
         ▼
  Daemon persists tasks, emits PLAN_CREATED + N×TASK_CREATED
         │
         ▼
  Scheduler Loop:
    finds unblocked tasks → spawns Implementer Runners (up to max_parallel)
         │
    ┌────┴────────────────────────────────────┐
    ▼                                         ▼
  Runner: Implementer (charlie) on T1      Runner: Implementer (diana) on T4
    • worktree created                       • worktree created
    • commits code                           • commits code
    • format → lint → typecheck → test_fast  • checks pass
    • all pass → requests review             • requests review
    • emits REVIEW_REQUESTED                 • emits REVIEW_REQUESTED
         │                                         │
         ▼                                         ▼
  Runner: Reviewer on T1 diff              Runner: Reviewer on T4 diff
    • REVIEW_RESULT: 1 blocking finding      • REVIEW_RESULT: no blockers
         │                                         │
         ▼                                         ▼
  Scheduler: spawn Fixer                   Merge gate: AWAITING_HUMAN
    • Fixer fixes blocker
    • re-runs checks (all pass)
    • Reviewer re-reviews: no blockers
    • Merge gate: AWAITING_HUMAN
         │
         ▼
  GUI: both T1 and T4 show "Ready for approval"
  Human clicks "Approve & merge" for T1, then T4
         │
         ▼
  Daemon: merge T1 branch → main (squash)
           emit MERGE_PERFORMED
           cleanup worktree
           mark T1 done
           → T2, T3 become unblocked
           → Scheduler spawns Implementers for T2, T3
         ...
```
