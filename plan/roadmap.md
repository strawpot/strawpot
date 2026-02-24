# Loguetown — Roadmap

## Implementation Phases

### Phase 1 — Foundation
- [x] Python project setup (`pyproject.toml`, `setuptools`, dev extras)
- [x] Agent Charter YAML: `Charter.from_yaml()` / `to_yaml()`; `ModelConfig`
- [x] Provider protocols: `AgentProvider` (API/completions) + `AgentSessionProvider` (tmux sessions)
- [x] `ClaudeSessionProvider`: spawns `claude --dangerously-skip-permissions` in tmux; writes `.claude/settings.json`
- [x] `ClaudeAPIProvider`: `AsyncAnthropic` SDK completions
- [x] `SkillPool` + `SkillManager`: pool resolver (global / project / agent)
- [x] `ContextBuilder` + `SessionContext`: pool path table + CLAUDE.md instruction
- [x] `lt prime --hook`: SessionStart context injection
- [ ] SQLite schema + migrations (`memory_chunks`, Chronicle, tasks, runs, plans)
- [ ] JSONL Chronicle writer (append + SQLite index)
- [ ] Role YAML loader and registry (`lt role list/create/edit`)
- [ ] Basic CLI: `lt init`, `lt role create`, `lt agent create`, `lt agent list`

### Phase 2 — Skills CLI
- [ ] `lt skills install/remove` — scaffold and delete skill module directories; default project scope, `--global` / `--agent <name>` flags for other scopes
- [ ] `lt skills list` — enumerate all skill modules across the three pool scopes (cumulative: default = global+project, `--agent` = all three)
- [ ] `lt skills edit/show` — open skill module in `$EDITOR` or print content
- [ ] Project context resolution: walk up from CWD for `.loguetown/`; `$LT_WORKDIR` env override

### Phase 3 — Single Agent Runtime
- [ ] Session builder: role → skill pool paths (agent-discovered) → system prompt
- [ ] Model provider registry: Claude provider (default), OpenAI provider, Ollama provider
- [ ] Runner executor loop with selected model provider
- [ ] Git worktree create/cleanup
- [ ] `lt agent spawn` single-task execution loop

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
- [ ] Agents screen — management: create/edit agent (Charter YAML editor), skill pool browser, session log, inbox
- [ ] Roles & Skills screen — management: role YAML editor, skill module browser (Monaco), new-skill scaffold
- [ ] Chat screen — conversation list, orchestrator chat, per-agent chat with full transcript + tool-call rendering + context panel
- [ ] `conversations` + `conversation_turns` REST endpoints (`GET/POST /conversations`, `POST /conversations/:id/turns`)

### Phase 8 — Polish
- [ ] `lt run --dry-run` plan preview
- [ ] GUI auth (token-based for remote access)
- [ ] Failure summary artifact generation

---

## Extensibility Roadmap

### v1.1
- Better diff UI: file tree, syntax highlighting, inline blame
- Interactive step approval ("pause before commit" mode)
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
| Language | Go (75k LOC) | Python 3.11+ (starts lean) |
| Task queue | Git-backed Beads | Local SQLite tasks; GitHub Issues in v1.2 |
| Agent config | Code-defined roles | Hot-reloadable YAML Charters + user-managed role files |
| Skills | None | Folder-based modules (global/project/agent scopes); agent-discovered via Glob/Read; synthesised into CLAUDE.md |
| Memory | Implicit in-context | Managed as skills — agents write learned knowledge into skill modules |
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

1. **Concurrent claim racing** — Two Runners could theoretically claim the same task if the scheduler races. Mitigation: all task status transitions are SQLite transactions with `WHERE status = 'todo'` guards; only one will win.

2. **Human interruption mid-run** — A human can send a `HUMAN_COMMENTED` event via GUI while a Runner is active. Runner polls the Chronicle for interruption events between tool calls.

3. **Planner hallucinating bad deps** — The DAG from the Planner may have incorrect dependency edges. The dry-run mode (`lt run --dry-run`) lets the user review and edit the plan before execution starts.

4. **Chronicle event log growth** — For active projects, JSONL files grow unboundedly. The `lt chronicle archive` command (v1.1) compresses old events, but the threshold for what counts as "old" needs design: (a) archive everything older than N days, (b) archive all events from completed plans, (c) let the user decide. Recommended: archive by completed plan (natural unit), keeping the last 3 completed plans in the hot log.

5. **Integration branch + restricted_paths** — If an integration branch touches `restricted_paths`, should the restriction apply to each child task merge (into the integration branch) or only to the final land to `main`? Recommended: apply `restricted_paths` only at final land — the integration branch is an intermediate staging area, not `main`.

6. **Notification debouncing** — If 10 tasks fail in rapid succession, the patrol loop should not fire 10 desktop notifications. Recommend: batch all notifications from a single patrol cycle into one summary alert ("3 tasks need human attention, 1 critical escalation").
