# Loguetown — Roadmap

## Implementation Phases

### Phase 1 — Foundation
- [ ] Monorepo setup (pnpm workspaces: daemon, runner, gui, cli)
- [ ] SQLite schema + migrations (including `memory_chunks`, `skill_files`, vector tables)
- [ ] JSONL Chronicle writer (append + SQLite index)
- [ ] Role YAML loader and registry (`lt role list/create/edit`)
- [ ] Agent Charter YAML loader with role inheritance
- [ ] Basic CLI: `lt init`, `lt role create`, `lt agent create`, `lt agent list`

### Phase 2 — Skills + Memory Infrastructure
- [ ] Skill file scanner: index `*.md` files under `.loguetown/skills/` (role-scoped + shared)
- [ ] **Global skills store** at `~/.loguetown/skills/global/` — scanned and indexed alongside project skills
- [ ] Local embeddings: pluggable embedding provider (Ollama default, OpenAI option)
- [ ] SQLite vector storage: store embeddings as float32 BLOBs, cosine similarity search
- [ ] `lt skills list/add/edit/reindex` (all scopes); `lt skills reindex --global`
- [ ] Memory chunk file writer: `episodic` + `semantic_local` (project-local); `semantic_global` at `~/.loguetown/memory/global/`
- [ ] Memory retrieval: vector search per layer + scope, with budget allocation
- [ ] `lt memory list/show/promote/reject`; layer filter includes global scope
- [ ] Memory provider interface + local provider implementation

### Phase 3 — Single Agent Runtime
- [ ] Session builder: role → skills (vector-retrieved) + memory (vector-retrieved) → system prompt
- [ ] Model provider registry: Claude provider (default), OpenAI provider, Ollama provider
- [ ] Runner executor loop with selected model provider
- [ ] Git worktree create/cleanup
- [ ] `lt agent spawn` single-task execution loop
- [ ] Post-run episodic memory proposal (agent self-reflection after each run)

### Phase 4 — Check Pipelines
- [ ] `.loguetown/project.yaml` check pipeline loader
- [ ] Runner: execute check commands, emit COMMAND_* events
- [ ] Path-based routing (skip checks for docs-only changes)
- [ ] Artifact store: save stdout/stderr to disk with Chronicle reference

### Phase 5 — Multi-Agent Orchestration (Chat-First)
- [ ] **Orchestrator conversational agent**: persistent session, natural-language goal intake, plan proposal with human confirmation
- [ ] Orchestrator internal tools: `create_plan`, `queue_run`, `get_status`, `get_chronicle`, `approve_task`, `pause_all`, `get_memory`
- [ ] Planner agent invoked by Orchestrator: objective → DAG tasks in SQLite
- [ ] Scheduler goroutine (driven by Orchestrator decisions): unblock detection, Runner spawning
- [ ] Async status turns: Orchestrator injects progress updates back into the active conversation
- [ ] Dispatch message bus: SQLite queue + validator + router
- [ ] Typed A2A envelopes: REQUEST_REVIEW, REVIEW_RESULT, NEED_INFO
- [ ] Reviewer agent + Fixer agent
- [ ] Bounded retry policy
- [ ] `lt chat` as primary orchestration entry point; `lt run` as scripting shortcut

### Phase 6 — Merge Gate + Integration Branches + Escalation
- [ ] Gate policy evaluator (checks + review + approval_policy: require_human / auto / risk_based)
- [ ] Merge executor (squash / ff)
- [ ] Integration branch creation, child-task routing, and `lt plan land`
- [ ] `lt tasks approve` / `lt tasks reject` CLI commands
- [ ] Worktree cleanup on merge
- [ ] Patrol loop (health monitor): stale run detection, escalation creation, severity bump
- [ ] Escalation system: `escalations` table, ESCALATION_* events, auto-bump timer
- [ ] `lt escalate list/show/ack/resolve` CLI commands
- [ ] Notification channels: desktop notifications + webhook dispatch

### Phase 7 — GUI
- [ ] Fastify REST API + WebSocket Chronicle stream
- [ ] React app scaffold (Vite + Tailwind)
- [ ] Plan/DAG screen (React Flow)
- [ ] Run Timeline screen (event feed)
- [ ] Diff & Review screen
- [ ] Merge Gate screen (with approval policy status display)
- [ ] Memory screen (layer tabs, promote/reject UI, episodic timeline)
- [ ] Agents screen — management: create/edit agent (Charter YAML editor), skills retrieval preview, memory browser + editor, session log, inbox
- [ ] Roles & Skills screen — management: role YAML editor, skill file editor (Monaco), new-skill scaffold, retrieval test box with threshold slider
- [ ] Chat screen — conversation list, orchestrator chat, per-agent chat with full transcript + tool-call rendering + context panel
- [ ] `conversations` + `conversation_turns` REST endpoints (`GET/POST /conversations`, `POST /conversations/:id/turns`)

### Phase 8 — Polish
- [ ] `lt run --dry-run` plan preview
- [ ] Mem0 provider adapter
- [ ] Custom memory provider loader (dynamic import by path)
- [ ] OpenAI embeddings provider
- [ ] GUI auth (token-based for remote access)
- [ ] Failure summary artifact generation

---

## Extensibility Roadmap

