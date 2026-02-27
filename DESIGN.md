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
    claude.py              # ClaudeCodeRuntime — tmux sessions
  isolation/
    protocol.py            # Isolator protocol, IsolatedEnv
    worktree.py            # GitWorktreeIsolator
```

9 source files. That's it.

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

v1 implementations: `ClaudeCodeRuntime` (default) — spawns `claude` in tmux.
Future: `CodexRuntime`, `OpenHandsRuntime`.

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
    orchestrator_role: str | None = None
    allowed_roles: list[str] | None = None   # None = all
    max_depth: int = 3
    claude_model: str | None = None
```

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
role = "team-lead"           # strawhub role slug (optional)

[policy]
allowed_roles = ["implementer", "reviewer", "fixer"]
max_depth = 3

[claude]
model = "claude-sonnet-4-6"
```

---

## Flows

### `strawpot start`

```
1. working_dir = os.getcwd()
2. config = load_config(working_dir)
3. runtime = resolve_runtime(config.runtime)     # claude_code | codex | openhands
4. isolator = resolve_isolator(config.isolation)  # worktree | docker
5. session = Session(config, runtime, isolator)
6. session.start():
   a. run_id = "run_" + uuid4()
   b. Create session worktree:
      env = isolator.create(session_id=run_id, base_dir=working_dir)
      → git worktree add .strawpot/worktrees/<run_id> -b strawpot/<run_id>
      All agents will work in env.path from here on.
   c. Start DenDenServer(addr=config.denden_addr)
      - server.on_delegate(self._handle_delegate)
      - server.on_ask_user(self._handle_ask_user)
      - run in background thread
   d. If config.orchestrator_role:
        resolved = resolve(slug, kind="role")
        system_prompt = build_prompt(resolved)
      Else:
        system_prompt = minimal default
   e. agent_id = "agent_" + uuid4()
   f. runtime.spawn(
        agent_id=agent_id,
        working_dir=env.path,           # orchestrator works in session worktree
        system_prompt=system_prompt,
        task="",                        # interactive mode
        env={
          DENDEN_ADDR: config.denden_addr,
          DENDEN_AGENT_ID: agent_id,
          DENDEN_RUN_ID: run_id,
        }
      )
   g. Write .strawpot/runtime/session.json
   h. Attach user to tmux session (if runtime supports it)
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
     agent_id, self.worktree.path, system_prompt, task_text,
     env={DENDEN_ADDR, DENDEN_AGENT_ID, DENDEN_PARENT_AGENT_ID, DENDEN_RUN_ID}
   )
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

## Skill & Role Management

Strawpot delegates all skill/role management to the `strawhub` CLI.
No wrapper, no reimplementation — just passthrough:

```
strawpot install skill <slug>     →  strawhub install skill <slug>
strawpot install role <slug>      →  strawhub install role <slug>
strawpot uninstall skill <slug>   →  strawhub uninstall skill <slug>
strawpot uninstall role <slug>    →  strawhub uninstall role <slug>
strawpot search <query>           →  strawhub search <query>
strawpot list                     →  strawhub list
```

At runtime (delegation), strawpot calls `strawhub.resolver.resolve()` directly
as a Python import to resolve role + skill paths for prompt building.

---

## ClaudeCodeRuntime (`agents/claude.py`)

```
spawn(agent_id, working_dir, system_prompt, task, env):
  1. Write system_prompt to .strawpot/runtime/<agent_id>.prompt.md
  2. Build command:
     - Interactive (orchestrator): claude --system-prompt <file>
     - Non-interactive (sub-agent): claude -p "<task>" --system-prompt <file>
  3. tmux new-session -d -s strawpot-<agent_id[:8]> -c <working_dir> <cmd>
  4. Return AgentHandle with tmux session name in metadata

wait(handle):
  Poll tmux has-session until session exits. Read output.

is_alive(handle):
  tmux has-session -t <session_name> → returncode == 0

kill(handle):
  tmux kill-session -t <session_name>
```

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
strawpot start  [--role SLUG] [--runtime claude_code|codex|openhands]
                [--isolation worktree|docker] [--host HOST] [--port PORT]
strawpot config

# Passthrough to strawhub CLI:
strawpot install skill <slug>
strawpot install role <slug>
strawpot uninstall skill <slug>
strawpot uninstall role <slug>
strawpot search <query>
strawpot list
```

`start` runs in the foreground — on exit (Ctrl+C or agent quit), the session
cleans up automatically (kill sub-agents, remove worktree, stop denden).
No separate `stop`/`status`/`agents` commands needed.

---

## Implementation Order

1. `config.py`
2. `agents/protocol.py` + `isolation/protocol.py`
3. `isolation/worktree.py`
4. `context.py`
5. `agents/claude.py`
6. `delegation.py`
7. `session.py`
8. `cli.py` + `__main__.py`

---

## Future Extensions

- **Docker isolation** — `DockerIsolator` implementing the same protocol
- **Codex / OpenHands runtimes** — implementing `AgentRuntime` protocol
- **Automation inputs** — GitHub issue watcher, email, Telegram → feed tasks to orchestrator
- **Web GUI** — read session state + denden status, display agent tree
