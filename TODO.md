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
  service adds value mainly for worktree isolation (DB access, no file
  coordination) and queryable search across long conversations. Not urgent —
  the history file works well for typical conversation lengths.

  **Depends on:** Wrapper protocol supporting tool registration (wrappers must
  expose conversation tools to the agent). See `designs/context/DESIGN.md`
  Phase 3 for full details.

- [ ] **Structured decision events in wrapper protocol**
  Extend the wrapper protocol with a callback or sidecar mechanism for agents
  to emit structured events during a session — decisions, corrections, blockers.
  Currently the wrapper protocol is stateless (called once, no callbacks), so
  StrawPot only sees the final output blob. Structured events would let the
  context builder and memory provider use first-class decision records instead
  of reconstructing them from raw output. Requires each wrapper (Claude Code,
  Gemini, Codex) to implement the callback. Related to cost/token tracking
  which also needs a wrapper protocol extension.

  **Why not now:** The recap instruction already captures decisions, blockers,
  and open items in prose. `_extract_recap()` pulls them out reliably. The
  practical benefit of structured events is small until we need to
  programmatically query decisions across many conversations. Depends on
  wrapper protocol extension and optionally on the conversation history
  service. See `designs/context/DESIGN.md` Phase 4 for full details.

- [ ] **Parallel sub-agent delegation**
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
  Pre/post spawn, pre/post cleanup extension points. Allow users to run
  custom scripts at key session lifecycle events.

- [ ] **Cost / token tracking**
  Requires wrapper protocol extension. The wrapper protocol is stateless
  (called once to translate args to CLI command) — no callback to return
  metrics. Needs a sidecar file approach: wrapper writes
  `<workspace>/.metrics.json` after agent exits, `WrapperRuntime` reads
  it and passes to tracer via extended `AgentResult.metrics` field.
  Each runtime reports usage differently (Claude Code, Gemini, etc.),
  so per-wrapper parsing is needed. GUI side is straightforward once
  trace events carry the data.

## Self-Improvement

- [ ] **Support self-improvement**
  Allow agents to improve themselves across sessions through three mechanisms:
  - ~~**Memory** — persistent knowledge that agents accumulate and reference~~ (done)
  - **System Prompt** — self-authored or refined system prompts tuned to the project
  - **Skill** — agent-created skills that automate recurring patterns

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

## Housekeeping

- [ ] **Archive retention policy**
  Configurable max age or count for archived sessions per project. Auto-prune
  old session directories in `.strawpot/sessions/` to reclaim disk space.
  Low priority — users can manually delete session directories for now.
