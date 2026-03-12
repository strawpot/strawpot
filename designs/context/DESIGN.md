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

Record which files were modified during each session so the next session knows where to pick up.

**How it works:**

At session end (`Session.stop()` in `cli/src/strawpot/session.py`), before the tracer emits `session_end`, compute the list of changed files:

- **Worktree sessions:** The worktree branch (`strawpot/<session_id>`) is created from the base branch at session start. Run `git diff --name-only <base_branch>..<session_branch>` in the worktree directory to get changed files. The infrastructure for this already exists in `cli/src/strawpot/merge.py` (`_generate_patch()`).
- **Non-worktree sessions:** Run `git diff --name-only HEAD` to get uncommitted changes, plus `git diff --name-only HEAD~1` if the agent made commits. This is less reliable since concurrent sessions or user edits can pollute the diff — best-effort only.
- **Non-git sessions:** Report empty list.

**Data flow:**

```
Session.stop()
  → compute files_changed list (before cleanup)
  → tracer.session_end(..., files_changed=["src/foo.py", "tests/test_foo.py"])
  → trace.jsonl stores files_changed in session_end event
  → _parse_trace() reads it, stores as JSON array in sessions.files_changed column
  → _build_conversation_context() shows "Files: src/foo.py, tests/test_foo.py"
    for most recent 2-3 turns only
```

**Changes required:**

| File | Change |
|------|--------|
| `cli/src/strawpot/session.py` | Compute `files_changed` in `stop()` before `session_end` emission |
| `cli/src/strawpot/trace.py` | Add `files_changed: list[str]` param to `session_end()` |
| `gui/src/strawpot_gui/db.py` | Add `files_changed TEXT` column (JSON array), parse in `_parse_trace()` |
| `gui/src/strawpot_gui/routers/conversations.py` | Show file paths in context for recent turns |

### 5. Structured context format

Replace the current flat text format with a more structured output that separates metadata from content. Include turn status (completed/failed), duration, and optional file paths — giving the agent richer signals about what happened.

### 6. Richer session summaries

Currently the session summary is the raw agent output — it captures *what* was done but loses the mid-session discussion: user corrections, design decisions, rejected alternatives, and open items. This means the next session in a conversation has no awareness of the "why" behind prior turns.

**Approach: Recap instruction**

When `_build_conversation_context()` builds the text prefix for a conversation with prior turns, append a short instruction asking the agent to end its response with a structured recap:

```
When you finish, end your response with a "## Session Recap" section containing:
- What was accomplished
- Key decisions (e.g., "user chose X over Y")
- Open items or next steps
```

This instruction only appears when there is conversation context (not on the first turn).

**Extraction:** In `_parse_trace()`, when reading the output artifact for `summary`, check if the output contains a `## Session Recap` block. If found, store that block as the summary instead of the full output. If not found, fall back to the current behavior (full output).

**Why this works for both context and memory:**

- **Conversation context:** The context builder condenses the summary via tiered truncation. A structured recap condenses much better than raw log output — 120 chars of recap carries more signal than 120 chars of log.
- **Memory:** `memory_provider.dump(task, output, status)` receives the same output. A structured recap at the end gives the memory provider cleaner input to decide what's worth persisting long-term.

**Changes required:**

| File | Change |
|------|--------|
| `gui/src/strawpot_gui/routers/conversations.py` | Append recap instruction in `_build_conversation_context()` |
| `gui/src/strawpot_gui/db.py` | In `_parse_trace()`, prefer `## Session Recap` block over full output for `summary` |

**Fallback:** If the agent doesn't produce the recap (crashed, non-compliant wrapper, first turn), the full output is used as before.

**Long-term:** The recap instruction is a pragmatic near-term solution. The long-term approach is structured decision events in the wrapper protocol — agents emit decision, correction, and blocker events during the session, which the context builder and memory provider consume directly. This requires a wrapper protocol extension (see TODO.md).

## Implementation status

| # | Item | Status |
|---|------|--------|
| 1 | Conversation context builder (`_build_conversation_context`) | Done |
| 2 | Memory get/dump integration at session level | Done |
| 3 | Memory get/dump integration at delegation level | Done |
| 4 | `user_task` / `memory_task` separation to prevent context pollution | Done |
| 5 | Filter out non-terminal sessions | Done |
| 6 | Use `user_task` instead of `task` for asked lines | Done |
| 7 | Cap turns + tiered condensation | Done |
| 8 | File change tracking in trace events | Done |
| 9 | Structured context format | Done |
| 10 | Richer session summaries | Discussion |

## Key files

| File | Role |
|------|------|
| `gui/src/strawpot_gui/routers/conversations.py` | Conversation context builder + task submission endpoint |
| `gui/src/strawpot_gui/db.py` | Sessions table schema, `_parse_trace()` |
| `cli/src/strawpot/session.py` | Memory get/dump at session level |
| `cli/src/strawpot/delegation.py` | Memory get/dump at delegation level, `_format_memory_prompt()` |
| `cli/src/strawpot/trace.py` | Trace event definitions and artifact storage |
| `gui/tests/test_conversations.py` | Tests for conversation context |
