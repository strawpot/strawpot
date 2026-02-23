# Loguetown — Runtime

## Git / Worktree Strategy

Each Implementer or Fixer run gets an isolated git worktree. This allows parallel agents to work on separate tasks without file system conflicts.

**Worktree root:** `data/projects/{project_id}/worktrees/{run_id}/`

**Branch naming:** `lt/{plan_id}/{task_id}/a{attempt}`
(e.g., `lt/pl-abc12/tk-xyz34/a1`)

**Lifecycle:**
```
git worktree add <path> -b <branch> <base_sha>
  → agent commits work
  → checks run inside worktree
  → human approves
  → merge to base branch
  → git worktree remove <path>
  → git branch -d <branch>
```

**Merge strategies** (user-configurable per project):
- `squash` (default — clean history for solo dev)
- `ff` (fast-forward, preserves commits)
- `rebase` *(v1.1)*

**Concurrency guard:** Worktree paths are keyed on `run_id` (UUID), so two simultaneous runs never share a path. The daemon owns worktree creation/cleanup, never the agent itself.

**Integration branch flow:** When a plan sets `integration_branch.enabled = true`, the daemon creates `integration/{plan_id}` from the base branch before any tasks start. All task worktrees are created from this integration branch (not from `main`). Each task merges into the integration branch. The `lt plan land` command runs the full check suite against the integration branch and merges it to `main` in a single commit, then cleans up the integration branch and all task worktrees.

---

## Check Pipelines

Each project declares its check commands in `.loguetown/project.yaml`:

```yaml
# .loguetown/project.yaml
checks:
  setup:
    run: "npm ci"
    cache_key: "package-lock.json"

  format:
    run: "npx prettier --check ."
    on_fail: warn              # warn | block (default block)

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
    retry_on_flake: 1          # retry flaky tests once

path_routing:
  docs_only:
    patterns: ["docs/**", "*.md"]
    skip: [lint, typecheck, test_fast, test_full]
```

**Runner execution order per task:**

```
after each agent commit:   format → lint → typecheck → test_fast
before requesting review:  test_full
before merge gate:         full suite must be green
```

All command invocations emit `COMMAND_STARTED` / `COMMAND_FINISHED` events with stdout/stderr artifacts stored to disk. The GUI can show full command output from any run.

---

## Orchestration and Scheduling

### 8.1 Planner Output → DAG

The Planner creates tasks with:
- Dependency list (DAG edges)
- Suggested role (implementer, reviewer)
- Acceptance criteria (structured)
- Risk notes (paths touched, complexity estimate)
- Required skill labels

The daemon persists tasks in SQLite and renders the DAG in the GUI.

### 8.2 Scheduler Loop

```
loop every N seconds:
  1. Find unblocked tasks (status=todo AND all deps done)
  2. If running_count < max_parallel_runs:
       pick next unblocked task
       create Run record (role=implementer, attempt=1)
       emit RUN_QUEUED event
       spawn Runner subprocess

  3. For each Run that succeeded + checks passed:
       create Run record (role=reviewer)
       emit RUN_QUEUED event
       spawn Reviewer Runner

  4. For each Reviewer Run with blockers:
       if attempt < max_fix_attempts:
         create Run record (role=fixer, attempt=N+1)
         spawn Fixer Runner
       else:
         set task status=needs-human
         create failure summary artifact
         emit TASK_STATE_CHANGED

  5. For each Reviewer Run with no blockers:
       set task status=reviewing → awaiting-approval
       emit MERGE_GATE_PASSED
```

### 8.3 Retry Policy (Bounded)

| Config key | Default | Description |
|---|---|---|
| `max_fix_attempts` | 3 | Max Fixer runs per task before escalating to human |
| `max_parallel_runs` | 3 | Max concurrent Runner subprocesses on this machine |
| `stale_run_timeout_minutes` | 20 | Kill and requeue a run that goes silent |

After exceeding `max_fix_attempts`, the task becomes `needs-human` and the daemon creates a **failure summary artifact** (last logs + diff + review findings) for the human to inspect.

### 8.4 Patrol Loop (Health Monitor)

