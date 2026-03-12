# Design: Improve Conversation Context Handover

## Context

`_build_conversation_context()` in `gui/src/strawpot_gui/routers/conversations.py` builds a text prefix from prior sessions to give the next agent continuity. Currently it has several issues: no turn cap (unbounded growth), uniform condensation (recent turns lose detail), uses `task` instead of `user_task` (nested context), and includes running sessions. This plan addresses the first three fixes and defers file change tracking.

## Changes

### 1. Filter out non-terminal sessions

**File:** `gui/src/strawpot_gui/routers/conversations.py` line 46

Update the SQL query:
```sql
SELECT task, user_task, summary, exit_code, status FROM sessions
WHERE conversation_id = ? AND status NOT IN ('starting', 'running')
ORDER BY started_at
```

This prevents confusing `(status: running)` lines from appearing in context.

### 2. Use `user_task` instead of `task` for "asked:" lines

**File:** `gui/src/strawpot_gui/routers/conversations.py` line 78

Change:
```python
task_text = row["user_task"] or row["task"]
task_line = _condense(task_text, task_limit)
```

Fallback to `task` handles sessions created before the `user_task` column existed. This prevents nested context (where prior context gets re-embedded turn after turn).

### 3. Cap turns + tiered condensation

**File:** `gui/src/strawpot_gui/routers/conversations.py` lines 66-85

- `MAX_TURNS = 10` — keep only the 10 most recent completed sessions
- If turns were dropped, prepend `"(… {N} earlier turns omitted)"`
- Tiered limits based on position from end:
  - **Old turns** (4+ from end): task 100 chars, summary 120 chars
  - **Recent turns** (2-3 from end): task 200 chars, summary 300 chars
  - **Last turn**: task 200 chars (summary goes into Pending Follow-up in full anyway)

### 4. File change tracking — DEFERRED

Requires cross-cutting changes to CLI trace events, db schema, and trace parser. Not worth bundling. Can be done in a follow-up PR by adding `files_changed: list[str]` to the `session_end` trace event.

## Files

| File | Action |
|------|--------|
| `gui/src/strawpot_gui/routers/conversations.py` | Modify `_build_conversation_context()` |
| `gui/tests/test_conversations.py` | Add tests for all 3 fixes |

## Tests

1. `test_context_excludes_running_sessions` — insert a running session, submit new task, verify context doesn't mention it
2. `test_context_uses_user_task` — verify the "asked:" line uses raw user input, not context-padded task
3. `test_context_caps_at_max_turns` — insert 15 completed sessions, verify only 10 appear with omission note
4. `test_context_tiered_condensation` — verify recent turns have longer text than old turns

## Verification

1. Run `pytest gui/tests/test_conversations.py -v` — all new and existing tests pass
2. Manual: open a long conversation in Bot Imu, submit a new task, inspect the session's `task` column to confirm the context format
