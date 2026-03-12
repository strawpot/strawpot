# Design: Conversation Context Handover

## Overview

When a user sends multiple messages within a single conversation, each message launches a new session. These sessions are independent processes with no shared state. Context handover is the mechanism that gives each new session awareness of what happened before it.

There are two layers of context handover:

1. **Conversation context** (same conversation) — a text prefix built from prior sessions in the conversation, prepended to the agent's task. Managed by `_build_conversation_context()` in `gui/src/strawpot_gui/routers/conversations.py`.

2. **Memory** (cross-conversation) — context cards retrieved from the memory provider before the agent spawns, injected into the agent's system prompt. Managed by `memory_provider.get()` in `cli/src/strawpot/session.py` and `cli/src/strawpot/delegation.py`.

## How it works today

### Conversation context flow

```
User submits task to conversation
  → _build_conversation_context() queries all prior sessions
  → Formats as "## Prior Conversation" text block
  → Prepends to user's task: "{context}\n\n---\n\n{user_task}"
  → launch_session_subprocess() receives:
      task      = full_task (context + user input)
      user_task = raw user input (stored separately for display)
      memory_task = raw user input (used for memory scoring, not polluted by context)
```

### Memory flow

```
Session starts
  → memory_provider.get(task=memory_task) returns scored context cards
  → Formatted as "## Memory\n\n[kind] content" blocks
  → Injected into agent's system prompt (role_prompt + memory_prompt)
  → Agent executes with both conversation context (in task) and memory (in prompt)
Session ends
  → memory_provider.dump(task, output, status) stores for future recall
```

### Key separation of concerns

| Field | Contains | Used for |
|-------|----------|----------|
| `task` | Context prefix + user input | Agent sees full history |
| `user_task` | Raw user input only | UI display, stored in DB |
| `memory_task` | Raw user input only | Memory provider scoring |
| `summary` | Session output (from trace artifacts) | Next turn's context |

## Improvements

### 1. Filter out non-terminal sessions

Exclude sessions with status `starting`, `running`, `stopped`, or `stale` from the context query. Only `completed` and `failed` sessions carry useful information. Stopped sessions were killed by the user (no summary), and stale sessions are orphaned processes.

```sql
SELECT task, user_task, summary, exit_code, status FROM sessions
WHERE conversation_id = ? AND status IN ('completed', 'failed')
ORDER BY started_at
```

### 2. Use `user_task` instead of `task` for "asked:" lines

The `task` column contains the full task including prior context prefix, which causes nested/recursive context when re-embedded. Use `user_task` (raw user input) instead.

When `user_task` is NULL (sessions created before the column existed), fall back to `task` but strip the `## Prior Conversation` block if present (everything before the `---` separator).

### 3. Cap turns + tiered condensation

- `MAX_TURNS = 10` — keep only the 10 most recent terminal sessions
- If turns were dropped, prepend `"(… {N} earlier turns omitted)"`
- Tiered limits based on distance from end:
  - **Old turns** (4+ from end): task 100 chars, summary 120 chars
  - **Recent turns** (2-3 from end): task 200 chars, summary 300 chars
  - **Last turn**: task 200 chars, summary 200 chars (full detail goes into Pending Follow-up)
- **Pending Follow-up** capped at 800 chars to prevent a single large output from dominating the context

### 4. File change tracking

Record which files were modified during each session so the next session knows where to pick up. Add a `files_changed` field to the `session_end` trace event, populated by diffing the worktree at session completion. Parse in `_parse_trace()` and store as a JSON array column on the sessions table. In context, show file paths for the most recent 2-3 turns only.

### 5. Structured context format

Replace the current flat text format with a more structured output that separates metadata from content. Include turn status (completed/failed), duration, and optional file paths — giving the agent richer signals about what happened.

## Implementation status

| # | Item | Status |
|---|------|--------|
| 1 | Conversation context builder (`_build_conversation_context`) | Done |
| 2 | Memory get/dump integration at session level | Done |
| 3 | Memory get/dump integration at delegation level | Done |
| 4 | `user_task` / `memory_task` separation to prevent context pollution | Done |
| 5 | Filter out non-terminal sessions | Planned |
| 6 | Use `user_task` instead of `task` for asked lines | Planned |
| 7 | Cap turns + tiered condensation | Planned |
| 8 | File change tracking in trace events | Planned |
| 9 | Structured context format | Planned |

## Key files

| File | Role |
|------|------|
| `gui/src/strawpot_gui/routers/conversations.py` | Conversation context builder + task submission endpoint |
| `gui/src/strawpot_gui/db.py` | Sessions table schema, `_parse_trace()` |
| `cli/src/strawpot/session.py` | Memory get/dump at session level |
| `cli/src/strawpot/delegation.py` | Memory get/dump at delegation level, `_format_memory_prompt()` |
| `cli/src/strawpot/trace.py` | Trace event definitions and artifact storage |
| `gui/tests/test_conversations.py` | Tests for conversation context |
