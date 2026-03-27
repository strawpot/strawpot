# TODO

## Architecture

- [ ] **Conversation history service**
  A dedicated service layer that provides queryable access to conversation
  history. Agents interact with it through tools registered in Denden's tool
  catalog. Separate from Denden (which is the communication layer) — Denden
  routes tool calls to the service, like it does for `memory.*` and `delegate`.

  **Tools:**
  - `conversation.list_turns()` — turn metadata (task, status, files, duration)
  - `conversation.read_turn(N)` — full output for turn N
  - `conversation.search(query)` — search across turn outputs
  - `conversation.decisions()` — structured decisions from all turns

  **Why:** Phase 2 (conversation history file) covers most use cases — full
  output for last 5 turns, recap for older turns, readable on demand. The
  service adds value mainly for queryable search across long conversations.
  Not urgent — the history file works well for typical conversation lengths.

  **Depends on:** Wrapper protocol supporting tool registration (wrappers must
  expose conversation tools to the agent). See `designs/context/DESIGN.md`
  Phase 3 for full details.

- [x] **Parallel sub-agent delegation**
  Currently delegation is sequential — an agent calls `stub.Send()` which
  blocks until the sub-agent finishes. The architecture already supports
  parallelism in the gRPC server thread pool, `handle_delegate()`, agent
  workspaces, role staging, and tracing spans. Incremental changes needed:
  thread-safe locks for `Session._agents`/`_agent_info`/`_agent_spans`,
  `Tracer` JSONL writes, and `_write_session_file()`; client-side agent
  wrapper must support concurrent gRPC calls. Shared worktree conflicts
  can be managed via task decomposition discipline initially.

- [ ] **Session re-run**
  "Run again" button on archived sessions pre-filling launch dialog with
  the same role, task, and config overrides. Also covers sub-agent
  delegation retry from the session detail view.

- [ ] **Hooks**
  Pre/post spawn, pre/post cleanup, and memory extension points. Allow
  users to run custom scripts at key session lifecycle events.

- [ ] **Agent CLI output streaming**
  Hook into agent CLI native output streams so StrawPot can observe what
  agents are doing in real time — tool calls, file edits, decisions,
  progress — instead of waiting for the session to finish.

  **Problem:** Running a session is opaque. StrawPot spawns the agent CLI
  and blocks until it exits. The GUI shows "running…" with no visibility
  into what the agent is actually doing. Each agent CLI already emits
  structured streaming output, but the wrapper protocol has no channel to
  capture it.

  **Native streaming formats (already available):**
  - **Claude Code:** `--output-format stream-json` emits JSONL with
    `assistant`, `tool_use`, `tool_result`, `result` message types
  - **Gemini CLI:** Streaming terminal output (token counts parseable)
  - **Codex:** `--json` flag emits structured JSON events
  - **OpenHands:** WebSocket event stream from the runtime

  **Phase 1 — Sidecar event file**
  StrawPot creates a JSONL event file at
  `<session_dir>/agents/<agent_id>/.events.jsonl` and passes its path
  via `STRAWPOT_EVENT_FILE` env var. Each wrapper monitors its agent
  CLI's native output stream and translates events into a common format:
  ```jsonl
  {"event":"tool_use","data":{"tool":"Edit","file":"src/main.py"}}
  {"event":"tool_result","data":{"tool":"Edit","status":"ok"}}
  {"event":"progress","data":{"step":"analyzing","pct":30}}
  {"event":"cost","data":{"input_tokens":1500,"output_tokens":800,"model":"claude-sonnet-4-20250514"}}
  {"event":"decision","data":{"type":"architecture","summary":"Using repository pattern"}}
  {"event":"file_changed","data":{"path":"src/main.py","action":"modified"}}
  ```

  **Per-wrapper implementation:**
  Each wrapper (Go binary) adds a `monitor` goroutine that reads the
  agent CLI's stdout/stderr and writes translated events to the file:
  - **Claude Code wrapper:** Spawn with `--output-format stream-json`,
    parse JSONL stream, emit `tool_use`/`tool_result`/`cost` events
  - **Gemini wrapper:** Parse streaming output for token counts and
    tool invocations
  - **Codex wrapper:** Parse `--json` output events
  - **OpenHands wrapper:** Connect to WebSocket event stream

  **Phase 2 — StrawPot event reader**
  `WrapperRuntime` tails the event file in a background thread using
  `inotify`/`kqueue` and forwards events to the tracer and event bus.
  GUI picks them up via the existing WebSocket channel. Events appear
  as a live activity feed in the session detail view.

  **Phase 3 — GUI live activity view**
  Surface agent operations in the GUI:
  - Real-time tool call feed (what the agent is doing now)
  - File change list (files created/modified/deleted)
  - Cost/token counters (running totals)
  - Progress indicators when available

  **Depends on:** Phase 1 requires per-wrapper changes (Go). Phase 2
  requires changes to `WrapperRuntime` in StrawPot. Phase 3 requires
  Phase 2 + GUI components.

