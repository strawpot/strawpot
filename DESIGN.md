# Strawpot — Design

Lightweight CLI for agent orchestration. Strawpot is the glue between
[Denden](https://github.com/user/denden) (gRPC agent ↔ orchestrator transport)
and [StrawHub](https://strawhub.dev) (skill & role registry).

```
User
 │
 ▼
strawpot start          ← CLI entry point, CWD = working dir
 │
 ├─ Create worktree     ← one worktree per session, shared by all agents
 │
 ├─ DenDen gRPC server  ← listens on 127.0.0.1:9700
 │
 └─ Orchestrator agent   ← "hive mind" (Claude Code / Codex / OpenHands)
      │                     runtime is user's choice, default: claude_code
      │  denden send '{"delegate": ...}'
      ▼
    Strawpot handles delegate:
      1. Policy check (role allowed? depth limit?)
      2. Resolve role + skills (strawhub.resolver)
      3. Spawn sub-agent in the session worktree (shared)
      4. Wait for completion
      5. Return result to caller
      │
      ├─ Sub-agent A (same worktree, implementer role)
      │    └─ can also delegate via denden
      │
      └─ Sub-agent B (same worktree, reviewer role)
```

All agents in a session share the same worktree. This keeps things simple —
no merge conflicts between worktrees, agents can see each other's changes,
and cleanup is a single `git worktree remove`.

---

## Package Structure

```
src/strawpot/
  __init__.py              # __version__
  __main__.py              # python -m strawpot
  cli.py                   # click CLI: strawpot start/config + strawhub passthrough
  config.py                # TOML config loading (stdlib tomllib)
  session.py               # Session lifecycle — owns denden server + agent registry
  delegation.py            # Delegate handler — policy → resolve → spawn → wait
  context.py               # Build system prompt from resolved role + skills
  agents/
    protocol.py            # AgentRuntime protocol, AgentHandle, AgentResult
    registry.py            # Discover agent.toml, validate config, resolve wrapper
    wrapper.py             # WrapperRuntime — calls any wrapper CLI via subprocess
  isolation/
    protocol.py            # Isolator protocol, IsolatedEnv
    worktree.py            # GitWorktreeIsolator
  _builtin_agents/         # Ships with strawpot
    claude_code/
      agent.toml           # Built-in Claude Code wrapper manifest
      wrapper.py           # Built-in wrapper script
```

11 source files + 1 built-in agent. No agent-specific code in the core.

---

## Dependencies

```toml
[project]
name = "strawpot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "denden",
    "strawhub",
    "click>=8.1",
]

[project.scripts]
strawpot = "strawpot.cli:cli"
```

Config uses `tomllib` (stdlib 3.11+). IDs use `uuid` (stdlib). Subprocesses
use `subprocess` (stdlib). No other deps.

---

## Types

### AgentRuntime (`agents/protocol.py`)

```python
@dataclass
class AgentHandle:
    agent_id: str
    runtime_name: str
    pid: int | None = None
    metadata: dict = field(default_factory=dict)

@dataclass
class AgentResult:
    summary: str
    output: str = ""
    exit_code: int = 0

class AgentRuntime(Protocol):
    name: str
    def spawn(self, *, agent_id, working_dir, system_prompt, task, env) -> AgentHandle: ...
    def wait(self, handle: AgentHandle, timeout: float | None = None) -> AgentResult: ...
    def is_alive(self, handle: AgentHandle) -> bool: ...
    def kill(self, handle: AgentHandle) -> None: ...
```

The runtime is the user's choice via config or `--runtime` flag.

Only one implementation lives in strawpot core: `WrapperRuntime` (`agents/wrapper.py`).
It calls any wrapper CLI that implements the agent wrapper protocol (see below).
Agent-specific logic lives entirely in wrapper CLIs, never in strawpot.

### Agent Wrapper Protocol

Every agent wrapper CLI must implement four subcommands with these standard
protocol args. The wrapper translates them to the underlying agent's native
flags.

**Protocol args** (required by all wrappers):

| Arg | Description |
|---|---|
| `--agent-id ID` | Unique agent identifier |
| `--working-dir DIR` | Session worktree path |
| `--system-prompt FILE` | Path to system prompt markdown |
| `--task TEXT` | Task text (empty string = interactive) |
| `--skills-dir DIR` | Path to resolved skills directory |
| `--approval-mode MODE` | `force` \| `suggest` \| `auto` |
| `--config JSON` | Agent-specific extras as JSON blob |
| `--env KEY=VAL` | Additional env vars (repeatable) |

**Subcommands:**

```
<wrapper> spawn  <protocol args>
  → stdout JSON: {"pid": 1234, "metadata": {"session": "strawpot-ab12"}}

<wrapper> wait   --agent-id ID [--timeout SECS]
  → stdout JSON: {"summary": "...", "output": "...", "exit_code": 0}

<wrapper> alive  --agent-id ID
  → stdout JSON: {"alive": true}

<wrapper> kill   --agent-id ID
  → stdout JSON: {"killed": true}
```

The wrapper CLI can be named anything — `claude-agent`, `my-codex-wrapper`,
`openhands-runner`. The `agent.toml` manifest declares which command to call.

### Agent Manifest (`agent.toml`)

Each agent is a folder with a manifest describing the wrapper and its config:

```toml
[agent]
name = "claude-code"
version = "0.1.0"
description = "Claude Code agent via tmux"

[agent.wrapper]
# Bundled script (relative to agent folder):
script = "wrapper.py"
# OR external CLI on PATH:
# command = "claude-agent"

# Agent-specific config — NOT protocol args.
# These are extras that vary per agent implementation.
[config]
model = { type = "string", default = "claude-sonnet-4-6", description = "Claude model" }

# Required environment variables — validated at startup.
[config.env]
ANTHROPIC_API_KEY = { required = true, description = "Anthropic API key" }
```

Two wrapper delivery modes:

- `script = "wrapper.py"` — bundled in the agent folder, strawpot runs it
  as `python <agent_dir>/wrapper.py spawn ...`. Zero install, just download
  the folder.
- `command = "claude-agent"` — external CLI on PATH, installed however the
  provider wants (pip, cargo, npm, brew).

### Agent Registry (`agents/registry.py`)

Resolves an agent name to a loaded manifest + wrapper command:

```python
@dataclass
class AgentSpec:
    name: str
    version: str
    wrapper_cmd: list[str]   # e.g. ["python", "/path/to/wrapper.py"]
    config: dict             # merged from agent.toml defaults + user config
    env_schema: dict         # required env vars from [config.env]

def resolve_agent(name: str, project_dir: str) -> AgentSpec:
    """
    Resolution order:
    1. .strawpot/agents/<name>/agent.toml    (project-local)
    2. ~/.strawpot/agents/<name>/agent.toml  (global install)
    3. built-in _builtin_agents/<name>/      (ships with strawpot)
    """
```

### WrapperRuntime (`agents/wrapper.py`)

Single generic runtime that delegates to any wrapper CLI:

```python
class WrapperRuntime:
    """Implements AgentRuntime by calling wrapper CLI subcommands."""

    def __init__(self, spec: AgentSpec): ...

    def spawn(self, *, agent_id, working_dir, system_prompt, task, env) -> AgentHandle:
        cmd = [*self.spec.wrapper_cmd, "spawn",
               "--agent-id", agent_id,
               "--working-dir", working_dir,
               "--system-prompt", system_prompt,
               "--task", task,
               "--skills-dir", env.get("SKILLS_DIR", ""),
               "--approval-mode", env.get("APPROVAL_MODE", "suggest"),
               "--config", json.dumps(self.spec.config)]
        result = subprocess.run(cmd, capture_output=True)
        data = json.loads(result.stdout)
        return AgentHandle(agent_id=agent_id, pid=data.get("pid"),
                           runtime_name=self.spec.name, metadata=data.get("metadata", {}))

    def wait(self, handle, timeout=None) -> AgentResult:
        cmd = [*self.spec.wrapper_cmd, "wait", "--agent-id", handle.agent_id]
        if timeout: cmd += ["--timeout", str(timeout)]
        result = subprocess.run(cmd, capture_output=True)
        data = json.loads(result.stdout)
        return AgentResult(**data)
```

No agent-specific code. One class handles all agents.

### Isolator (`isolation/protocol.py`)

Creates one isolated environment per **session** (not per agent).
All agents — orchestrator and sub-agents — work in the same directory.

```python
@dataclass
class IsolatedEnv:
    path: str
    branch: str | None = None

class Isolator(Protocol):
    def create(self, *, session_id: str, base_dir: str) -> IsolatedEnv: ...
    def cleanup(self, env: IsolatedEnv) -> None: ...
```

v1 implementation: `GitWorktreeIsolator`.
Future: `DockerIsolator`.

### Config (`config.py`)

```python
@dataclass
class StrawpotConfig:
    runtime: str = "claude_code"
    isolation: str = "worktree"
    denden_addr: str = "127.0.0.1:9700"
    orchestrator_role: str = "orchestrator"
    allowed_roles: list[str] | None = None   # None = all
    max_depth: int = 3
    agents: dict[str, dict] = field(default_factory=dict)  # per-agent extras
```

`agents` holds agent-specific config keyed by agent name. These are extras
beyond the standard protocol args — model, temperature, custom endpoints, etc.
Passed as `--config JSON` to the wrapper.

Loaded from (later overrides earlier):
1. Built-in defaults
2. `$STRAWPOT_HOME/config.toml` (global — defaults to `~/.strawpot/`)
3. `.strawpot/config.toml` (project-level, in CWD)
4. CLI flags

Environment variables:
- `STRAWPOT_HOME` — global config/data directory (default: `~/.strawpot/`).
  Also used by `strawhub` CLI for skill/role install paths.

---

## Config Format

```toml
# .strawpot/config.toml
runtime = "claude_code"
isolation = "worktree"

[denden]
addr = "127.0.0.1:9700"

[orchestrator]
role = "team-lead"           # strawhub role slug (default: "orchestrator")

[policy]
allowed_roles = ["implementer", "reviewer", "fixer"]
max_depth = 3

# Agent-specific extras — keyed by agent name.
# Only for config beyond the standard protocol args.
[agents.claude_code]
model = "claude-sonnet-4-6"

[agents.my_custom_agent]
endpoint = "https://api.custom.dev"
temperature = 0.7
```

---

## Flows

### `strawpot start`

```
1. working_dir = os.getcwd()
2. config = load_config(working_dir)
3. agent_spec = resolve_agent(config.runtime, working_dir)  # registry lookup
   → validates [config.env] (fail fast if required env vars missing)
   → merges config.agents[name] into spec.config
4. runtime = WrapperRuntime(agent_spec)                     # generic, works for any agent
5. isolator = resolve_isolator(config.isolation)             # worktree | docker
6. session = Session(config, runtime, isolator)
7. session.start():
   a. run_id = "run_" + uuid4()
   b. Create session worktree:
      env = isolator.create(session_id=run_id, base_dir=working_dir)
      → git worktree add .strawpot/worktrees/<run_id> -b strawpot/<run_id>
      All agents will work in env.path from here on.
   c. Start DenDenServer(addr=config.denden_addr)
      - server.on_delegate(self._handle_delegate)
      - server.on_ask_user(self._handle_ask_user)
      - run in background thread
   d. Resolve orchestrator role + skills:
        resolved = resolve(config.orchestrator_role, kind="role")
        system_prompt = build_prompt(resolved)
        → writes prompt to .strawpot/runtime/<agent_id>.prompt.md
   e. agent_id = "agent_" + uuid4()
   f. runtime.spawn(
        agent_id=agent_id,
        working_dir=env.path,
        system_prompt=prompt_file,       # path to written prompt
        task="",                         # interactive mode
        env={
          DENDEN_ADDR: config.denden_addr,
          DENDEN_AGENT_ID: agent_id,
          DENDEN_RUN_ID: run_id,
        }
      )
      → WrapperRuntime calls: <wrapper> spawn --agent-id ... --working-dir ...
        --system-prompt ... --task "" --skills-dir ... --approval-mode ...
        --config '{"model": "..."}' --env DENDEN_ADDR=... --env DENDEN_AGENT_ID=...
   g. Write .strawpot/runtime/session.json
   h. Attach user to tmux session (if wrapper metadata includes session name)
```

### Delegate Request

Any agent calls `denden send '{"delegate": {"delegate_to": "implementer", "task": {"text": "..."}}}'`.
Denden server dispatches to `Session._handle_delegate`:

```
1. Extract: role_slug, task_text, parent_agent_id, run_id from request
2. Policy check:
   - role_slug in allowed_roles?  → DENY_ROLE_NOT_ALLOWED
   - depth > max_depth?           → DENY_DEPTH_LIMIT
3. Resolve:
   resolved = strawhub.resolver.resolve(role_slug, kind="role")
   → {slug, version, path, dependencies: [{slug, kind, path}, ...]}
4. Build prompt:
   system_prompt = context.build_prompt(resolved)
   → reads SKILL.md bodies (deps first) + ROLE.md body
5. Spawn in session worktree (shared — no new worktree):
   handle = runtime.spawn(
     agent_id, self.worktree.path, system_prompt_file, task_text,
     env={DENDEN_ADDR, DENDEN_AGENT_ID, DENDEN_PARENT_AGENT_ID, DENDEN_RUN_ID}
   )
   → WrapperRuntime calls wrapper CLI with standard protocol args
6. Wait:
   result = runtime.wait(handle)
   (blocks — denden threadpool allows concurrent delegates)
7. Return:
   ok_response(request_id, delegate_result=DelegateResult(summary=result.summary))
```

No per-agent worktree creation or cleanup. All agents share the session worktree.

### ask_user Request

Agent calls `denden send '{"ask_user": {"question": "which db?", "choices": ["postgres", "sqlite"]}}'`.
Forwarded to the user via the orchestrator's terminal. Orchestrator's response
flows back through denden.

---

## Context Building (`context.py`)

`build_prompt(resolved)` reads the resolved role and its dependencies:

```
## Skill: git-workflow

<contents of git-workflow SKILL.md body>

---

## Skill: code-review

<contents of code-review SKILL.md body>

---

## Role: implementer

<contents of implementer ROLE.md body>
```

Dependencies come first (topological order from resolver), role last.
Only the markdown body is included — frontmatter is stripped.

---

## Skill, Role, Agent & Memory Management

Strawpot delegates all package management to the `strawhub` CLI.
Agents and memory providers are package types alongside skills and roles.
No wrapper, no reimplementation — just passthrough:

```
strawpot install skill <slug>     →  strawhub install skill <slug>
strawpot install role <slug>      →  strawhub install role <slug>
strawpot install agent <slug>     →  strawhub install agent <slug>
strawpot install memory <slug>    →  strawhub install memory <slug>
strawpot uninstall skill <slug>   →  strawhub uninstall skill <slug>
strawpot uninstall role <slug>    →  strawhub uninstall role <slug>
strawpot uninstall agent <slug>   →  strawhub uninstall agent <slug>
strawpot uninstall memory <slug>  →  strawhub uninstall memory <slug>
strawpot search <query>           →  strawhub search <query>
strawpot list                     →  strawhub list
```

At runtime (delegation), strawpot calls `strawhub.resolver.resolve()` directly
as a Python import to resolve role + skill paths for prompt building.

### Agent Installation Layout

Agents install to `$STRAWPOT_HOME/agents/<name>/` (default: `~/.strawpot/agents/`):

```
~/.strawpot/agents/
  claude_code/
    agent.toml        # manifest: wrapper command, config schema, env requirements
    wrapper.py        # bundled wrapper script (if script= mode)
  codex/
    agent.toml
    wrapper.py
  my_custom_agent/
    agent.toml        # may point to external CLI via command=
```

Project-local agents can also be placed at `.strawpot/agents/<name>/` and take
precedence over global installs.

### Writing a Wrapper

A wrapper is any CLI that implements the four subcommands (`spawn`, `wait`,
`alive`, `kill`) with the standard protocol args. Minimal example in Python:

```python
#!/usr/bin/env python3
"""Minimal wrapper — runs a command in a subprocess."""
import argparse, json, subprocess, os

def spawn(args):
    proc = subprocess.Popen(
        [args.config["command"], args.task],
        cwd=args.working_dir,
        env={**os.environ, **dict(e.split("=", 1) for e in args.env)},
    )
    print(json.dumps({"pid": proc.pid, "metadata": {}}))

def wait(args):
    pid = int(open(f"/tmp/strawpot-{args.agent_id}.pid").read())
    os.waitpid(pid, 0)
    print(json.dumps({"summary": "done", "output": "", "exit_code": 0}))

# ... alive, kill similarly
```

Wrapper authors only need to care about translating protocol args to their
agent's native interface. Strawpot handles everything else.

---

## Built-in Agent: claude_code

Ships with strawpot at `_builtin_agents/claude_code/`. Serves as the default
runtime and as a reference implementation for wrapper authors.

### `agent.toml`

```toml
[agent]
name = "claude_code"
version = "0.1.0"
description = "Claude Code agent via tmux"

[agent.wrapper]
script = "wrapper.py"

[config]
model = { type = "string", default = "claude-sonnet-4-6", description = "Claude model" }

[config.env]
ANTHROPIC_API_KEY = { required = true, description = "Anthropic API key" }
```

### `wrapper.py`

The wrapper translates standard protocol args to Claude Code CLI flags:

```
spawn:
  1. Read --config JSON → extract model
  2. Read --skills-dir → glob SKILL.md files → --append-system-prompt for each
  3. Read --approval-mode → map to --permission-mode
  4. Build claude command:
     - Interactive (task=""): claude --system-prompt <file> [--model M]
     - Non-interactive:      claude -p "<task>" --system-prompt <file> [--model M]
  5. tmux new-session -d -s strawpot-<agent_id[:8]> -c <working_dir> <cmd>
  6. stdout: {"pid": <tmux server pid>, "metadata": {"session": "strawpot-ab12"}}

wait:
  Poll tmux has-session until session exits. Capture pane output.
  stdout: {"summary": "...", "output": "...", "exit_code": 0}

alive:
  tmux has-session -t <session> → {"alive": true|false}

kill:
  tmux kill-session -t <session> → {"killed": true}
```

This is the only place that knows about `claude` CLI flags or tmux.
Strawpot core never imports or references it directly — the registry
discovers it via `agent.toml`.

---

## GitWorktreeIsolator (`isolation/worktree.py`)

Creates one worktree per session. Called once at `session.start()`,
cleaned up once at `session.stop()`.

```
create(session_id, base_dir):
  path = .strawpot/worktrees/<session_id>
  branch = strawpot/<session_id[:12]>
  git worktree add <path> -b <branch>
  return IsolatedEnv(path, branch)

cleanup(env):
  git worktree remove <path> --force
  git branch -D <branch>
```

`.strawpot/worktrees/` is gitignored.

---

## Session State

Written to `.strawpot/runtime/session.json` (gitignored) for crash recovery
and debugging:

```json
{
  "run_id": "run_abc123",
  "runtime": "claude_code",
  "denden_addr": "127.0.0.1:9700",
  "denden_pid": 12345,
  "worktree": ".strawpot/worktrees/run_abc123",
  "worktree_branch": "strawpot/run_abc123",
  "orchestrator_agent_id": "agent_xyz",
  "started_at": "2026-02-27T10:00:00Z",
  "agents": {}
}
```

---

## CLI

```
strawpot start  [--role SLUG] [--runtime NAME]
                [--isolation worktree|docker] [--host HOST] [--port PORT]
strawpot config

# Passthrough to strawhub CLI:
strawpot install skill <slug>
strawpot install role <slug>
strawpot install agent <slug>
strawpot install memory <slug>
strawpot uninstall skill <slug>
strawpot uninstall role <slug>
strawpot uninstall agent <slug>
strawpot uninstall memory <slug>
strawpot search <query>
strawpot list
```

`--runtime NAME` accepts any agent name resolvable by the registry (project-local,
global install, or built-in). Not limited to a hardcoded list.

`start` runs in the foreground — on exit (Ctrl+C or agent quit), the session
cleans up automatically (kill sub-agents, remove worktree, stop denden).
No separate `stop`/`status`/`agents` commands needed.

---

## Implementation Order

1. `config.py` — add `agents: dict` field, parse `[agents.*]` sections
2. `agents/protocol.py` + `isolation/protocol.py` — types
3. `agents/registry.py` — discover `agent.toml`, validate env, merge config
4. `agents/wrapper.py` — `WrapperRuntime` (calls wrapper CLI via subprocess)
5. `_builtin_agents/claude_code/` — `agent.toml` + `wrapper.py`
6. `isolation/worktree.py`
7. `context.py`
8. `delegation.py`
9. `session.py`
10. `cli.py` + `__main__.py` — add `install/uninstall agent` passthrough

---

## Memory (Planned)

Installable memory providers that strawpot queries before spawning an agent
(`memory.get`) and writes to after the agent completes (`memory.dump`).
Memory follows the same installable-package pattern as agents — a folder with
a manifest, managed by strawhub.

### Memory Types

| Type | Abbr | Description |
|---|---|---|
| Procedural Memory | PM | Role-specific instructions, patterns, runbooks |
| Semantic Memory | SM | Workspace facts (global) + project conventions |
| Short-Term Memory | STM | Session/agent-scoped scratchpad, TTL-based |
| Retrieval Memory | RM | Hinted retrieval — triggered only when relevant |
| Event Memory | EM | Append-only event log (agent runs, tool calls, results) |

### Hooks in Delegation Flow

Memory wraps the existing spawn/wait cycle. Two calls per agent:

```
Delegate flow (updated):
  1. Policy check
  2. Resolve role + skills
  3. memory.get(...)          ← NEW: before spawn
     → returns context_cards + control_signals
  4. Build prompt (role + skills + context_cards)
  5. Spawn agent
  6. Wait for result
  7. memory.dump(...)         ← NEW: after completion
     → appends to EM, updates STM, proposes SM/RM
  8. Return result
```

### `memory.get` — Before Every Agent

Strawpot calls the memory provider to retrieve relevant context before
building the agent's prompt.

```
Inputs:
  worktree_id
  agent_instance_id
  parent_agent_instance_id    (optional)
  role
  behavior_ref                (Agent.md / ROLE.md path)
  task_text
  budget                      (token budget hint)

Outputs:
  context_cards               (typed: PM/SM/STM/RM)
  control_signals             (risk level, suggested next, policy flags)
  context_hash + sources_used (receipt for traceability)
```

**Retrieval order** (default):
1. PM — role bundle (instructions for this role)
2. RM — hint-triggered retrieval (only if relevant)
3. SM — workspace-scoped facts
4. SM — global invariants (minimal)
5. STM — global + agent-scoped scratchpad

No conversation history passed by the orchestrator. The memory provider
decides what context is relevant.

### `memory.dump` — After Every Agent

Strawpot calls the memory provider to record what happened.

```
Inputs:
  worktree_id
  agent_instance_id
  parent_agent_instance_id    (optional)
  role
  task_text
  assistant_output
  tool_trace                  (strongly recommended)
  artifacts                   (commit hash, patch refs, test reports)
  status                      (success/failure/timeout)

Outputs (mandatory receipt):
  em_event_ids                (appended event IDs or count)
  stm_updates                 (what changed in short-term memory)
  sm_rm_proposals             (proposed commits + reasons)
  deferred_items              (queued for review)
```

**Routing rules:**
- EM: always append (never gate)
- STM: always update (TTL-based expiry)
- SM/RM: propose → gate → commit or defer
- PM: never auto-commit; always defer to eval/review

### Memory Provider Protocol

Same pattern as agent wrappers — a CLI that implements a contract:

```
<provider> get  --worktree-id ID --agent-id ID --role SLUG \
                --behavior-ref FILE --task TEXT --budget N \
                [--parent-agent-id ID]
  → stdout JSON: {"context_cards": [...], "control_signals": {...},
                   "context_hash": "...", "sources_used": [...]}

<provider> dump --worktree-id ID --agent-id ID --role SLUG \
                --task TEXT --status STATUS \
                --output FILE --tool-trace FILE \
                [--parent-agent-id ID] [--artifacts JSON]
  → stdout JSON: {"em_event_ids": [...], "stm_updates": [...],
                   "sm_rm_proposals": [...], "deferred": [...]}
```

### Memory Manifest (`memory.toml`)

```toml
[memory]
name = "strawpot-memory-local"
version = "0.1.0"
description = "File-based local memory provider"

[memory.wrapper]
script = "wrapper.py"
# OR: command = "strawpot-memory-local"

[config]
storage_dir = { type = "string", default = ".strawpot/memory" }
em_max_events = { type = "int", default = 10000 }

[config.env]
# e.g. for a vector-db-backed provider:
# PINECONE_API_KEY = { required = true }
```

Installed to `~/.strawpot/memory/<name>/`, resolved the same way as agents:
project-local → global → built-in.

### EM Event Schema

Every event in the append-only event log:

```json
{
  "worktree_id": "run_abc123",
  "agent_instance_id": "agent_xyz",
  "parent_agent_instance_id": null,
  "role": "implementer",
  "event_type": "AGENT_RESULT",
  "payload": {},
  "timestamp": "2026-02-27T10:05:00Z"
}
```

Event types: `AGENT_STARTED`, `MEMORY_GET_USED`, `TOOL_CALL`, `TOOL_RESULT`,
`AGENT_RESULT`, `MEMORY_DUMP_RECEIPT`, `AGENT_SPAWN_REQUESTED`, `AGENT_SPAWNED`.

### Config

```toml
# .strawpot/config.toml
memory = "strawpot-memory-local"   # provider name (default: none/disabled)

[memory_config]
storage_dir = ".strawpot/memory"
```

Memory is optional. When no provider is configured, strawpot skips the
`memory.get`/`memory.dump` calls and the delegation flow works as before.

### Installation

```
strawpot install memory <slug>     →  strawhub install memory <slug>
strawpot uninstall memory <slug>   →  strawhub uninstall memory <slug>
```

---

## Future Extensions

- **Docker isolation** — `DockerIsolator` implementing the same protocol
- **Community agent wrappers** — anyone can publish a wrapper to strawhub registry
- **Agent providers** — third-party providers ship CLIs that implement the wrapper protocol
- **Memory providers** — vector-DB backed, cloud-synced, or team-shared memory implementations
- **Automation inputs** — GitHub issue watcher, email, Telegram → feed tasks to orchestrator
- **Web GUI** — read session state + denden status, display agent tree + EM replay