### v1.1
- Better diff UI: file tree, syntax highlighting, inline blame
- Interactive step approval ("pause before commit" mode)
- Memory UI: promote/reject with reasons, search
- Rebase merge strategy
- **Per-agent work history (CV)** — global `~/.loguetown/db.sqlite` with `agent_runs` table tracking tasks completed, outcomes, token usage, duration across all projects. Surface via `lt agent show` and the Agents screen. Enables reliability-based agent selection for risky tasks.
- **Plan templates (Formulas)** — `.loguetown/templates/*.yaml` pre-define a task DAG structure with placeholder variables. `lt run --template <name> <args>` fills the template and creates a plan without a full Planner invocation. Useful for repeated patterns (add-endpoint, add-test-suite, refactor-module).
- **Explore mode agents** — Charter option `mode: explore` gives an agent a full git clone (not worktree), no check pipeline, and no merge gate. Produces reports/proposals rather than commits. Useful for large codebase analysis, documentation drafting, or investigative spikes.
- **Chronicle archival** — `lt chronicle archive --before <date>` compresses old JSONL events into a summary SQLite record, moving detailed per-step events to a cold archive. Prevents event log bloat on long-running projects.

### v1.2 — GitHub Integration
- Map local Plans → GitHub Milestones
- Map local Tasks → GitHub Issues (label-based sync)
- Open PRs instead of (or in addition to) local merge
- Sync CI/CD check results back into Chronicle
- Optional auto-merge for low-risk categories

### v2
- Distributed runners (multiple machines)
- Model-agnostic execution profiles (not just Claude)
- IDE plugin (VSCode extension)
- Team mode (RBAC, shared daemon)

---

## Key Differences from Gastown

| Aspect | Gastown | Loguetown |
|---|---|---|
| Language | Go (75k LOC) | TypeScript (monorepo, starts lean) |
| Task queue | Git-backed Beads | Local SQLite tasks; GitHub Issues in v1.2 |
| Agent config | Code-defined roles | Hot-reloadable YAML Charters + user-managed role files |
| Skills | None | Role-scoped *.md files, vector-retrieved per task |
| Memory | Implicit in-context | 4-layer chunked store (episodic, semantic local/global, working); vector search; pluggable provider |
| A2A comms | tmux / informal | Typed Dispatch envelopes; daemon-validated |
| Tracing | None | Chronicle: JSONL + SQLite index; full GUI trace |
| Merge control | Not specified | Explicit merge gate: checks + review + human approval |
| Check pipelines | Not specified | Configurable per-project check pipeline |
| GUI | None | Full React dashboard: DAG, timeline, diff, memory |
| Process model | tmux sessions | Daemon + Runner subprocesses; no tmux dependency |
| DB | Dolt (git-for-data) | SQLite + JSONL (zero-infra) |
| Human-in-the-loop | Minimal | Explicit approval gate; human can comment/override |
| Local vs cloud | Cloud-first | Local-first; GitHub sync deferred to v1.2 |

---

## Open Questions

1. **Embedding model cold start** — `@xenova/transformers` downloads the model on first use (~23MB). Options: (a) download at `lt init`, (b) lazy download with a progress bar, (c) ship the model file in the npm package (too large). Recommended: download at `lt init` and cache in `~/.loguetown/models/`.

2. **Memory chunk granularity** — How large should each chunk be? Too large → imprecise retrieval. Too small → low coherence. Recommended starting heuristic: one H2 section per chunk (split on `##` headings). Provide a `lt memory split <file>` command to help users restructure large files.

3. **Episodic memory noise** — If every run proposes episodic memories, the store fills with low-signal entries. Mitigation: require Reviewer approval before promoting to `active`; set retention limits (`max_entries`, `max_days`) in config.

4. **Concurrent claim racing** — Two Runners could theoretically claim the same task if the scheduler races. Mitigation: all task status transitions are SQLite transactions with `WHERE status = 'todo'` guards; only one will win.

5. **Human interruption mid-run** — A human can send a `HUMAN_COMMENTED` event via GUI while a Runner is active. Runner polls the Chronicle for interruption events between tool calls.

6. **Planner hallucinating bad deps** — The DAG from the Planner may have incorrect dependency edges. The dry-run mode (`lt run --dry-run`) lets the user review and edit the plan before execution starts.

7. ~~**Cross-project semantic_global isolation**~~ — **Resolved.** `semantic_global` is stored at `~/.loguetown/memory/global/semantic_global/` and is intentionally cross-project. `semantic_local` and `episodic` are project-local (`.loguetown/memory/`). If a chunk is project-specific, agents must use `semantic_local`. Agents are instructed to choose the right layer via their role charter; the session builder retrieves both without mixing them. Global skills follow the same pattern: `~/.loguetown/skills/global/` is cross-project; `.loguetown/skills/shared/` is project-local.

8. **Chronicle event log growth** — For active projects, JSONL files grow unboundedly. The `lt chronicle archive` command (v1.1) compresses old events, but the threshold for what counts as "old" needs design: (a) archive everything older than N days, (b) archive all events from completed plans, (c) let the user decide. Recommended: archive by completed plan (natural unit), keeping the last 3 completed plans in the hot log.

9. **Integration branch + restricted_paths** — If an integration branch touches `restricted_paths`, should the restriction apply to each child task merge (into the integration branch) or only to the final land to `main`? Recommended: apply `restricted_paths` only at final land — the integration branch is an intermediate staging area, not `main`.

10. **Notification debouncing** — If 10 tasks fail in rapid succession, the patrol loop should not fire 10 desktop notifications. Recommend: batch all notifications from a single patrol cycle into one summary alert ("3 tasks need human attention, 1 critical escalation").
