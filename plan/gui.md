# Loguetown — GUI Deep Dive

The GUI is a **full management interface**. It calls the same API as the CLI and adds richer interaction for visualization, management, moderation, and conversation.

---

## Plan / DAG Screen *(visualization)*

CLI equivalent: `lt plan show`, `lt status`

- Nodes: tasks colored by status (grey=blocked, blue=running, yellow=reviewing, green=done, red=failed, orange=needs-human)
- Edges: dependency arrows; hover to see dep titles
- Click a node → Task Detail side panel (acceptance criteria, branch, worktree path, run history)
- **Why GUI over CLI?** — A spatial graph makes dependency structure immediately legible; `lt plan show` renders a text tree which is adequate but slower to scan for a large DAG

---

## Run Timeline Screen *(visualization)*

CLI equivalent: `lt chronicle --task <id>`

The timeline for a selected task shows all events interleaved in chronological order:

```
14:23:01  [system]          WORKTREE_CREATED  lt/pl-abc/tk-xyz/a1
14:23:02  [agent/implementer/charlie]  "Reading acceptance criteria..."
14:23:45  [system]          COMMIT_CREATED    abc123f "feat: add OAuth2 provider interface"
14:24:01  [system]          COMMAND_STARTED   npx eslint src
14:24:04  [system]          COMMAND_FINISHED  exit=0
14:24:32  [system]          CHECKS_FINISHED   exit=0  (27 tests passed)
14:24:33  [agent/implementer/charlie]  REQUEST_REVIEW → reviewer
14:25:01  [agent/reviewer]  REVIEW_SUBMITTED  blockers=1
14:25:02  [system]          RUN_QUEUED        fixer attempt=2
```

- Click any event → expand full payload JSON
- Click `DIFF_SNAPSHOT_SAVED` → jump to Diff & Review screen
- Click `COMMAND_FINISHED` → expand stdout/stderr inline
- Click `MEMORY_PROPOSED` → jump to Memory screen for that chunk
- **Why GUI over CLI?** — `lt chronicle` streams raw JSONL; the GUI renders it with colour-coded actors, collapsible payloads, and cross-screen navigation

---

## Diff & Review Screen *(visualization + moderation)*

CLI equivalents: `lt diff <task-id>`, `lt review show <task-id>`, `lt tasks approve/reject <id>`

- Two-pane unified diff with syntax highlighting
- Reviewer `blocking` findings overlaid as inline annotations on the relevant lines
- Non-blocking findings shown in a sidebar list
- Risk score and confidence badge
- **"Approve & merge"** / **"Request fix"** / **"Reject"** buttons
- **Why GUI over CLI?** — Inline diff annotations and risk overlays require a visual layout that a terminal diff cannot provide. Approval itself works fine via `lt tasks approve <id>` if the human has already reviewed via another tool (e.g., a local diff viewer)

---

## Merge Gate Screen *(moderation)*

CLI equivalent: `lt tasks approve/reject <id> [--comment "..."]`

- Policy checklist: each gate condition (checks, review, risk policy) shown as pass/fail
- Buttons active only when all required gates pass
- Comment box for rejection reason
- **Why GUI over CLI?** — The checklist visualization makes it instantly clear *which* gate is still blocking. `lt tasks approve` works identically but prints the checklist as text

---

## Memory Screen *(visualization + moderation)*

CLI equivalent: `lt memory list/show/promote/reject/deprecate`

- Layer tabs: Episodic | Semantic Local | Semantic Global
- Table columns: title, tags, agent, status, provenance (run/commit), last validated
- Filter bar: layer / agent / status / tags / free-text search
- Click a row → full Markdown chunk rendered
- Status badge with inline action buttons:
  - `proposed` → **Approve** / **Reject** (reason input inline)
  - `approved` → **Promote** / **Reject**
  - `promoted` → **Deprecate**
- Episodic sub-view: horizontal timeline of past run outcomes per agent (green=success, red=failure, yellow=warning)
- **Why GUI over CLI?** — Memory moderation involves reading content then immediately acting; the GUI collapses read + act into one screen. `lt memory` commands work for scripted or batch promotion

---

## Agents Screen *(management)*

CLI equivalent: `lt agent list/create/edit/spawn/kill`, `lt memory list --agent <name>`

The Agents screen is a full management surface — not just a viewer.

**Agent list panel:**
- Columns: name, role, status (idle / active / blocked), current task, model provider
- **"New Agent"** button → opens create form (name, role, model provider, extra skills)
- Each row has a **"..."** menu → Edit Charter, Spawn, Kill, Delete

**Agent detail panel (click any agent):**