The daemon runs a lightweight **patrol loop** every `patrol_interval_seconds` (default: 60) alongside the scheduler loop. The patrol loop is not an AI agent — it is a deterministic state machine:

```
patrol loop every 60s:
  1. Find runs with status=running older than stale_run_timeout_minutes
     → kill process, emit RUN_CANCELED, requeue (attempt+1) or set needs-human

  2. Find tasks with status=needs-human
     → if no open escalation for this task: create Escalation (severity=2)
     → if existing escalation and auto_bump timer expired: bump severity, re-notify

  3. Count tasks with status=needs-human
     → if count >= critical_task_threshold: ensure severity=3 escalation exists

  4. Find open escalations (status='open') where time since created_at (or bumped_at) > auto_bump_after_minutes
     → bump severity, emit ESCALATION_BUMPED, fire configured notification channels

  5. Send desktop/webhook notifications for new severity=3 escalations
     (lower severity notifications are batched and sent once per patrol cycle)
```

The patrol loop is the only component that fires notifications. Runners and the scheduler only update state; the patrol loop observes state and acts on it. This separation keeps agent code simple and avoids double-notification races.

---

## Merge Gate (Configurable Approval Policy)

A task passes the merge gate only when **all structural gates** are satisfied, after which the **approval policy** determines whether a merge happens automatically or waits for human sign-off.

### Structural Gates (always required)

| Gate | Condition |
|---|---|
| Checks | All required check commands exit 0 |
| Review | Reviewer result has zero `blocking` findings |
| Risk policy | No restricted paths violated (configurable per project) |

### Approval Policies

| Policy | Behavior |
|---|---|
| `require_human` | Task waits in `awaiting-approval` state until a human explicitly approves via `lt tasks approve` or the GUI. **Default.** |
| `auto` | Daemon merges automatically as soon as all structural gates pass. No human action required. |
| `risk_based` | Auto-merge if `risk_score ≤ auto_merge_max_risk_score` (set in project config). Escalates to `awaiting-approval` otherwise. |

Set the policy per project in `.loguetown/project.yaml`:

```yaml
merge:
  approval_policy: risk_based         # require_human | auto | risk_based
  auto_merge_max_risk_score: 0.3      # only for risk_based; 0.0–1.0
  strategy: squash
  require_checks: [lint, typecheck, test_full]
  require_review: true
  restricted_paths: ["db/migrations/**", "src/auth/**"]
```

`restricted_paths` forces `require_human` regardless of the policy for any diff that touches those paths.

### Merge Execution

When the gate is cleared (either by human approval or auto-policy), the daemon:

1. Emits `HUMAN_APPROVED` (for `require_human` / `risk_based` w/ human action) or `AUTO_MERGE_TRIGGERED`
2. Performs the merge using the configured strategy (`squash` by default)
3. Emits `MERGE_PERFORMED` with strategy, base_sha, head_sha, merge_sha
4. Stores the final diff snapshot artifact
5. Cleans up the worktree and branch
6. Marks the task `done`

Human rejection resets the task to `needs-human`. Provide a comment via `lt tasks reject <id> --comment "..."` or via the GUI Merge Gate screen. The rejection comment is stored in the Chronicle and shown to the Fixer on the next attempt.

---

## Security and Safety

Even local-only, the system needs guardrails to prevent runaway agent behavior:

| Concern | Mitigation |
|---|---|
| Arbitrary command execution | `bash_allowlist` in Charter; Runner validates each command against allowlist before executing |
| File system escape | Runner validates all file paths are within worktree root |
| Secret leakage in logs | Basic secret redaction heuristics (regex for tokens, passwords, API keys) in Chronicle writer |
| Network access | Optional `no_network: true` toggle in Charter; Runner sets `NODE_NET=off` via env |
| Runaway agent | `stale_run_timeout_minutes` kills and requeuees silently-hanging Runners |
| Concurrent worktree conflict | Worktree path keyed on UUID run_id; daemon is sole creator/destroyer of worktrees |
| Malformed A2A messages | Daemon validates all messages against TypeScript schemas before routing; invalid messages are rejected and logged |
