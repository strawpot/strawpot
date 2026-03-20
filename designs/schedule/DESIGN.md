# Scheduled Tasks

## Problem

StrawPot users need automated, unattended agent sessions — both recurring (e.g.
daily code reviews) and one-off (e.g. "run this migration tonight at 2 AM").
Without scheduling, every session must be manually triggered.

## Goal

Provide a cron-based scheduling system for recurring tasks and a datetime-based
system for one-time tasks, with full GUI management and run-history tracking.

---

## Existing Design: Recurring Schedules

### Database Schema

Table `scheduled_tasks` in `gui/src/strawpot_gui/db.py`:

```sql
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role            TEXT,
    task            TEXT NOT NULL,
    cron_expr       TEXT,                                    -- nullable for one-time
    schedule_type   TEXT NOT NULL DEFAULT 'recurring',       -- 'recurring' | 'one_time'
    run_at          TEXT,                                    -- ISO datetime for one-time
    enabled         INTEGER NOT NULL DEFAULT 1,
    system_prompt   TEXT,
    skip_if_running INTEGER NOT NULL DEFAULT 1,
    last_run_at     TEXT,
    next_run_at     TEXT,
    last_error      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Sessions link back via `schedule_id` FK:

```sql
-- In sessions table:
schedule_id INTEGER REFERENCES scheduled_tasks(id) ON DELETE SET NULL
```

### Backend API

Router: `gui/src/strawpot_gui/routers/schedules.py`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/schedules` | List schedules (with `?type=recurring\|one_time` filter) |
| POST | `/api/schedules` | Create recurring schedule |
| POST | `/api/schedules/one-time` | Create one-time schedule |
| GET | `/api/schedules/runs` | List schedule-triggered sessions with metadata |
| GET | `/api/schedules/{id}` | Get single schedule |
| PUT | `/api/schedules/{id}` | Update schedule fields |
| DELETE | `/api/schedules/{id}` | Delete schedule |
| POST | `/api/schedules/{id}/enable` | Enable + compute next_run_at (one-time: reject past `run_at`) |
| POST | `/api/schedules/{id}/disable` | Disable + clear next_run_at |
| GET | `/api/schedules/{id}/history` | Sessions spawned by this schedule (max 50) |

Models:
- `ScheduleCreate`: name, project_id, task, cron_expr (validated via croniter),
  role, system_prompt, skip_if_running
- `OneTimeScheduleCreate`: name, project_id, task, run_at (ISO datetime, must be future),
  role, system_prompt
- `ScheduleUpdate`: all fields optional (including `run_at`)

### Scheduler Engine

File: `gui/src/strawpot_gui/scheduler.py`

- `Scheduler` class runs as asyncio background task in FastAPI lifespan
- Checks every 30 seconds for due schedules (`enabled=1 AND next_run_at <= now`)
- `skip_if_running` prevents concurrent sessions for the same schedule
- Recurring: after firing, computes `next_run_at` from `cron_expr` via croniter
- One-time: after firing, sets `enabled=0, next_run_at=NULL` (auto-disable)
- One-time skip-if-running: leaves `next_run_at` unchanged to retry next tick
- On launch failure, records error in `last_error`
- On startup, `_init_next_run_times()` fills `next_run_at` for enabled recurring
  schedules only (one-time schedules have `next_run_at` set at creation)

### Frontend

| File | Purpose |
|------|---------|
| `gui/frontend/src/pages/ScheduledTasks.tsx` | Recurring schedule list page |
| `gui/frontend/src/pages/OneTimeSchedules.tsx` | One-time schedule list page |
| `gui/frontend/src/pages/ScheduleRuns.tsx` | Aggregated run history page |
| `gui/frontend/src/components/CreateScheduleDialog.tsx` | Create/edit recurring dialog with cron presets |
| `gui/frontend/src/components/CreateOneTimeScheduleDialog.tsx` | Create one-time schedule dialog |
| `gui/frontend/src/hooks/queries/use-schedules.ts` | Query hooks (`useSchedules`, `useScheduleRuns`) |
| `gui/frontend/src/hooks/mutations/use-schedules.ts` | Mutation hooks (`useCreateSchedule`, `useCreateOneTimeSchedule`) |
| `gui/frontend/src/api/types.ts` | `Schedule`, `ScheduleRun` interfaces |

