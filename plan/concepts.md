# Strawpot — Core Concepts

## Agent Charter

An **Agent Charter** is a hot-reloadable YAML file that is the single source of truth for an agent's identity, role, instructions, model, and allowed tools. Editing it takes effect on the agent's next session — no restart of the daemon required.

```yaml
# .strawpot/agents/charlie.yaml
name: charlie
role: implementer               # inherits defaults from .strawpot/roles/implementer.yaml

model:
  provider: claude              # claude | openai | ollama | custom
  id: claude-opus-4-6

tools:
  allowed: [read, write, bash]
  bash_allowlist:
    - "npm *"
    - "git *"
    - "npx tsc *"
    - "npx eslint *"
```

Charters reference a **Role** (which supplies default tool policy and model) and can override or extend any field. This keeps agent identity separate from capability definitions.

---

## Skills

Skills are **folder-based modules** — each skill is a directory containing one or more Markdown files. A skill directory teaches the agent one capability, convention, or workflow area. The agent reads skills using its native `Glob` and `Read` tools, then synthesises the applicable guidelines into a `CLAUDE.md` file that Claude Code auto-loads on subsequent sessions.

### Skill Scopes

Skills exist at three scopes, resolved from broadest to narrowest:

| Scope | Location | Includes |
|---|---|---|
| **Global** | `~/.strawpot/skills/` | Global only. Cross-project, developer-wide conventions. Applies in every project. |
| **Project** | `.strawpot/skills/` | Global + Project. Shared across all agents in this project (e.g. commit style, architecture overview). |
| **Agent** | `.strawpot/skills/<agent-name>/` | Global + Project + Agent. Full skill set for a specific agent instance. |

Scopes are cumulative: an agent session sees all three pools. The `lt skills list` command follows the same convention — default shows global + project, `--agent <name>` shows all three.

### Directory Structure

Each scope is a flat directory of skill sub-folders. Each sub-folder is one skill module:

```
~/.strawpot/skills/
  personal-coding-style/       # global: applies to all projects
    style.md
    examples/
  security-baseline/           # global: OWASP + auth conventions
    checklist.md

.strawpot/skills/
  project-overview/            # project-wide: high-level architecture
    architecture.md
    monorepo-layout.md
  commit-conventions/          # project-wide: commit style guide
    guide.md

.strawpot/skills/charlie/     # agent-specific (charlie)
  typescript-patterns/
    patterns.md
    examples/
  testing-conventions/
    guide.md
  react-patterns/
    hooks.md
    components.md
```

### Session Start: CLAUDE.md Generation

At session start `lt prime` injects the three skill pool paths and instructs the agent to:

1. Use `Glob` and `Read` to explore each skill pool directory
2. Identify modules relevant to the current task and role
3. Synthesise the applicable guidelines into `CLAUDE.md` in the working directory
4. Claude Code auto-loads `CLAUDE.md` in all future sessions — no re-reading required

This avoids front-loading context: the first session does the discovery work; subsequent sessions get the synthesised result automatically.

### Skill Module Format

Each skill module is a directory. No required file structure — the agent reads whatever Markdown files are present:

```
.strawpot/skills/charlie/typescript-patterns/
  patterns.md        # main content
  examples/          # optional sub-directory with code examples
  anti-patterns.md   # additional content files
```

**CLI:** `lt skills list` shows all skill modules across scopes. `lt skills install` scaffolds a new skill module directory (default: project scope; `--global` / `--agent <name>` for other scopes). `lt skills remove` deletes a module.

---

## Roles

A **Role** is a named, reusable configuration template stored in `.strawpot/roles/{name}.yaml`. Agents are instances of roles — a role defines defaults (skills, tools, model), an agent Charter can override any of them.

Roles are fully user-manageable: create `documenter.yaml`, `security-auditor.yaml`, `migration-writer.yaml`, etc. Built-in roles ship with Strawpot but can be overridden.

```yaml
# .strawpot/roles/implementer.yaml
name: implementer
description: "Writes code to implement features and fix bugs"

default_tools:
  allowed: [read, write, bash]
  bash_allowlist: ["npm *", "git *", "npx tsc *", "npx eslint *"]

default_model:
  provider: claude
  id: claude-opus-4-6
```

