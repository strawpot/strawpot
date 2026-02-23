# Loguetown — Core Concepts

## Agent Charter

An **Agent Charter** is a hot-reloadable YAML file that is the single source of truth for an agent's identity, role, skill bundle, memory settings, model, and allowed tools. Editing it takes effect on the agent's next session — no restart of the daemon required.

```yaml
# .loguetown/agents/charlie.yaml
name: charlie
role: implementer               # inherits defaults from .loguetown/roles/implementer.yaml

model:
  provider: claude              # claude | openai | ollama | custom
  id: claude-opus-4-6

extra_skills:                   # files to load in addition to the role's default_skills
  - implementer/react-patterns.md

memory:
  layers: [working, episodic, semantic_local, semantic_global]
  provider: local               # local | mem0 | custom
  max_tokens_injected: 8000
  budget:
    skills_pct: 25              # % of budget for skill files
    episodic_pct: 25            # % of budget for past-run experiences
    semantic_local_pct: 35      # % of budget for project-scoped facts
    semantic_global_pct: 15     # % of budget for cross-project facts

tools:
  allowed: [read, write, bash]
  bash_allowlist:
    - "npm *"
    - "git *"
    - "npx tsc *"
    - "npx eslint *"
```

Charters reference a **Role** (which supplies default skills, tool policy, and model) and can override or extend any field. This keeps agent identity separate from capability definitions.

---

## Skills

Skills are plain **Markdown files** (`*.md`). Each file teaches the agent one specific capability, convention, or pattern. Files are small and independently retrievable via vector search — avoiding the "one giant CLAUDE.md" anti-pattern.

```
.loguetown/skills/
  implementer/
    typescript-patterns.md      # language conventions and idioms
    testing-conventions.md      # how to write tests in this codebase
    git-workflow.md             # commit style, branch rules, PR process
    api-design.md               # REST/GraphQL conventions
    react-patterns.md           # (example extra skill for a specific agent)
  reviewer/
    code-review-checklist.md    # what a thorough review checks
    security-checklist.md       # OWASP top 10, injection, auth issues
    performance-checklist.md    # DB queries, bundle size, rendering
  documenter/
    api-docs-style.md
    changelog-format.md
    readme-template.md
  planner/
    decomposition-heuristics.md
    risk-scoring.md
  fixer/
    debugging-strategies.md
    minimal-change-principle.md
  shared/                       # available to ALL roles
    commit-style.md
    project-overview.md         # high-level architecture (human-maintained)
    monorepo-layout.md
```

**Skill file format** — pure Markdown, no required frontmatter. Optional frontmatter enables better indexing:

```markdown
---
id: sk_typescript_patterns
role: implementer
tags: [typescript, patterns, style]
---

# TypeScript Patterns

## Error Handling
Always use typed errors. Extend the base `AppError` class in `src/errors/base.ts`...

## Async/Await
Prefer async/await over raw Promise chains. Always handle rejections...
```

At session start the Runner embeds each skill file (once, cached) and retrieves the **top-K most relevant** to the current task via vector similarity search, within the skills token budget. If the role has few skills and all fit in budget, all are loaded.

---

## Roles

A **Role** is a named, reusable configuration template stored in `.loguetown/roles/{name}.yaml`. Agents are instances of roles — a role defines defaults (skills, tools, model), an agent Charter can override any of them.

Roles are fully user-manageable: create `documenter.yaml`, `security-auditor.yaml`, `migration-writer.yaml`, etc. Built-in roles ship with Loguetown but can be overridden.

```yaml
# .loguetown/roles/implementer.yaml
name: implementer
description: "Writes code to implement features and fix bugs"

default_skills:
  - implementer/typescript-patterns.md
  - implementer/testing-conventions.md
  - implementer/git-workflow.md
  - shared/commit-style.md

default_tools:
  allowed: [read, write, bash]
  bash_allowlist: ["npm *", "git *", "npx tsc *", "npx eslint *"]

default_model:
  provider: claude
  id: claude-opus-4-6

default_memory:
  layers: [working, episodic, semantic_local, semantic_global]
  max_tokens_injected: 8000
```

**Built-in roles:**

| Role | What it does | Output |
|---|---|---|
| **planner** | Decomposes objective into a DAG of tasks | Tasks with deps, acceptance criteria, risk notes |
| **implementer** | Executes one task in an isolated worktree | Commits + test updates + check pass |
| **reviewer** | Reviews diff against acceptance criteria | Structured review: blockers, risk score, required changes |
| **fixer** | Fixes failing checks or review blockers | Minimal changes to satisfy the merge gate |
| **documenter** | Writes/updates docs, changelogs, READMEs | Doc patches, changelog entries |