## Self-Improvement

- [x] **Support self-improvement**
  Allow agents to improve themselves across sessions through three mechanisms:
  - ~~**Memory** — persistent knowledge that agents accumulate and reference~~ (done)
  - ~~**System Prompt** — self-authored or refined system prompts tuned to the project~~ (done — evaluator delegation loop)
  - ~~**Skill** — agent-created skills that automate recurring patterns~~ (done — evaluator delegation loop)

## Security

- [ ] **Sanitize summary field in session API responses**
  The `summary` field in `delegate_end` trace events comes from agent output
  unfiltered and is exposed via `GET /api/projects/{id}/sessions`. Could
  inadvertently contain API keys or credentials in error messages. Mitigations:
  truncate to a reasonable length, add regex-based redaction for common secret
  patterns. Low priority while GUI is local-only.

- [ ] **Encrypt session artifacts on disk**
  Artifacts in `.strawpot/sessions/*/artifacts/` store raw task text and agent
  stdout/stderr in plaintext. Consider optional at-rest encryption with key
  management via OS keychain. Low priority for single-user local machines.

## Dependency Management

- [ ] **Unified denden installation and updates**
  denden-server (Python gRPC lib) and denden CLI (Go binary) share proto
  definitions and are released in lockstep, but installed through separate
  channels (PyPI vs GitHub Releases). Version drift between the two causes
  silent failures (e.g. empty `delegateResult`). Current mitigations: skill
  PATH prepending ensures agents use the managed binary, and install scripts
  default to the skill directory. Longer-term options:
  - **Option A: strawpot manages CLI at session start** — download the CLI
    binary matching `denden.__version__` from GitHub Releases to a cache dir
    (`~/.strawpot/bin/`). Simplest change (~50 lines in session.py), no CI
    changes to denden repo.
  - **Option B: Bundle CLI in denden-server platform wheels** — produce
    per-platform wheels (linux/amd64, darwin/arm64, etc.) containing the Go
    binary. One `pip install` gets both. Requires CI matrix build with
    `cibuildwheel` and a `hatch_build.py` hook. More complex but eliminates
    the separate install channel entirely.
  - **Option C: Version check at session start** — compare
    `denden.__version__` against `denden status` output, warn or error on
    mismatch. Quick win that catches drift without solving it.
  Also need to consider how denden-server itself gets updated — currently
  unpinned in strawpot's pyproject.toml, so `pip install --upgrade strawpot`
  may or may not pull a newer denden-server depending on resolver state.

## Resources

- [ ] **Pluggable context builder**
  Make the conversation context builder a resource type (like memory providers).
  Currently `_build_conversation_context()` is hardcoded in the GUI router with
  fixed tiered condensation, turn caps, and recap instructions. A pluggable
  context builder would let users customize how prior turns are summarized —
  e.g., domain-specific condensation, LLM-based summarization, or different
  formats for different agent runtimes. The interface would mirror memory
  providers: a Python class with a `build(sessions) -> str` method, resolved
  by name from project-local or global directories, with a manifest file
  (e.g., `CONTEXT.md`). Default builder ships built-in with the current logic.

- [ ] **Support custom resource import**
  Allow users to import custom resources (files, configs, templates) into
  projects that agents can reference during sessions. Currently resources
  are limited to roles, skills, and project files. Custom imports would
  let users provide reference docs, API specs, or other context that agents
  need but that don't fit existing resource types.

## GUI

- [ ] **Add search to Schedule One-Time and Recurring pages**
  Client-side filtering (not paginated, small dataset). Create a reusable
  `SearchInput` component (debounced, with search icon and clear button).
  Use `useMemo` to filter the already-fetched array on `name`, `task`, and
  `project_name` (case-insensitive). Show "No schedules match" empty state
  when search is active but yields no results.

- [ ] **Add search to the Session list**
  Server-side search (paginated, dataset grows). Add a `q` query param to
  both `GET /api/sessions` and `GET /api/projects/{id}/sessions` that does
  `LIKE` matching across `task`, `user_task`, `role`, and `run_id`. Update
  `useProjectSessions` hook to accept a `search` param and include it in
  the query key. Add `SearchInput` to the Sessions tab in `ProjectDetail`,
  resetting page to 1 on search change.

## Housekeeping

- [ ] **Archive retention policy**
  Configurable max age or count for archived sessions per project. Auto-prune
  old session directories in `.strawpot/sessions/` to reclaim disk space.
  Low priority — users can manually delete session directories for now.