Routes: `/schedules/recurring`, `/schedules/one-time`, `/schedules/runs` in
`App.tsx`. Sidebar "Schedules" group with three sub-links in `AppLayout.tsx`.

### Tests

| File | Coverage |
|------|----------|
| `gui/tests/test_schedules.py` | CRUD API tests + one-time schedule + type filter + runs endpoint |
| `gui/tests/test_scheduler.py` | Scheduler engine tests + one-time auto-disable + skip-if-running |

---

## New Feature: One-Time Schedules + Run History Panel

### Problem

Users cannot schedule a task to run once at a specific future time. All
schedules require a cron expression and repeat indefinitely. There is also no
aggregated view of schedule-triggered runs across all schedules.

### Goal

1. One-time schedules that fire at a specific datetime and auto-disable
2. Separate GUI panel for one-time schedules (distinct from recurring)
3. Run history panel showing all schedule-triggered runs with status and
   session links

### Database Changes

File: `gui/src/strawpot_gui/db.py`

Add two columns and make `cron_expr` nullable:

```sql
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role            TEXT,
    task            TEXT NOT NULL,
    cron_expr       TEXT,                                    -- nullable for one-time
    schedule_type   TEXT NOT NULL DEFAULT 'recurring',       -- 'recurring' | 'one_time'
    run_at          TEXT,                                    -- ISO datetime for one-time
    enabled         INTEGER NOT NULL DEFAULT 1,
    system_prompt   TEXT,
    skip_if_running INTEGER NOT NULL DEFAULT 1,
    last_run_at     TEXT,
    next_run_at     TEXT,
    last_error      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Migration steps:
1. `ALTER TABLE` to add `schedule_type` and `run_at` columns
2. Rebuild table to make `cron_expr` nullable (SQLite cannot ALTER NOT NULL →
   nullable) — same pattern as the conversations AUTOINCREMENT migration

**Pitfall:** Must disable `foreign_keys` during table rebuild, otherwise
`DROP TABLE scheduled_tasks` cascades `ON DELETE SET NULL` to
`sessions.schedule_id`, wiping all schedule-session links.

### Backend API Changes

File: `gui/src/strawpot_gui/routers/schedules.py`

**New model:**

```python
class OneTimeScheduleCreate(BaseModel):
    name: str
    project_id: int
    task: str
    run_at: str  # ISO datetime, must be in the future
    role: str | None = None
    system_prompt: str | None = None