Add any role by creating a YAML file in `.loguetown/roles/`. The Planner can assign any defined role to tasks it creates.

---

## Memory

Memory is composed of **multiple layers** with different lifetimes, scopes, and retrieval strategies. Each layer is stored as **individual Markdown chunk files** — not one monolithic file — enabling targeted vector search retrieval.

### Memory Layers

| Layer | Name | Scope | Lifetime | Purpose |
|---|---|---|---|---|
| 0 | **Working** | Session | Cleared at session end | In-context scratchpad; active observations and reasoning |
| 1 | **Episodic** | Agent | Configurable (e.g. 90 days / 100 entries) | Past run experiences: what happened, what worked, what to avoid |
| 2 | **Semantic Local** | Project | Until deprecated | Project facts: conventions, architecture decisions, known patterns |
| 3 | **Semantic Global** | Cross-project | Until deprecated | Personal standards, reusable patterns, tool preferences |
| 4 | **Skills** | Role | Managed separately | How-to knowledge (see Skills section above) |

Layers 1–3 are each stored as many small `.md` chunk files, independently embedded and searchable. The Working layer is in-context only.

### Memory Chunk Format

Each chunk is a single `.md` file with optional YAML frontmatter:

```markdown
---
id: mem_abc123
layer: episodic
agent: charlie
project: my-service      # null for global
tags: [auth, oauth, csrf]
outcome: failure         # episodic: success | failure | warning
provenance:
  task_id: tk-xyz34
  run_id: run-456
  commit: abc123f
created_at: 2025-01-15T14:23:00Z
last_validated_at: 2025-01-15T14:23:00Z
status: active           # active | deprecated
---

## Mistake: not validating OAuth state parameter

When implementing the OAuth callback I forgot to validate `req.query.state` against
`req.session.oauthState` before calling the token exchange endpoint. This introduced
a CSRF vulnerability.

**What to do instead:**
- Always verify `state` matches the stored session value before token exchange
- Return 400 if state is missing or mismatched
- Clear state from session after successful validation
```

Semantic chunk example:

```markdown
---
id: mem_def456
layer: semantic_local
project: my-service
tags: [auth, architecture, jwt]
status: active
---

## JWT token strategy

Tokens are issued by `POST /auth/login`. Access tokens expire in 15 minutes,
refresh tokens in 7 days. Tokens are stored in httpOnly cookies, never
localStorage. Validation middleware lives in `src/middleware/auth.ts`.
```

### File Layout

```
.loguetown/memory/
  charlie/
    episodic/
      2025-01-15-oauth-state-csrf.md
      2025-01-20-db-migration-rollback.md
    semantic_local/
      my-service/
        auth-architecture.md
        db-schema-conventions.md
        api-error-format.md
    semantic_global/
      typescript-preferences.md
      testing-philosophy.md

~/.loguetown/memory/
  charlie/
    semantic_global/             # symlinked or separate global store
```

### Retrieval at Session Start

The Runner performs **vector similarity search** for each active layer:

```
query = current task description + role name + project name

for each active layer:
  retrieve top-K chunks where similarity(chunk.embedding, query) > threshold
  sort by similarity DESC, recency DESC
  apply layer token budget

inject into system prompt in order: global semantic → local semantic → episodic → skills
```

This ensures the agent receives the most relevant knowledge for *this specific task*, not a dump of everything it has ever learned.

### Memory Promotion Lifecycle

Agents cannot directly write to promoted layers — all writes are proposals:

```
proposed ──► approved ──► promoted (active, retrievable)
              │
              └──► rejected (with reason, stored but not retrieved)

promoted ──► deprecated (invalidated by later changes, excluded from retrieval)
```

- **Any agent** can *propose* episodic, semantic-local, or semantic-global chunks during a run
- **Reviewer** *approves or rejects* proposed chunks (with structured reasons)
- **Human** can override: promote rejected entries or deprecate stale ones from the GUI

### Episodic Memory — Learning from Mistakes

Episodic memory is the "don't do this again" layer. After each run completes (success or failure), the daemon prompts the active agent:

> *"What did you learn from this run that future agents should know? Any mistakes made, patterns discovered, or decisions that should be remembered?"*

The agent writes one or more episodic chunks tagged with `outcome: success | failure | warning`. These are proposed, approved by the Reviewer, and then retrievable in future sessions when a similar task is encountered.

Episodic entries have a configurable **retention policy** (default: keep the 100 most recent, or entries within 90 days — whichever is larger).

### Memory Provider Abstraction

The local Markdown + vector-search implementation is the default, but the memory system is pluggable:

```typescript
interface MemoryProvider {
  store(chunk: MemoryChunk): Promise<void>;
  retrieve(query: MemoryQuery): Promise<MemoryChunk[]>;
  update(id: string, updates: Partial<MemoryChunk>): Promise<void>;
  delete(id: string): Promise<void>;
  list(filter?: MemoryFilter): Promise<MemoryChunk[]>;
}

interface MemoryQuery {
  text: string;           // natural language query for vector search
  layer?: MemoryLayer[];  // filter to specific layers
  agent?: string;
  project?: string;
  tags?: string[];
  limit?: number;
  min_similarity?: number;
}
```

**Built-in providers:**

| Provider | Description | Config |
|---|---|---|
| `local` | Markdown files + sqlite-vec embeddings. Zero-infra, default. | `provider: local` |
| `mem0` | [Mem0](https://mem0.ai) managed memory service (cloud or self-hosted) | `provider: mem0` + API key |
| `custom` | Any class implementing `MemoryProvider` | `provider: custom`, `path: ./my-provider.ts` |

Custom providers are loaded by path. This enables integration with any external memory system (LangMem, Zep, Weaviate, Pinecone, etc.).

---

## Task

A **Task** is a local record (SQLite) representing one atomic unit of work in a plan.

```
Task:
  id, plan_id
  title, description
  status: todo | running | blocked | reviewing | done | failed | needs-human
  deps: [task_id, ...]          # dependency IDs (must be done before this starts)
  labels: [skill-tag, risk-tag] # used for skill matching
  acceptance: {                 # structured acceptance criteria
    tests_required: true,
    behaviors: ["..."],
    files_touched: ["src/auth/*"]
  }
  risk_notes: "..."
```

In v1.2+, tasks can optionally sync to GitHub Issues (one-way or bidirectional).

---

## Integration Branch (Optional)

For large plans where multiple tasks should be reviewed together before landing on `main`, Loguetown supports an optional **integration branch** — a staging branch that task branches merge into, with a single final land to `main`.

**When to use it:** Enable this on Plans that touch multiple subsystems or have high inter-task dependency. Disabled by default; most small plans merge each task to `main` individually.

```yaml
# Set at plan-creation time (lt run) or specified in a template
integration_branch:
  enabled: true
  name: "integration/auth-overhaul"   # auto-generated if omitted: integration/{plan_id}
  base: main                          # final target branch
  auto_land: false                    # auto-land when all tasks are done (default: false)
```

**Lifecycle:**

```
Plan created with integration_branch.enabled = true
  │
  ├─ Daemon creates integration branch from base
  │
  ├─ All task branches use integration branch as their base and merge target
  │     (branch naming: lt/{plan_id}/{task_id}/a{attempt}  →  base: integration/{plan_id})
  │
  ├─ Each task merges into the integration branch after passing its own checks + review
  │
  ├─ When all tasks are done:
  │     Human runs: lt plan land   (or auto-land if enabled)
  │     Daemon runs full check suite on integration branch
  │     Daemon merges integration branch → base (squash or ff)
  │     Emits INTEGRATION_BRANCH_LANDED
  │
  └─ Daemon cleans up integration branch
```

The Planner is instructed to suggest integration branches for plans it judges to be large (risk score > threshold or task count > N).

---

## Dispatch (A2A Message Bus)

**Dispatch** is the agent-to-agent communication layer. The daemon validates all messages against typed schemas before routing. No free-form *"LGTM"* without a schema.

### Generic Message Envelope

```typescript
interface Message {
  id: string;
  type: MessageType;
  from: string;           // agent name
  to: string | string[];  // agent name(s) or channel
  subject: string;
  payload: TypedPayload;  // varies by type (see below)
  timestamp: string;
  replyTo?: string;       // threading
}
```

### Typed Payload Schemas (Agent-Domain)

**REQUEST_REVIEW** — Implementer → Reviewer
```typescript
{
  type: 'REQUEST_REVIEW';
  branch: string;
  base_sha: string;
  head_sha: string;
  task_id: string;
  acceptance: AcceptanceCriteria;
  how_to_test: string[];   // commands to reproduce
  risk_notes: string;
}
```

**REVIEW_RESULT** — Reviewer → Implementer + Daemon
```typescript
{
  type: 'REVIEW_RESULT';
  blocking: Finding[];     // must fix before merge
  non_blocking: Finding[]; // suggestions
  required_changes: string[];
  risk_score: number;      // 0–1
  confidence: number;      // 0–1
}
```

**NEED_INFO** — any agent → any agent
```typescript
{
  type: 'NEED_INFO';
  questions: string[];
  attempted: string[];     // what the agent already tried
}
```

**TASK_UNBLOCKED** — Daemon → all agents (broadcast)
```typescript
{
  type: 'TASK_UNBLOCKED';
  task_ids: string[];
  reason: string;
}
```

All messages are persisted in SQLite (Dispatch inbox per agent) and written to the Chronicle.

---

## Chronicle (Trace System)

The **Chronicle** is the full audit record of everything that happens. It has two layers:

| Layer | Format | Role |
|---|---|---|
| **Event log** | Append-only JSONL per project | Canonical, immutable source of truth |
| **Event index** | SQLite table | Fast queryable index for GUI and CLI |

**JSONL path:** `data/projects/{project_id}/events.jsonl`

**Event envelope:**
```typescript
{
  id: string;          // uuid
  ts: string;          // ISO 8601
  project_id: string;
  plan_id?: string;
  task_id?: string;
  run_id?: string;
  actor: string;       // "human:<name>" | "agent:<role>/<name>" | "system"
  type: EventType;
  payload: object;     // typed per event type
}
```

### Core Event Types

| Category | Event Types |
|---|---|
| Plan/Task | `PLAN_CREATED` `TASK_CREATED` `TASK_STATE_CHANGED` |
| Run lifecycle | `RUN_QUEUED` `RUN_STARTED` `RUN_SUCCEEDED` `RUN_FAILED` `RUN_CANCELED` |
| Git/Worktree | `WORKTREE_CREATED` `BRANCH_CREATED` `COMMIT_CREATED` `DIFF_SNAPSHOT_SAVED` `MERGE_PERFORMED` `INTEGRATION_BRANCH_CREATED` `INTEGRATION_BRANCH_LANDED` |
| Escalation | `ESCALATION_CREATED` `ESCALATION_BUMPED` `ESCALATION_ACKNOWLEDGED` `ESCALATION_RESOLVED` |
| Agent comms | `AGENT_MESSAGE_SENT` `AGENT_MESSAGE_RECEIVED` `REVIEW_REQUESTED` `REVIEW_SUBMITTED` |
| Checks | `COMMAND_STARTED` `COMMAND_FINISHED` `CHECKS_STARTED` `CHECKS_FINISHED` |
| Memory | `MEMORY_PROPOSED` `MEMORY_APPROVED` `MEMORY_REJECTED` `MEMORY_PROMOTED` `MEMORY_DEPRECATED` |
| Human | `HUMAN_APPROVED` `HUMAN_REJECTED` `HUMAN_COMMENTED` |
| Merge | `MERGE_GATE_PASSED` `AUTO_MERGE_TRIGGERED` `MERGE_PERFORMED` |
| Chat | `CONVERSATION_TURN_HUMAN` `CONVERSATION_TURN_ASSISTANT` |

### Chronicle Trace Queries (GUI)

- Timeline by plan / task / run
- Filter by event type, actor, time range
- Jump from review finding → diff snapshot → command logs
- Provenance links: memory entry → commit → diff → checks → approval

---

## Escalation

An **Escalation** is a structured alert created when the system needs the developer's attention. It is more specific than `needs-human` (which is a task status) — it carries a severity, a reason, and an auto-bump timer.

### Severity Levels

| Level | Name | Meaning |
|---|---|---|
| 1 | `warn` | Agent stalled; action helpful but not urgent |
| 2 | `error` | Task blocked; plan cannot progress without intervention |
| 3 | `critical` | Multiple tasks blocked or all retries exhausted across the plan |

### When Escalations Are Created

| Trigger | Severity |
|---|---|
| Task reaches `needs-human` after exceeding `max_fix_attempts` | 2 (error) |
| Stale run killed and cannot be recovered automatically | 2 (error) |
| N tasks simultaneously `needs-human` (configurable threshold) | 3 (critical) |
| Integration branch has conflicts agents cannot resolve | 3 (critical) |

### Auto-Bump

If an escalation is not acknowledged within `auto_bump_after_minutes`, the daemon bumps its severity by 1 and emits `ESCALATION_BUMPED`. Configured per project:

```yaml
# .loguetown/project.yaml
escalation:
  auto_bump_after_minutes: 30    # bump severity if unacknowledged after this time
  critical_task_threshold: 3     # escalate to critical when ≥ N tasks need-human simultaneously
```

### Lifecycle

```
created (severity 1–3)
  → acknowledged (human saw it, auto-bump stops)
    → resolved (task unblocked or manually closed)
  OR
  → auto-bumped (severity+1 after timer, re-notifies)
```

Escalations appear as a persistent banner in the GUI Dashboard and as orange halos on affected task nodes in the Plan/DAG screen.