*Identity tab:*
- Inline Charter YAML editor (Monaco) — edit `role`, `model`, `extra_skills`, `tools.bash_allowlist`, `memory.budget`; **Save** button calls `PATCH /agents/:name`
- Role badge with link to the Roles & Skills screen
- Model provider badge (shows active provider + model ID)

*Skills tab:*
- Lists all skills loaded for the last session, sorted by similarity score
- Green = loaded (above threshold), grey = skipped (below threshold)
- Similarity scores shown as bars; edit threshold inline and preview changes live
- **"Add skill file"** button → scaffold a new `.md` file for this role

*Memory tab:*
- Layer switcher: Working | Episodic | Semantic Local | Semantic Global
- Paginated chunk list with title, tags, status badge, similarity score (for last query)
- Similarity search box — type a description and see which chunks would be retrieved
- Per-chunk actions: **Promote**, **Reject** (reason inline), **Deprecate**, **Edit** (opens chunk `.md` in Monaco)
- **"New chunk"** button — create a new memory chunk manually in any layer

*Session log tab:*
- Live stdout stream from the current Runner subprocess
- Scroll-locked; pause/resume button

*Inbox tab:*
- Dispatch messages for this agent (from / type / timestamp / payload summary)
- Click any message → full JSON payload

- **Why GUI over CLI?** — The Skills similarity view and live memory search with scores are diagnostic tools that benefit from instant interactive feedback; the Charter YAML editor with live validation is faster than editing raw YAML and re-running the daemon. `lt agent edit`, `lt memory`, and `lt skills` commands cover the same operations for scripted use.

---

## Roles & Skills Screen *(management)*

CLI equivalent: `lt role list/create/edit/delete`, `lt skills list/add/edit/reindex`

**Roles panel (left):**
- List of all role YAML files in `.loguetown/roles/`
- **"New Role"** button → scaffold a new role with name and description
- Each row: name, description, agent count (how many agents use this role)
- Click a role → open role detail

**Role detail:**
- Inline Monaco editor for the full role YAML (`default_skills`, `default_tools`, `default_model`, `default_memory`)
- **Save** button calls `PUT /roles/:name`
- **Delete** button (disabled if any agents reference this role; shows warning)

**Skills panel (right, per selected role):**
- List of all `*.md` files under `.loguetown/skills/{role}/` and `shared/`
- Columns: filename, title (first heading), tags, last modified
- **"New skill file"** button → creates blank `.md` with frontmatter scaffold, opens in Monaco editor
- Click any file → open inline editor; **Save** writes to disk and triggers re-embedding
- **Delete** button per file

**"Test retrieval" box (bottom):**
- Enter a task description → show which skill chunks score above `min_similarity` for this role, ranked by score
- Live preview: adjust threshold slider and see which chunks would be included/excluded
- **Why GUI over CLI?** — The retrieval test and threshold tuning are genuinely interactive; `lt skills query <text> --role <name>` provides the same search from the terminal for scripted use

---

## Chat Screen *(conversation)*

CLI equivalent: `lt chat [--agent <name>]`, `lt chat --history`

The Chat screen provides a persistent conversation interface with the orchestrator or any individual agent. Conversations are stored in the `conversations` + `conversation_turns` tables and replayed on reload.

**Conversation list (left sidebar):**
- One entry per conversation: participant name (orchestrator or agent), last message preview, timestamp
- **"New conversation"** button → start a fresh chat (choose: orchestrator or select an agent by name)
- Conversations persist across sessions; old ones are browseable as history

**Orchestrator chat:**
- Converse with the Planner / daemon about the current plan
- Example prompts:
  - *"Why is task T3 blocked?"*
  - *"What's the risk score on the T4 diff?"*
  - *"Add a new task to add rate limiting to the auth endpoints"*
  - *"Summarize what charlie has done today"*
- The orchestrator has access to the full Chronicle and can answer queries about any task, run, or event
- Tool calls made by the orchestrator during the conversation are shown inline (collapsed by default)

**Per-agent chat:**
- Select any agent by name → opens (or resumes) the conversation with that agent
- Shows the full turn-by-turn transcript: human messages + assistant responses + tool calls
- New messages are delivered to the running Runner subprocess (if active) or queued for the next session
- **Context panel (right):** shows the current task the agent is working on, its active memory chunks, and the last check results — so the human can reference them while chatting

**Conversation transcript view:**
- Each turn is rendered as a bubble: human (right), assistant (left)
- Tool calls are shown as collapsible code blocks (tool name + input + output)
- Chronicle events that reference this conversation are linked inline (e.g., `HUMAN_COMMENTED → TASK_UNBLOCKED`)
- **Export** button → copy transcript as Markdown or JSON

- **Why GUI over CLI?** — A persistent, threaded chat UI with tool-call rendering and context panel is significantly more usable than a terminal REPL. `lt chat` provides the same interaction for automation scripts or quick terminal queries.