```

**Endpoint changes:**

| Change | Detail |
|--------|--------|
| `GET /api/schedules` | Add `?type=recurring\|one_time` query param filter |
| `POST /api/schedules/one-time` | New: create one-time schedule (`schedule_type='one_time'`, `cron_expr=NULL`, `next_run_at=run_at`) |
| `POST /api/schedules/{id}/enable` | For one-time: use `run_at` for `next_run_at`; reject 422 if `run_at` is in the past |
| `GET /api/schedules/runs` | New: sessions with non-null `schedule_id`, joined with schedule name/type, ordered by `started_at DESC`, limit 100 |
| `_row_to_dict` | Include `schedule_type` and `run_at` in output |

Update `ScheduleUpdate`: add optional `run_at` field.

### Scheduler Engine Changes

File: `gui/src/strawpot_gui/scheduler.py`

| Method | Change |
|--------|--------|
| `_init_next_run_times` | Add `AND schedule_type = 'recurring'` filter (one-time schedules already have `next_run_at` set from `run_at` at creation) |
| `_fire` | After launching: if `schedule_type == 'one_time'`, set `enabled=0, next_run_at=NULL` instead of computing next cron run |
| `_check_and_fire` | When `skip_if_running` triggers for one-time schedule, do NOT advance `next_run_at` (leave as-is to retry next tick) |

### Frontend Changes

#### Types

File: `gui/frontend/src/api/types.ts`

Update `Schedule` interface:

```typescript
export interface Schedule {
  id: number;
  name: string;
  project_id: number;
  project_name: string;
  role: string | null;
  task: string;
  cron_expr: string | null;                        // nullable for one-time
  schedule_type: 'recurring' | 'one_time';
  run_at: string | null;                            // ISO datetime for one-time
  enabled: boolean;
  system_prompt: string | null;
  skip_if_running: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  last_error: string | null;
  created_at: string;
}
```

Add `ScheduleRun` interface:

```typescript
export interface ScheduleRun {
  run_id: string;
  schedule_id: number;
  schedule_name: string;
  schedule_type: 'recurring' | 'one_time';
  project_id: number;
  project_name: string;
  role: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  exit_code: number | null;
  task: string | null;
}
```

#### Hooks

Files: `gui/frontend/src/hooks/queries/use-schedules.ts`,
`gui/frontend/src/hooks/mutations/use-schedules.ts`

- `useSchedules(type?)` — add optional type filter param
- `useScheduleRuns()` — new query hook for `GET /schedules/runs`
- `useCreateOneTimeSchedule()` — new mutation for `POST /schedules/one-time`

#### Routing & Navigation

File: `gui/frontend/src/App.tsx`

```tsx
<Route path="schedules" element={<Navigate to="/schedules/recurring" replace />} />
<Route path="schedules/recurring" element={<ScheduledTasks />} />
<Route path="schedules/one-time" element={<OneTimeSchedules />} />
<Route path="schedules/runs" element={<ScheduleRuns />} />
```

File: `gui/frontend/src/layouts/AppLayout.tsx`

Replace single "Schedules" sidebar entry with a group:
- Recurring (Clock icon)
- One-Time (CalendarClock icon)
- Run History (History icon)

Update breadcrumb logic for nested segments.

#### New Pages

**`OneTimeSchedules.tsx`** — similar to `ScheduledTasks.tsx` but:
- Calls `useSchedules('one_time')`
- Table columns: Name, Project, Scheduled For (`run_at`), Status
  ("Pending"/"Fired"/"Disabled")
- No cron column
- "Create" opens `CreateOneTimeScheduleDialog`

**`CreateOneTimeScheduleDialog.tsx`** — based on `CreateScheduleDialog.tsx` but:
- Datetime-local input for `run_at` instead of cron presets
- Validates datetime is in the future

**`ScheduleRuns.tsx`** — new page:
- Calls `useScheduleRuns()`
- Table columns: Schedule Name, Type badge, Project, Status (color-coded),
  Started, Duration, Session link
- Session link navigates to `/projects/{projectId}/sessions/{runId}`

#### Existing Page Update

File: `gui/frontend/src/pages/ScheduledTasks.tsx`
- Change `useSchedules()` → `useSchedules('recurring')`
- Update heading: "Scheduled Tasks" → "Recurring Schedules"

### Files to Change

| File | Change |
|------|--------|
| `gui/src/strawpot_gui/db.py` | Schema + migration: add `schedule_type`, `run_at`, make `cron_expr` nullable |
| `gui/src/strawpot_gui/routers/schedules.py` | New model, new endpoints, type filter |
| `gui/src/strawpot_gui/scheduler.py` | Handle one-time auto-disable in `_fire` |
| `gui/frontend/src/api/types.ts` | Update `Schedule`, add `ScheduleRun` |
| `gui/frontend/src/hooks/queries/use-schedules.ts` | Add type filter, add `useScheduleRuns` |
| `gui/frontend/src/hooks/mutations/use-schedules.ts` | Add `useCreateOneTimeSchedule` |
| `gui/frontend/src/App.tsx` | Three sub-routes under `/schedules` |
| `gui/frontend/src/layouts/AppLayout.tsx` | Sidebar group with 3 sub-links |
| `gui/frontend/src/pages/ScheduledTasks.tsx` | Filter to recurring, rename heading |
| **NEW** `gui/frontend/src/pages/OneTimeSchedules.tsx` | One-time schedule list page |
| **NEW** `gui/frontend/src/components/CreateOneTimeScheduleDialog.tsx` | Create/edit dialog |
| **NEW** `gui/frontend/src/pages/ScheduleRuns.tsx` | Aggregated run history page |


---

## New Feature: Manual Trigger & Re-run

### Problem

Users cannot manually trigger a recurring schedule or replay a past run from
the GUI. The only way schedules fire is via the automatic 30-second cron tick.
This makes it hard to test new schedules or retry failed runs.

### Goal

1. "Run Now" button on recurring schedule items to trigger immediately
2. "Re-run" button on run history items to replay a past run

### Backend Changes

#### Extract shared fire helper

File: `gui/src/strawpot_gui/scheduler.py`

Extract `Scheduler._fire()` logic into a standalone function:

```python
def fire_schedule(conn, schedule: dict, launch_fn, *, task_override: str | None = None) -> dict:
    """Fire a schedule immediately.

    Returns {"run_id": ...} or {"queued": True} or {"error": ...}.

    Args:
        conn: DB connection.
        schedule: Full schedule row as dict.
        launch_fn: launch_session_subprocess callable.
        task_override: If set, use this task instead of schedule's task.
    """