**Built-in roles:**

| Role | What it does | Output |
|---|---|---|
| **planner** | Decomposes objective into a DAG of tasks | Tasks with deps, acceptance criteria, risk notes |
| **implementer** | Executes one task in an isolated worktree | Commits + test updates + check pass |
| **reviewer** | Reviews diff against acceptance criteria | Structured review: blockers, risk score, required changes |
| **fixer** | Fixes failing checks or review blockers | Minimal changes to satisfy the merge gate |
| **documenter** | Writes/updates docs, changelogs, READMEs | Doc patches, changelog entries |

Add any role by creating a YAML file in `.strawpot/roles/`. The Planner can assign any defined role to tasks it creates.

---

---

## Orchestrator

The **Orchestrator** is the primary entry point for multi-agent workflows. It is a **session-based conversational agent** — not a polling daemon. The human talks to it in natural language; it plans, delegates, monitors, and reports back — all within a persistent conversation.

### Chat-First Design

```
lt chat              # opens (or resumes) an orchestrator session
lt chat --new        # force-start a fresh conversation
```

The Orchestrator is always available as a conversation partner. A session persists across multiple human turns and multiple agent runs. The human can describe a goal, ask for status, redirect work, approve proposals, or just ask questions — all without leaving the conversation.

### What the Orchestrator Does

| Human says | Orchestrator does |
|---|---|
| *"Add OAuth login with Google and GitHub"* | Proposes a task DAG, waits for approval, then queues runs |
| *"Why is T3 blocked?"* | Queries Chronicle + SQLite, explains the blocker |
| *"Add a task for rate limiting the auth endpoint"* | Creates a new task in the current plan and schedules it |
| *"Stop everything, something is broken"* | Pauses all active runners, emits RUN_CANCELED events |
| *"What did charlie do today?"* | Summarizes chronicle events for that agent |
| *"Approve T4"* | Triggers the merge gate for task T4 |

### Orchestrator Session Model

```
Conversation
  │  (persisted in conversations + conversation_turns tables)
  │
  ├── Turn 1: human "Add OAuth login"
  ├── Turn 2: orchestrator proposes DAG (shown inline, requires confirmation)
  ├── Turn 3: human "looks good, go"
  ├── Turn 4: orchestrator queues runs, reports "Running T1 with charlie..."
  ├── Turn 5: (async) "T1 done. T2 queued. Reviewer found 1 blocker — want me to fix?"
  ├── Turn 6: human "yes"
  └── Turn 7: orchestrator spawns fixer, eventually reports merge complete
```

The underlying **scheduler** runs as an asyncio task, driven by the Orchestrator's decisions rather than a standalone poll loop. The Orchestrator:

1. Receives human goals via conversation
2. Invokes the Planner agent to decompose goals into tasks (or accepts the human's manual task descriptions)
3. Queues and monitors runs via the scheduler
4. Reports status updates back into the conversation as async turns
5. Escalates blockers by asking the human inline rather than creating a separate escalation record

### Orchestrator Tools

During a conversation turn the Orchestrator can call internal tools (not exposed to individual agents):

| Tool | What it does |
|---|---|
| `create_plan(objective)` | Runs the Planner agent, creates plan + tasks in SQLite |
| `queue_run(task_id, agent_name)` | Spawns a Runner for the given task |
| `get_status(plan_id?)` | Returns a summary of all task statuses |
| `get_chronicle(task_id)` | Returns recent events for a task |
| `approve_task(task_id)` | Clears the merge gate for a task |
| `pause_all()` / `resume_all()` | Stops or resumes all active runners |

### Relationship to CLI Commands

`lt run`, `lt plan`, `lt tasks`, `lt agent spawn` all remain as **direct CLI entry points** for scripting and automation. The Orchestrator chat is the *human-facing* interface that calls the same underlying operations. Both paths write to the same SQLite state and emit the same Chronicle events.

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

For large plans where multiple tasks should be reviewed together before landing on `main`, Strawpot supports an optional **integration branch** — a staging branch that task branches merge into, with a single final land to `main`.

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
# .strawpot/project.yaml
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
