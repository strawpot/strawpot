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

**Extraction:** The DB stores the full agent output as the session `summary`. Extraction happens at read time in `_build_conversation_context()` — when building context for the next turn, `_extract_recap()` extracts just the recap section from the stored summary. This keeps the full output available for GUI display while giving the context builder a focused summary.

`_extract_recap()` uses `rfind` to find the last `## Session Recap` heading (handles agents that produce multiple headings), returns everything after it. Falls back to the full content if no recap is found.

**Why this works for both context and memory:**

- **Conversation context:** The context builder condenses the extracted recap via tiered truncation. A structured recap condenses much better than raw log output — 120 chars of recap carries more signal than 120 chars of log.
- **Memory:** `memory_provider.dump(task, output, status)` receives the full output including the recap block. A structured recap at the end gives the memory provider cleaner input to decide what's worth persisting long-term.

**Changes required:**

| File | Change |
|------|--------|
| `gui/src/strawpot_gui/routers/conversations.py` | Append recap instruction in `_build_conversation_context()`, apply `_extract_recap()` when reading summaries for context |
| `gui/src/strawpot_gui/db.py` | `_extract_recap()` helper (used by context builder, not by `_parse_trace()`) |

**Fallback:** If the agent doesn't produce the recap (crashed, non-compliant wrapper, first turn), the full output is used as before.

**Long-term:** The recap instruction is a pragmatic near-term solution. See the roadmap below for the full evolution.

## Roadmap

### Phase 1: Richer context (implement now)

Improve what's already in the context prefix — no architecture changes.

#### 1a. Enhanced recap instruction

Ask for a more detailed structured recap instead of 3 brief bullets:

```
When you finish, end your response with a "## Session Recap" section containing:

### Accomplished
- What was done, with specifics (file paths, function names, error fixes)

### Changes Made
- Files modified and what changed in each

### Decisions
- Key choices and why (e.g., "used X over Y because...")

### Open Items
- What's left to do, blockers, or questions for the user
```

#### 1b. Dual Pending Follow-up

For the last turn, include both the structured recap AND a tail of raw output:

```
**Pending Follow-up:**

**Recap:**
[extracted recap, up to 1500 chars]

**Recent output:**
[last 1500 chars of full output, excluding recap section]
```

The recap tells the next agent *what to know*; the raw output shows *what actually happened*. They complement each other. Total Pending Follow-up ceiling: ~3K chars.

#### 1c. Tiered history lines (unchanged)

Older turns in the History section continue to use recap only, condensed to 120-300 chars. At that distance, the condensed recap is sufficient — if something from turn N-2 mattered, the agent at turn N-1 would have carried it forward in its own recap.

**Context budget:**

| Section | Max chars |
|---------|-----------|
| History (10 turns) | ~3-4K |
| Pending Follow-up (recap + raw tail) | ~3K |
| Recap instruction | ~500 |
| **Total** | **~7K** |

**Changes required:**

| File | Change |
|------|--------|
| `gui/src/strawpot_gui/routers/conversations.py` | Enhanced recap instruction text, dual Pending Follow-up with raw output tail |

### Phase 2: Conversation history file

Write a `.strawpot/conversation_history.md` file to the project working directory before spawning the agent. The context prefix includes a hint telling the agent where to find it.

```
> Full session outputs available at `.strawpot/conversation_history.md` —
> read it if you need more detail than the summaries above.
```

**File format:**

```markdown
# Conversation History

## Turn 1 — 2026-03-12T10:00:00 [completed, 45s]
**Task:** Implement the login page
**Files changed:** src/auth/login.tsx, src/auth/login.test.tsx

### Output
(full agent output, untruncated)

---

## Turn 2 — ...
```

**Bounds:** Last 5 turns get full output; turns 6-10 get recap only; older turns omitted.

**Why a file:**

- Runtime-agnostic — every agent (Claude Code, Codex, etc.) can read files natively
- On-demand — not loaded into context by default, agent reads it only when needed
- Zero context window cost
- Already gitignored (`.strawpot/` is in `.gitignore`)

**Limitation:** Awkward with worktree isolation — the file must be written in the worktree directory, which is created by the CLI, not the GUI. Requires coordination between the GUI (which builds context) and the CLI (which creates the worktree). This is solvable but adds coupling.

**Changes required:**

| File | Change |
|------|--------|
| `gui/src/strawpot_gui/routers/conversations.py` | New `_write_conversation_history()` helper, call before `launch_session_subprocess()`, add hint to context prefix |

### Phase 3: Conversation history service

A dedicated service layer (separate from Denden, which is the communication layer) that provides queryable access to conversation history. Agents interact with it through tools registered in Denden's tool catalog.

**Tools:**

```
conversation.list_turns()     → turn metadata (task, status, files, duration)
conversation.read_turn(N)     → full output for turn N
conversation.search(query)    → search across turn outputs
conversation.decisions()      → structured decisions from all turns
```

**Why a service, not Denden directly:**

Denden is the communication/routing layer (gRPC transport, tool dispatch). The conversation history service owns the data and query logic. Denden routes tool calls to it, just as it routes `memory.*` calls to the memory provider and `delegate` calls to the delegation engine.

**Why not the history file:**

- Works with worktree isolation — the service has DB access, no file coordination needed
- Queryable — agent can ask for specific turns or search, not read a wall of text
- Extensible — `conversation.search()` could use embeddings; `conversation.decisions()` could filter by topic

**Depends on:** Wrapper protocol supporting tool registration (wrappers must expose conversation tools to the agent).

### Phase 4: Structured decision events

Replace the recap instruction with structured events emitted during the session. Agents emit decision, correction, and blocker events via Denden during execution — not as a post-hoc summary.

```python
# Agent emits during session:
denden.emit_event("decision", {
    "choice": "JWT over sessions",
    "reason": "compliance requirement for stateless auth",
    "alternatives_rejected": ["session cookies"],
})

denden.emit_event("blocker", {
    "description": "CI pipeline failing on arm64",
    "workaround": "skipped arm64 tests for now",
})
```

Events are stored in the trace and queryable by the conversation history service. The context builder uses structured events instead of parsing prose recaps.

**Why this is the end state:**

- Machine-readable — no lossy extraction from prose
- Real-time — captured during session, not reconstructed after
- Lossless — agent explicitly marks what matters, nothing is dropped by condensation
- Works for both context builder and memory provider

**Depends on:** Wrapper protocol extension (see TODO.md), conversation history service (Phase 3).

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
| 10 | Richer session summaries (basic recap instruction) | Done |
| 11 | Enhanced recap instruction (Phase 1a) | Planned |
| 12 | Dual Pending Follow-up with raw output tail (Phase 1b) | Planned |
| 13 | Conversation history file (Phase 2) | Planned |
| 14 | Conversation history service (Phase 3) | Planned |
| 15 | Structured decision events (Phase 4) | Planned |

## Key files

| File | Role |
|------|------|
| `gui/src/strawpot_gui/routers/conversations.py` | Conversation context builder + task submission endpoint |
| `gui/src/strawpot_gui/db.py` | Sessions table schema, `_parse_trace()`, `_extract_recap()` |
| `cli/src/strawpot/session.py` | Memory get/dump at session level |
| `cli/src/strawpot/delegation.py` | Memory get/dump at delegation level, `_format_memory_prompt()` |
| `cli/src/strawpot/trace.py` | Trace event definitions and artifact storage |
| `gui/tests/test_conversations.py` | Tests for conversation context |