```

Logic (moved from `_fire`):
1. Resolve role (enforce `imu` for project 0)
2. If conversation-bound and active session exists, queue to `conversation_task_queue`
3. Otherwise build conversation context from prior turns
4. Call `launch_fn()` with project_id, task, role, system_prompt, schedule_id, conversation_id
5. On error, record in `last_error`

`Scheduler._fire()` becomes a thin wrapper that calls `fire_schedule()` then
calls `_advance_schedule()` on success.

#### New endpoints

File: `gui/src/strawpot_gui/routers/schedules.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/schedules/{id}/trigger` | Manual trigger: fire schedule now |
| POST | `/api/schedules/runs/{run_id}/rerun` | Re-run a past schedule run |

**`POST /api/schedules/{id}/trigger`**
- Load schedule row, 404 if not found
- Import `fire_schedule` from scheduler and `launch_session_subprocess` from sessions
- Call `fire_schedule(conn, schedule, launch_fn)`
- Do NOT advance `next_run_at` (ad-hoc, not a cron tick)
- Update `last_run_at` to now
- Return `{"run_id": ...}` or `{"queued": true}` or 500 on error

**`POST /api/schedules/runs/{run_id}/rerun`**
- Look up session by `run_id`, 404 if not found or no `schedule_id`
- Load schedule row, 404 if schedule deleted
- Use session's `user_task` if available (original task without context), else `task`
- Call `fire_schedule(conn, schedule, launch_fn, task_override=original_task)`
- Return `{"run_id": ...}` or `{"queued": true}` or 500 on error

### Frontend Changes

#### Mutations

File: `gui/frontend/src/hooks/mutations/use-schedules.ts`

```typescript
export function useTriggerSchedule() {
  // POST /api/schedules/${id}/trigger
  // Invalidates: schedules.all, schedules.runs
}

export function useRerunScheduleRun() {
  // POST /api/schedules/runs/${runId}/rerun
  // Invalidates: schedules.runs
}
```

#### UI Buttons

File: `gui/frontend/src/pages/ScheduledTasks.tsx`
- Add "Run Now" button (Zap icon) in Actions column, between edit and toggle buttons
- Calls `useTriggerSchedule()` with schedule id

File: `gui/frontend/src/pages/ScheduleRuns.tsx`
- Add "Re-run" button (RotateCcw icon) per row, next to existing session link button
- Calls `useRerunScheduleRun()` with run_id

### Files to Change

| File | Change |
|------|--------|
| `gui/src/strawpot_gui/scheduler.py` | Extract `fire_schedule()` from `_fire()` |
| `gui/src/strawpot_gui/routers/schedules.py` | Add trigger + rerun endpoints |
| `gui/frontend/src/hooks/mutations/use-schedules.ts` | Add `useTriggerSchedule`, `useRerunScheduleRun` |
| `gui/frontend/src/pages/ScheduledTasks.tsx` | Add "Run Now" button |
| `gui/frontend/src/pages/ScheduleRuns.tsx` | Add "Re-run" button |

### Tests

| File | Coverage |
|------|----------|
| `gui/tests/test_schedules.py` | Add tests for trigger + rerun endpoints |
| `gui/tests/test_scheduler.py` | Test `fire_schedule()` standalone function |

---

## Implementation Status

| # | Item | Status |
|---|------|--------|
| 1 | Database schema for `scheduled_tasks` | Done |
| 2 | `schedule_id` FK in `sessions` table | Done |
| 3 | `skip_if_running` column migration | Done |
| 4 | CRUD API endpoints (list, create, get, update, delete) | Done |
| 5 | Enable/disable endpoints | Done |
| 6 | Schedule history endpoint (`GET /schedules/{id}/history`) | Done |
| 7 | Cron expression validation (croniter) | Done |
| 8 | Scheduler engine (30s loop, fire-when-due) | Done |
| 9 | Skip-if-running logic | Done |
| 10 | Frontend: ScheduledTasks page | Done |
| 11 | Frontend: CreateScheduleDialog with cron presets | Done |
| 12 | Frontend: query and mutation hooks | Done |
| 13 | Frontend: routing and sidebar nav | Done |
| 14 | Backend tests (CRUD + scheduler) | Done |
| 15 | DB migration: add `schedule_type`, `run_at`, make `cron_expr` nullable | Done (PR #272) |
| 16 | Backend: `POST /api/schedules/one-time` endpoint | Done (PR #272) |
| 17 | Backend: `?type=` filter on `GET /api/schedules` | Done (PR #272) |
| 18 | Backend: `GET /api/schedules/runs` endpoint | Done (PR #272) |
| 19 | Backend: enable endpoint handles one-time (reject past `run_at`) | Done (PR #272) |
| 20 | Scheduler: one-time auto-disable after fire | Done (PR #272) |
| 21 | Scheduler: `_init_next_run_times` filters to recurring only | Done (PR #272) |
| 22 | Scheduler: skip-if-running for one-time leaves `next_run_at` unchanged | Done (PR #272) |
| 23 | Frontend types: update `Schedule`, add `ScheduleRun` | Done (PR #273) |
| 24 | Frontend hooks: type filter, `useScheduleRuns`, `useCreateOneTimeSchedule` | Done (PR #273) |
| 25 | Frontend routing: three sub-routes under `/schedules` | Done (PR #274) |
| 26 | Frontend nav: sidebar group with Recurring / One-Time / Run History | Done (PR #274) |
| 27 | Frontend: `OneTimeSchedules.tsx` page | Done (PR #275) |
| 28 | Frontend: `CreateOneTimeScheduleDialog.tsx` | Done (PR #275) |
| 29 | Frontend: `ScheduleRuns.tsx` page | Done (PR #275) |
| 30 | Frontend: update `ScheduledTasks.tsx` to filter recurring only | Done (PR #275) |
| 31 | Backend tests for one-time schedules + runs endpoint | Done (PR #272) |
| 32 | Extract `fire_schedule()` from `Scheduler._fire()` | Done |
| 33 | `POST /api/schedules/{id}/trigger` endpoint | Done |
| 34 | `POST /api/schedules/runs/{run_id}/rerun` endpoint | Done |
| 35 | Frontend: `useTriggerSchedule` + `useRerunScheduleRun` mutations | Planned |
| 36 | Frontend: "Run Now" button on ScheduledTasks | Planned |
| 37 | Frontend: "Re-run" button on ScheduleRuns | Planned |
| 38 | Backend tests for trigger + rerun endpoints | Done |

## Not in Scope

- CLI commands for schedule management (all management via GUI API)
- Timezone-aware scheduling (cron stored in UTC, frontend converts to/from local)
- Schedule templates or presets
