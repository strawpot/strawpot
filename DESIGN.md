# StrawPot — Design

Lightweight CLI for agent orchestration. StrawPot is the glue between
[Denden](https://github.com/user/denden) (gRPC agent ↔ orchestrator transport)
and [StrawHub](https://strawhub.dev) (skill & role registry).

```
User
 │
 ▼
strawpot start          ← CLI entry point, CWD = working dir
 │
 ├─ Isolate (optional)  ← none (use CWD) | worktree | docker
 │
 ├─ DenDen gRPC server  ← listens on 127.0.0.1:9700
 │
 └─ Orchestrator agent   ← "hive mind" (Claude Code / Codex / OpenHands)
      │                     runtime is user's choice, default: claude_code
      │  denden send '{"delegate": ...}'
      ▼
    StrawPot handles delegate:
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

All agents in a session share the same working directory. With `isolation=none`
(default), agents work directly in the project dir. With `isolation=worktree`,
a git worktree is created per session — agents see each other's changes and
cleanup is a single `git worktree remove`.

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
  _process.py              # Cross-platform process utilities (is_pid_alive)
  agents/
    protocol.py            # AgentRuntime protocol, AgentHandle, AgentResult
    registry.py            # Discover AGENT.md, validate config, resolve wrapper
    wrapper.py             # WrapperRuntime — calls any wrapper CLI via subprocess
    interactive.py         # InteractiveWrapperRuntime (tmux) + DirectWrapperRuntime (fallback)
  isolation/
    protocol.py            # Isolator protocol, IsolatedEnv
    worktree.py            # WorktreeIsolator
  _builtin_agents/         # Ships with strawpot
    claude_code/
      AGENT.md             # Built-in Claude Code agent manifest
      wrapper/             # Go source for wrapper binary
        main.go
        go.mod
```

13 source files + 1 built-in agent. No agent-specific code in the core.

---

## Dependencies

```toml
[project]
name = "strawpot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "click>=8.1",
    "pyyaml>=6.0",
    "strawhub",
    "denden-server",
]

[project.scripts]
strawpot = "strawpot.cli:cli"
```

Config uses `tomllib` (stdlib 3.11+). IDs use `uuid` (stdlib). Subprocesses
use `subprocess` (stdlib). The denden project has two packages: the `denden`
binary (distributed as a GitHub release) and `denden-server` (PyPI package)
which provides the `DenDenServer` Python class used by session.py.

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
    def spawn(self, *, agent_id, working_dir, agent_workspace_dir,
              role_prompt, memory_prompt, skills_dir, roles_dirs,
              task, env) -> AgentHandle: ...
    def wait(self, handle: AgentHandle, timeout: float | None = None) -> AgentResult: ...
    def is_alive(self, handle: AgentHandle) -> bool: ...
    def kill(self, handle: AgentHandle) -> None: ...
```

The runtime is the user's choice via config or `--runtime` flag.

Only one implementation lives in strawpot core: `WrapperRuntime` (`agents/wrapper.py`).
It calls any wrapper CLI that implements the agent wrapper protocol (see below).
Agent-specific logic lives entirely in wrapper CLIs, never in strawpot.

### Agent Wrapper Protocol

Every agent wrapper CLI must implement two subcommands: `setup` and `build`.
The wrapper is a pure translation layer — it maps StrawPot protocol args to
the underlying agent's native CLI flags. Process lifecycle (spawn, wait,
alive, kill) is handled internally by `WrapperRuntime` in strawpot core.

**Protocol args** (passed to `build`):

| Arg | Description |
|---|---|
| `--agent-id ID` | Unique agent identifier |
| `--working-dir DIR` | Session worktree path |
| `--agent-workspace-dir DIR` | Dedicated temp workspace for this agent (prompt files, staged skills) |
| `--role-prompt TEXT` | Role system prompt text |
| `--memory-prompt TEXT` | Memory context text |
| `--task TEXT` | Task text (empty string = interactive) |
| `--skills-dir DIR` | Parent directory containing staged skill subdirectories |
| `--roles-dir DIR` | Parent directory containing staged role subdirectories (repeatable) |
| `--config JSON` | Agent-specific extras as JSON blob |

Additional environment variables (e.g. `PERMISSION_MODE`, `DENDEN_ADDR`) are
passed as subprocess environment variables, not CLI args.

**Subcommands:**

```
<wrapper> setup
  → interactive (stdin/stdout attached), exit code 0 = success

<wrapper> build  <protocol args>
  → stdout JSON: {"cmd": ["claude", "-p", "task", ...], "cwd": "/path"}
  (returns the translated agent command without executing it)
```

`WrapperRuntime` calls `build` to get the translated command, then launches
it via `Popen` and manages PID/log files internally.
`InteractiveWrapperRuntime` also calls `build`, then wraps the command in tmux.

The wrapper CLI can be a compiled binary (Go, Rust) or an external CLI on PATH.
The `AGENT.md` manifest declares which to call.

### Agent Manifest (`AGENT.md`)

Agents follow the same [Agent Skills](https://agentskills.io) open format as
skills — YAML frontmatter (`name`, `description`) + markdown body. The body
describes the agent's capabilities for LLM discovery. StrawPot-specific
config (wrapper, tools, params, env) lives under `metadata.strawpot`:

```yaml
---
name: claude-code
description: Claude Code agent
metadata:
  version: "0.1.0"
  strawpot:
    # Compiled binary (relative to agent folder, keyed by OS):
    bin:
      macos: strawpot_claude_code
      linux: strawpot_claude_code
    # OR external CLI on PATH:
    # wrapper:
    #   command: claude-agent
    tools:
        claude:
          description: Claude Code CLI
          install:
            macos: npm install -g @anthropic-ai/claude-code
            linux: npm install -g @anthropic-ai/claude-code
    params:
      model:
        type: string
        default: claude-sonnet-4-6
        description: Claude model
    env:
      ANTHROPIC_API_KEY:
        required: false
        description: Anthropic API key (optional if using Plus/Max plan)
---

# Claude Code Agent

Runs Claude Code as a subprocess. Supports interactive and non-interactive
modes, custom model selection, and skill-based prompt augmentation.
```

Two wrapper delivery modes:

- `bin.<os>: name` — compiled binary in the agent folder, keyed by OS
  (`macos`, `linux`). StrawPot runs it as
  `<agent_dir>/<name> build ...`. Fast startup, no runtime dependency.
- `wrapper.command: name` — external CLI on PATH, installed however the
  provider wants (pip, cargo, npm, brew).

### Agent Registry (`agents/registry.py`)

Resolves an agent name to a loaded manifest + wrapper command:

```python
@dataclass
class AgentSpec:
    name: str
    version: str
    wrapper_cmd: list[str]   # e.g. ["python", "/path/to/wrapper.py"]
    config: dict             # merged from AGENT.md defaults + user config
    env_schema: dict         # required env vars from metadata.strawpot.env
    tools: dict              # required tools from metadata.strawpot.tools

def resolve_agent(name: str, project_dir: str, agent_config: dict | None = None) -> AgentSpec:
    """
    Resolution order:
    1. .strawpot/agents/<name>/AGENT.md    (project-local)
    2. ~/.strawpot/agents/<name>/AGENT.md  (global install)
    3. built-in _builtin_agents/<name>/    (ships with strawpot)

    agent_config merges user overrides (from config.agents[name]) into spec.config.
    """
```

### WrapperRuntime (`agents/wrapper.py`)

Single generic runtime that calls `<wrapper> build` for translation and
manages process lifecycle internally:

```python
class WrapperRuntime:
    """Implements AgentRuntime by calling <wrapper> build then managing processes."""

    def __init__(self, spec: AgentSpec, session_dir: str | None = None): ...

    def setup(self) -> bool:
        # Runs interactively (stdin/stdout attached) for one-time auth/config
        cmd = [*self.spec.wrapper_cmd, "setup"]
        result = subprocess.run(cmd, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
        return result.returncode == 0

    def spawn(self, *, agent_id, working_dir, agent_workspace_dir,
              role_prompt, memory_prompt, skills_dir, roles_dirs,
              task, env) -> AgentHandle:
        # 1. Call <wrapper> build to get translated command
        args = ["build", "--agent-id", agent_id, "--working-dir", working_dir,
                "--agent-workspace-dir", agent_workspace_dir,
                "--role-prompt", role_prompt, "--memory-prompt", memory_prompt,
                "--task", task, "--config", json.dumps(self.spec.config),
                "--skills-dir", skills_dir]
        for d in roles_dirs:  args += ["--roles-dir", d]
        data = self._run_subcommand(args, extra_env=env)
        # 2. Launch via Popen
        proc = subprocess.Popen(data["cmd"], cwd=data["cwd"], ...)
        # 3. Write PID file
        self._write_pid(agent_id, proc.pid)
        return AgentHandle(agent_id=agent_id, pid=proc.pid, ...)

    def wait(self, handle, timeout=None) -> AgentResult:
        # Poll PID with os.kill(pid, 0) until process exits, read log file
        ...

    def is_alive(self, handle) -> bool:
        # Check PID from handle or PID file
        ...

    def kill(self, handle) -> None:
        # Send SIGTERM to PID
        ...
```

The wrapper CLI only needs `setup` + `build`. Process lifecycle (Popen,
PID tracking, polling, SIGTERM) is handled generically by WrapperRuntime.
No agent-specific code. One class handles all agents.

### InteractiveWrapperRuntime (`agents/interactive.py`)

Wraps any `WrapperRuntime` with tmux for interactive sessions (orchestrator).
Sub-agents use `WrapperRuntime` directly (non-interactive, `-p` mode).

```python
class InteractiveWrapperRuntime:
    """Wraps a WrapperRuntime with tmux session management."""

    def __init__(self, inner: WrapperRuntime): ...

    def spawn(self, ...) -> AgentHandle:
        # 1. Call <wrapper> build → {"cmd": [...], "cwd": "..."}
        # 2. tmux new-session -d -s strawpot-<id[:8]> -c <cwd> -- <cmd>
        # 3. Return AgentHandle with session in metadata

    def wait(self, handle, timeout=None) -> AgentResult:
        # Poll tmux has-session, capture-pane on exit

    def is_alive(self, handle) -> bool:
        # tmux has-session

    def kill(self, handle) -> None:
        # tmux kill-session

    def attach(self, handle) -> None:
        # tmux attach-session (not part of AgentRuntime protocol)
```

tmux is a session-level concern in strawpot core, not an agent-specific one.
The orchestrator needs an interactive terminal; sub-agents do not. This
separation keeps wrappers simple — they only translate protocol args to
native flags without managing session infrastructure.

### DirectWrapperRuntime (`agents/interactive.py`)

Cross-platform fallback for interactive sessions when tmux is not available.
Runs the agent process directly attached to the current terminal via `Popen`
with stdin/stdout/stderr inherited. No detach/reattach capability.

```python
class DirectWrapperRuntime:
    """Cross-platform fallback — no tmux required."""

    def __init__(self, inner: WrapperRuntime): ...

    def spawn(self, ...) -> AgentHandle:
        # 1. Call <wrapper> build → {"cmd": [...], "cwd": "..."}
        # 2. Popen(cmd, cwd=cwd, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)

    def wait(self, handle, timeout=None) -> AgentResult:
        # proc.wait(timeout=timeout)

    def is_alive(self, handle) -> bool:
        # proc.poll() is None

    def kill(self, handle) -> None:
        # proc.terminate()

    def attach(self, handle) -> None:
        # proc.wait() — no-op if already terminal-attached
```

The CLI auto-selects the runtime via `shutil.which("tmux")`:
tmux found → `InteractiveWrapperRuntime`, otherwise → `DirectWrapperRuntime`.

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
    def cleanup(self, env: IsolatedEnv, *, base_dir: str) -> None: ...
```

Implementations:
- `NoneIsolator` — returns `base_dir` as-is, cleanup is a no-op.
  Agents work directly in the project directory.
- `WorktreeIsolator` — creates a worktree per session. Raises `ValueError`
  if the project is not already a git repo.
- Future: `DockerIsolator`.

### Config (`config.py`)

```python
@dataclass
class StrawPotConfig:
    runtime: str = "claude_code"
    isolation: str = "none"
    denden_addr: str = "127.0.0.1:9700"
    orchestrator_role: str = "orchestrator"
    allowed_roles: list[str] | None = None   # None = all
    max_depth: int = 3
    permission_mode: str = "default"   # orchestrator permission mode
    agent_timeout: int | None = None   # sub-agent timeout in seconds (None = no limit)
    agents: dict[str, dict] = field(default_factory=dict)  # per-agent extras
    merge_strategy: str = "auto"       # auto | local | pr
    pull_before_session: str = "prompt" # auto | always | never | prompt
    pr_command: str = "gh pr create --base {base_branch} --head {session_branch}"
```

`agents` holds agent-specific config keyed by agent name. These are extras
beyond the standard protocol args — model, temperature, custom endpoints, etc.
Passed as `--config JSON` to the wrapper.

`merge_strategy` controls how session changes are applied at cleanup:
- `auto` — detect remote (`git remote get-url origin`): PR if remote exists, local otherwise
- `local` — always apply patch locally (conflict resolution prompt)
- `pr` — always push branch + create PR (fail if no remote)

`pull_before_session` controls whether to pull latest from remote before
creating a worktree or docker session:
- `auto` — pull if remote detected
- `always` — force pull (fail if no remote)
- `never` — skip, use current HEAD
- `prompt` — ask the user each time (default)

`pr_command` is the command template for creating PRs. Supports `{base_branch}`
and `{session_branch}` placeholders. Set to empty string to push without
creating a PR. Users can swap `gh` for `glab`, a custom script, etc.

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
isolation = "none"               # none | worktree | docker

[denden]
addr = "127.0.0.1:9700"

[orchestrator]
role = "team-lead"           # strawhub role slug (default: "orchestrator")
permission_mode = "default"  # orchestrator permission mode (sub-agents always "auto")

[policy]
allowed_roles = ["implementer", "reviewer", "fixer"]
max_depth = 3
agent_timeout = 300          # sub-agent timeout in seconds (omit for no limit)

[session]
merge_strategy = "auto"          # auto | local | pr
pull_before_session = "prompt"   # auto | always | never | prompt
pr_command = "gh pr create --base {base_branch} --head {session_branch}"

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
3. agent_spec = resolve_agent(config.runtime, working_dir, config.agents.get(config.runtime))
   → merges config.agents[name] into spec.config
   → validates metadata.strawpot.tools (fail if missing — should
     have been installed via `strawpot install agent`, this is a safety net)
   → validates metadata.strawpot.env: prompt user for missing required env vars
     interactively (set in process env for this session only, not persisted)
4. wrapper = WrapperRuntime(agent_spec)                      # generic, works for any agent
   runtime = InteractiveWrapperRuntime(wrapper)              # tmux available → tmux session
          or DirectWrapperRuntime(wrapper)                   # no tmux → direct terminal attach
5. isolator = resolve_isolator(config.isolation)             # none | worktree | docker
6. session = Session(config, wrapper, runtime, isolator)
7. session.start():
   a. run_id = "run_" + uuid4()
   b. Create isolated env (or use CWD directly):
      env = isolator.create(session_id=run_id, base_dir=working_dir)
      → isolation=none:     env.path = working_dir (no-op)
      → isolation=worktree: git worktree add <STRAWPOT_HOME>/worktrees/<hash>/<run_id> ...
      All agents will work in env.path from here on.
   c. Start DenDenServer(addr=config.denden_addr)
      - If port was explicitly provided (--port flag): fail with error if taken
      - Otherwise (default from config): try configured port, if taken bind to
        port 0 (OS assigns free port)
      - Record actual addr in session file (agents use this to connect)
      - server.on_delegate(self._handle_delegate)
      - server.on_ask_user(self._handle_ask_user)
      - run in background thread
   d. Resolve orchestrator role + build prompt:
        resolved = resolve(config.orchestrator_role, kind="role")
        role_prompt = build_prompt(resolved)
   e. agent_id = "agent_" + uuid4()
      skills_dir, roles_dir = stage_role(session_dir, resolved)
      → session-level staging (idempotent): copies ROLE.md, symlinks transitive skills + direct role deps
      workspace = create_agent_workspace(session_dir, agent_id)
      → per-agent scratch directory
   f. runtime.spawn(                   # InteractiveWrapperRuntime
        agent_id=agent_id,
        working_dir=env.path,
        agent_workspace_dir=workspace,
        role_prompt=role_prompt,
        memory_prompt=memory_prompt,
        skills_dir=skills_dir,
        roles_dirs=[roles_dir],
        task="",                         # interactive mode
        env={
          PERMISSION_MODE: config.permission_mode,  # from global config
          DENDEN_ADDR: config.denden_addr,
          DENDEN_AGENT_ID: agent_id,
          DENDEN_RUN_ID: run_id,
        }
      )
      → InteractiveWrapperRuntime calls: <wrapper> build --agent-id ...
        --working-dir ... --agent-workspace-dir ... --role-prompt ...
        --memory-prompt ... --task "" --skills-dir ... --config '{"model": "..."}'
        (env vars PERMISSION_MODE, DENDEN_ADDR, etc. passed as subprocess environment)
      → Gets back {"cmd": [...], "cwd": "..."}
      → Launches: tmux new-session -d -s strawpot-<id[:8]> -c <cwd> -- <cmd>
   g. Write .strawpot/sessions/<run_id>/session.json
   h. runtime.attach(handle)          # attach user to tmux session
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
   Build delegatable roles list for the sub-agent:
   → excludes the current role (can't self-delegate)
   → excludes the requester role (can't delegate back to parent)
   → only includes roles in allowed_roles with resolvable directories
4. Build prompt:
   system_prompt = context.build_prompt(resolved,
     delegatable_roles=..., requester_role=parent_role)
   → reads SKILL.md bodies (deps first) + ROLE.md body
   → appends Delegation section (delegatable roles, if any)
   → appends Requester section (parent role that delegated the task)
5. Stage role + create workspace:
   skills_dir, roles_dir = stage_role(session_dir, resolved)
   → session-level (idempotent): copies ROLE.md into session_dir/roles/<slug>/,
     symlinks transitive skill deps into skills/, direct role deps into roles/
     (symlinks into session dir)
   roles_dirs = [roles_dir]
   → if requester role is resolvable, symlink into
     session_dir/requester_roles/<agent_id>/<parent_role>/
     and append that dir to roles_dirs (per-agent, avoids leak into shared staged dir)
   workspace = create_agent_workspace(session_dir, agent_id)
   → per-agent scratch directory at session_dir/agents/<agent_id>/ (clean — no pre-placed files)
6. Spawn in session worktree (shared — no new worktree):
   handle = runtime.spawn(
     agent_id=agent_id, working_dir=self.env.path,
     agent_workspace_dir=workspace,
     role_prompt=role_prompt, memory_prompt=memory_prompt,
     skills_dir=skills_dir, roles_dirs=roles_dirs,
     task=task_text,
     env={PERMISSION_MODE: "auto",    # sub-agents always run non-interactively
          DENDEN_ADDR, DENDEN_AGENT_ID,
          DENDEN_PARENT_AGENT_ID, DENDEN_RUN_ID}
   )
   → WrapperRuntime calls wrapper CLI with standard protocol args
7. Wait:
   result = runtime.wait(handle, timeout=config.agent_timeout)
   (blocks — sequential DAG, one sub-agent at a time)
   → on timeout: runtime.kill(handle), return error response
     "Agent timed out after {timeout}s" to parent
8. Return:
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

When the agent has delegatable roles, a delegation section is appended:

```
---

## Delegation

You can delegate tasks to the following roles:
- **backend-engineer**: Handles backend API implementation
- **test-writer**: Writes and maintains test suites

Each role is described in `roles/<role-name>/ROLE.md`. Read the ROLE.md
file to learn more about the role before delegating. Use the `denden`
skill to request delegation.
```

Only the role name and description (from ROLE.md frontmatter) are included
in the prompt — the full ROLE.md content is available on disk at
`roles/<role-name>/ROLE.md` (symlinked by the wrapper) for the agent to
read on demand.

When the task was delegated by a parent agent, a requester section is appended:

```
---

## Requester

This task was delegated to you by **orchestrator**. If you need task
clarification or domain knowledge, use the `denden` skill to ask your
requester.

Do NOT use `denden` to send your final results back. When your task is
complete, write your output to stdout.
```

The requester's ROLE.md is also made available on disk at
`roles/<requester-role>/ROLE.md` so the sub-agent can read it on demand.

---

## Skill Manifest (`SKILL.md`)

Skills follow the [Agent Skills](https://agentskills.io) open format — YAML
frontmatter + markdown body. StrawPot-specific extensions live under
`metadata.strawpot` to stay spec-compliant:

```yaml
---
name: git-workflow
description: Git workflow automation with GitHub PRs
metadata:
  author: example-org
  version: "1.0"
  strawpot:
    dependencies: [git-basics]
    tools:
        gh:
          description: GitHub CLI
          install:
            macos: brew install gh
            linux: apt install gh
    params:
      base_branch:
        type: string
        default: main
        description: Default base branch
    env:
      GITHUB_TOKEN:
        required: true
        description: GitHub API token
---

# Git Workflow

Step-by-step instructions for the agent...
```

| Key | Description |
|---|---|
| `metadata.strawpot.dependencies` | List of skill slugs this skill depends on (resolved by strawhub) |
| `metadata.strawpot.tools.<name>` | Required tools with per-OS install instructions |
| `metadata.strawpot.params` | Configurable parameters for the skill |
| `metadata.strawpot.env` | Required environment variables (prompted at session start) |

All `metadata.strawpot` fields are optional. Most skills only need the
standard Agent Skills fields (`name`, `description`) and the markdown body.

The same `tools`, `params`, and `env` schema is shared across
all package types — skills (`SKILL.md`), agents (`AGENT.md`), and memory
providers (`MEMORY.md`). All use YAML frontmatter with `metadata.strawpot`.

---

## Skill, Role, Agent & Memory Management

StrawPot delegates all package management to the `strawhub` CLI.
Currently strawhub manages skills and roles. Agent and memory provider
package types are planned future additions to strawhub.

Rather than redefining each strawhub option, strawpot passes through
all arguments directly — any flags strawhub supports work automatically:

```
strawpot install [...]            →  strawhub install [...]
strawpot uninstall [...]          →  strawhub uninstall [...]
strawpot update [...]             →  strawhub update [...]
strawpot search [...]             →  strawhub search [...]
strawpot list [...]               →  strawhub list [...]
strawpot info [...]               →  strawhub info [...]
strawpot init [...]               →  strawhub init [...]
strawpot install-tools [...]      →  strawhub install-tools [...]
strawpot resolve [...]            →  strawhub resolve [...]
strawpot publish [...]            →  strawhub publish [...]
strawpot login [...]              →  strawhub login [...]
strawpot logout [...]             →  strawhub logout [...]
strawpot whoami [...]             →  strawhub whoami [...]
```

At runtime (delegation), strawpot calls `strawhub.resolver.resolve()` directly
as a Python import to resolve role + skill paths for prompt building.

### Agent Installation Layout

Agents install to `$STRAWPOT_HOME/agents/<name>/` (default: `~/.strawpot/agents/`):

```
~/.strawpot/agents/
  claude_code/
    AGENT.md               # manifest: wrapper config, params, env, install prereqs
    strawpot_claude_code   # compiled wrapper binary (bin.<os> mode)
  codex/
    AGENT.md               # may point to external CLI via wrapper.command
  my_custom_agent/
    AGENT.md
```

Project-local agents can also be placed at `.strawpot/agents/<name>/` and take
precedence over global installs.

### Install-time Prerequisite Validation

When an agent is installed, its manifest `metadata.strawpot.tools` is validated:

```
Agent install example (claude_code):
  1. Agent package downloaded to ~/.strawpot/agents/claude_code/
  2. Read AGENT.md metadata.strawpot.tools
  3. Detect current OS (platform.system() → macos/linux)
  4. For each command: shutil.which(cmd)
     → found: ✓ claude
     → missing: ✗ some-tool — not found
       Install with: npm install -g some-tool  (from metadata.strawpot.tools.some-tool.install.macos)
  5. If any missing: warn (don't block install — user may install later)
```

Each command entry has per-OS install instructions. StrawPot detects the
current platform and shows the appropriate instruction. If the current OS
has no entry, the warning omits the install hint.

The same check runs as a safety net at `strawpot start` (step 3). If a
prerequisite command is still missing at session start, strawpot errors out
with the OS-specific install instructions from the manifest.

### install-tools

`strawpot install-tools` (passthrough to `strawhub install-tools`) scans all
installed packages for `metadata.strawpot.tools`, checks which commands are
missing via `shutil.which()`, and offers to install them:

```
$ strawpot install-tools

Scanning installed packages for required tools...

Missing tools:
  ✗ claude (required by: claude_code)
    Install: npm install -g @anthropic-ai/claude-code

Install missing tools? [y/N]
```

Tools are deduplicated across packages — if multiple packages require `tmux`,
it appears once. The `--yes` flag skips the confirmation prompt.

### Writing a Wrapper

A wrapper is any CLI that implements two subcommands: `setup` (interactive
auth) and `build` (translate protocol args to native agent command). Process
lifecycle is handled by `WrapperRuntime` — wrappers never manage processes.

Minimal example in Python:

```python
#!/usr/bin/env python3
"""Minimal wrapper — translates protocol args to agent CLI."""
import argparse, json, sys

def setup(args):
    # Run interactive auth flow for the underlying agent
    ...

def build(args):
    cmd = [args.config["command"]]
    if args.task:
        cmd += ["--task", args.task]
    print(json.dumps({"cmd": cmd, "cwd": args.working_dir}))
```

Wrapper authors only need to care about translating protocol args to their
agent's native interface. StrawPot handles everything else — launching
the process, tracking PIDs, waiting for completion, and cleanup.

---

## Built-in Agent: claude_code

Ships with strawpot at `_builtin_agents/claude_code/`. Serves as the default
runtime and as a reference implementation for wrapper authors.

### `AGENT.md`

```yaml
---
name: claude-code
description: Claude Code agent
metadata:
  version: "0.1.0"
  strawpot:
    bin:
      macos: strawpot_claude_code
      linux: strawpot_claude_code
    tools:
        claude:
          description: Claude Code CLI
          install:
            macos: npm install -g @anthropic-ai/claude-code
            linux: npm install -g @anthropic-ai/claude-code
    params:
      model:
        type: string
        default: claude-sonnet-4-6
        description: Claude model
    env:
      ANTHROPIC_API_KEY:
        required: false
        description: Anthropic API key (optional if using Plus/Max plan)
---

# Claude Code Agent

Runs Claude Code as a subprocess. Supports interactive and non-interactive
modes, custom model selection, and skill-based prompt augmentation.
```

### Go binary wrapper

The wrapper is a compiled Go binary — a pure translation layer that maps
StrawPot protocol args to `claude` CLI flags. Using Go eliminates Python
cold-start overhead since the wrapper runs on every agent spawn. It does NOT
manage processes or session infrastructure — that is handled by
`WrapperRuntime` and `InteractiveWrapperRuntime` in strawpot core.

Source: `wrapper/main.go` (built to `strawpot_claude_code` binary).

```
setup:
  Locate claude on PATH, run "claude /login" interactively.
  Exit code 0 = success.

build:
  Protocol arg             → Claude Code flag
  ─────────────────────────────────────────────
  --agent-workspace-dir DIR → uses DIR directly as --add-dir (required)
  --role-prompt TEXT    \
  --memory-prompt TEXT  /→ write to <DIR>/prompt.md → --system-prompt FILE
  --task TEXT              → -p TEXT (omit if empty = interactive)
  --config JSON            → extract "model" → --model MODEL
  --skills-dir DIR         → symlink children to <DIR>/.claude/skills/<name>/
  --roles-dir DIR          → symlink children to <DIR>/roles/<name>/ (repeatable, skips existing)
  PERMISSION_MODE env      → --permission-mode VALUE (passed through directly)
  (all)                    → --add-dir DIR (single add-dir for all)

  The agent workspace dir is used directly as --add-dir.  Skills are placed at
  .claude/skills/<name>/ so Claude Code discovers them natively.  Role symlinks
  are placed at roles/<name>/ so the agent can read ROLE.md files on demand
  (the prompt only contains descriptions, not full content).  When multiple
  --roles-dir flags are given, children are merged; duplicates are skipped.

  Returns: {"cmd": ["claude", ...], "cwd": "..."} without executing.
  WrapperRuntime then launches the command via Popen and manages PID/logs.
```

This is the only place that knows about `claude` CLI flags.
StrawPot core never imports or references it directly — the registry
discovers it via `AGENT.md`.

---

## Isolation Implementations

`none` and `docker` work with any directory. `worktree` requires a git
repository — raises `ValueError` if the project is not a git repo.

### NoneIsolator (default)

Agents work directly in the project directory. No setup, no cleanup.
Multiple concurrent sessions are allowed — each writes its own session file
under `sessions/<run_id>/session.json`.

```
create(session_id, base_dir):
  return IsolatedEnv(path=base_dir, branch=None)

cleanup(env, base_dir):
  pass  # no-op
```

Simplest option — good for single-agent sessions, non-coding workflows,
or when the user manages their own branching.

### WorktreeIsolator (`isolation/worktree.py`)

Creates one git worktree per session. Multiple concurrent sessions are
safe — each gets its own branch.

Worktrees are stored outside the project tree under `STRAWPOT_HOME` to
avoid interfering with IDEs, file watchers, and gitignore.

```
create(session_id, base_dir):
  if not is_git_repo(base_dir): raise ValueError

  path = <STRAWPOT_HOME>/worktrees/<project_hash>/<session_id>
  branch = strawpot/<session_id>
  git worktree add <path> -b <branch>
  return IsolatedEnv(path, branch)

cleanup(env, base_dir):
  # see Session Cleanup below — strategy determines local merge vs PR
  git worktree remove <path> --force
  git branch -D <branch>   # only if local strategy + user chose discard
```

Pull-before-session and merge strategy are handled by session.py, not here.
The isolator only manages worktree creation and removal.

### DockerIsolator (future)

Runs agents inside a container. The container gets a copy of the working
directory (not a bind-mount — true isolation). Multiple concurrent sessions
are safe — each gets its own container.

Git is initialized inside the container at create time purely for patch
generation — it never leaks to the host. Changes are exported as a unified
diff patch, not via `docker cp` (which would copy the `.git` directory).

```
create(session_id, base_dir):
  container_id = docker run ... -v <base_dir>:/src:ro  # read-only mount for initial copy
  # copy base_dir into container working dir
  docker exec <container> git init && git add -A && git commit -m "initial"
  return IsolatedEnv(path="/workspace", container_id=container_id)

cleanup(env):
  # see Session Cleanup below — extract patch, apply to host, remove container
  patch = docker exec <container> git diff HEAD
  apply_patch(patch, host_dir)   # uses git apply or patch (see below)
  docker rm <container>          # .git inside container dies here
```

---

## Session Tracking

`.strawpot/sessions/<run_id>/` holds one directory per active session,
with `session.json` inside. Multiple concurrent sessions are allowed for
all isolation modes. For `none`, concurrent sessions write to the same
directory — overlapping changes are the user's responsibility.

---

## Session Cleanup

When a session ends (Ctrl+C, agent quit, or crash recovery), cleanup
depends on the isolation mode.

### `isolation = none`

Nothing to do. Changes are already in the project directory.

```
session.stop():
  1. Kill remaining sub-agents
  2. Stop denden server
  3. Remove session directory
```

### `isolation = worktree`

Cleanup strategy is determined by `merge_strategy` config:
- `auto` — detect remote: PR if remote exists, local otherwise
- `local` — always apply patch locally
- `pr` — always push + create PR

**Local strategy** (no remote, or `merge_strategy = "local"`):

Changes live on a local branch. StrawPot generates a patch from the
session branch against the base branch and applies it.

```
session.stop():
  1. Kill remaining sub-agents
  2. Stop denden server
  3. Generate patch: git diff <base_branch>..strawpot/<run_id>
  4. Apply patch to base_branch: git apply --check <patch>
     → no conflicts: apply, remove worktree + delete branch
     → conflicts detected: show conflicting files, prompt user (see below)
  5. Remove session directory
```

**PR strategy** (remote detected, or `merge_strategy = "pr"`):

Changes are pushed to remote and a PR is created. No local merge.

```
session.stop():
  1. Kill remaining sub-agents
  2. Stop denden server
  3. Commit any uncommitted changes in worktree
  4. Push branch: git push -u origin strawpot/<run_id>
  5. Create PR: <pr_command> with {base_branch} and {session_branch} expanded
     e.g. gh pr create --base main --head strawpot/run_abc123
  6. Remove worktree (keep branch — it's on remote)
  7. Remove session directory
  → User reviews & merges PR on GitHub/GitLab
  → User pulls main when ready
```

### `isolation = docker` (future)

The container has git initialized inside it at `create()` time purely for
diff tracking. The container's `.git` never touches the host — it dies
with `docker rm`. Cleanup depends on the merge strategy.

**Local strategy**:

```
session.stop():
  1. Kill remaining sub-agents (inside container)
  2. Stop denden server
  3. Generate patch: docker exec <container> git diff HEAD
  4. Apply patch to host dir (see Patch Application below)
     → no conflicts: apply, remove container
     → conflicts detected: show conflicting files, prompt user (see below)
  5. docker rm <container>
  6. Remove session directory
```

**PR strategy** (host has remote):

```
session.stop():
  1. Kill remaining sub-agents (inside container)
  2. Stop denden server
  3. Generate patch: docker exec <container> git diff HEAD
  4. On host: git checkout -b strawpot/<run_id>
  5. Apply patch, commit
  6. Push branch: git push -u origin strawpot/<run_id>
  7. Create PR: <pr_command>
  8. git checkout <base_branch>   # return to original branch
  9. docker rm <container>
  10. Remove session directory
```

### Patch Application

StrawPot picks the right tool based on the host directory:

```
if is_git_repo(host_dir):
    use git apply          # better 3-way merge support
else:
    use patch              # POSIX standard, no git needed, no side effects
```

The `patch` fallback means docker isolation works on non-git host
directories without creating a `.git` on the host.

### Conflict Resolution (Local Strategy Only)

When using the **local** merge strategy, both `worktree` and `docker` use
the same conflict resolution flow. (PR strategy has no local conflicts —
they're handled through the PR review process.)

Conflicts are detected before applying — if the patch doesn't apply
cleanly, strawpot lists the conflicting files and prompts:

```
Conflict: 2 files changed on both sides since session started.
  src/auth.py
  src/config.py

  [a] Apply all — override conflicts with session's changes
  [s] Skip conflicts — apply only non-conflicting changes
  [d] Discard all — drop all session changes
```

| Option | git host (`git apply`) | non-git host (`patch`) |
|---|---|---|
| Detect conflicts | `git apply --check` | `patch --dry-run` |
| Apply all (override) | `git apply --3way` | `patch --force` |
| Skip conflicts | `git apply --reject`, drop `.rej` | `patch`, skip failed hunks |
| Discard all | don't apply | don't apply |

After any choice, the worktree is removed and the branch is deleted
(worktree), or the container is removed (docker).

StrawPot does not provide manual merge resolution. The three options
cover the common cases; for anything more nuanced the user can use
`isolation=none` and manage merges themselves.

### Crash Recovery

If a session was interrupted (crash/SIGKILL), the next `strawpot start`
detects stale session files (process dead via `pid` check) and runs the
same cleanup flow before starting a new session.

---

## Session State

Written to `.strawpot/sessions/<run_id>/` (gitignored) for crash recovery,
debugging, and the `strawpot sessions` / `strawpot agents` commands.

Each session writes to `.strawpot/sessions/<run_id>/session.json`.
Staged roles, agent workspaces, PID files, and agent logs all live under
the same session directory:

```
.strawpot/sessions/<run_id>/
  session.json                    # session state
  roles/<slug>/                   # staged roles (session-level, shared, idempotent)
    ROLE.md                       # copied from installed path
    skills/<dep_slug>/            # symlinked transitive skill deps
    roles/<dep_slug>/             # symlinked direct role deps
  requester_roles/<agent_id>/     # per-agent requester role (avoids leak into shared dir)
    <parent_role>/                # symlinked to installed path
  agents/<agent_id>/              # per-agent scratch workspace (clean)
    .pid                          # PID file (WrapperRuntime)
    .log                          # agent output log (WrapperRuntime)
```

```json
{
  "run_id": "run_abc123",
  "working_dir": "/home/user/project",
  "isolation": "worktree",
  "runtime": "claude_code",
  "denden_addr": "127.0.0.1:9700",
  "worktree": "~/.strawpot/worktrees/<project_hash>/run_abc123",
  "worktree_branch": "strawpot/run_abc123",
  "base_branch": "main",
  "started_at": "2026-02-27T10:00:00Z",
  "pid": 54321,
  "agents": {
    "agent_xyz": {
      "role": "orchestrator",
      "runtime": "claude_code",
      "parent": null,
      "started_at": "2026-02-27T10:00:01Z",
      "pid": 54322
    },
    "agent_abc": {
      "role": "implementer",
      "runtime": "claude_code",
      "parent": "agent_xyz",
      "started_at": "2026-02-27T10:01:00Z",
      "pid": 54330
    }
  }
}
```

- `pid` — strawpot process ID, used to detect stale sessions (process dead
  but file remains).
- `denden_addr` — actual bound address. May differ from config if the
  configured port was taken and auto-assigned (see port auto-resolution).
- `agents` — updated live as agents are spawned/completed. Each entry
  tracks role, runtime, parent chain, and process ID.

---

## Logging

StrawPot writes structured JSONL logs per session for debugging and Web GUI
consumption. Agent stdout/stderr is captured separately by WrapperRuntime.

### Session Log

One file per session: `.strawpot/sessions/<run_id>/session.jsonl`

Each line is a JSON object:

```json
{"ts": "2026-02-27T10:00:00Z", "level": "info", "event": "session_started", "run_id": "run_abc123", "msg": "Session started", "data": {"isolation": "worktree", "runtime": "claude_code"}}
{"ts": "2026-02-27T10:00:01Z", "level": "info", "event": "agent_spawned", "run_id": "run_abc123", "agent_id": "agent_xyz", "msg": "Spawned orchestrator", "data": {"role": "orchestrator"}}
{"ts": "2026-02-27T10:01:00Z", "level": "info", "event": "delegate_request", "run_id": "run_abc123", "agent_id": "agent_xyz", "msg": "Delegation requested", "data": {"role": "implementer", "task": "implement auth"}}
{"ts": "2026-02-27T10:05:00Z", "level": "error", "event": "agent_timeout", "run_id": "run_abc123", "agent_id": "agent_abc", "msg": "Agent timed out after 300s"}
```

### Event Types

| Event | Level | Description |
|---|---|---|
| `session_started` | info | Session created, isolation env ready |
| `session_stopped` | info | Clean shutdown completed |
| `denden_started` | info | gRPC server bound to address |
| `denden_stopped` | info | gRPC server shut down |
| `agent_spawned` | info | Agent process launched |
| `agent_completed` | info | Agent exited normally |
| `agent_timeout` | error | Agent killed after timeout |
| `agent_killed` | warn | Agent force-killed (Ctrl+C or cleanup) |
| `delegate_request` | info | Delegation request received |
| `delegate_denied` | warn | Policy denied delegation (role/depth) |
| `delegate_result` | info | Delegation completed with result |
| `cleanup_started` | info | Session cleanup in progress |
| `cleanup_merge` | info | Merge strategy applied (local/pr) |
| `cleanup_conflict` | warn | Patch conflicts detected |
| `crash_recovery` | warn | Stale session detected and cleaned up |

### Fields

| Field | Required | Description |
|---|---|---|
| `ts` | yes | ISO 8601 timestamp (UTC) |
| `level` | yes | `info`, `warn`, or `error` |
| `event` | yes | Machine-readable event type |
| `run_id` | yes | Session run ID |
| `agent_id` | no | Agent ID (when event relates to an agent) |
| `msg` | yes | Human-readable message |
| `data` | no | Structured payload (event-specific) |

### Agent Output

WrapperRuntime captures agent stdout/stderr to per-agent log files:
`.strawpot/sessions/<run_id>/agents/<agent_id>/.log`

These are raw text logs from the underlying agent process (e.g. Claude Code
output), not structured JSONL. The Web GUI can display them alongside the
session log for a complete picture.

### Retention

Session logs are preserved after cleanup for history tracking. The Web GUI
reads these for session history and replay. Old logs can be pruned manually
or by a future retention policy.

---

## Role Manifest (`ROLE.md`)

Roles follow the same [Agent Skills](https://agentskills.io) open format —
YAML frontmatter (`name`, `description`) + markdown body. The body contains
the role's system prompt (instructions for the agent). StrawPot-specific
config lives under `metadata.strawpot`:

```yaml
---
name: implementer
description: "Writes code to implement features and fix bugs"
metadata:
  version: "1.0.0"
  tags: [coding, implementation]
  author: strawpot
  strawpot:
    dependencies:
      skills:
        - git-workflow
        - code-review
      roles:
        - fixer
    default_model:
      provider: claude_session
      id: claude-opus-4-6
    tools:
        pytest:
          description: Python test runner
          install:
            macos: pip install pytest
            linux: pip install pytest
---

# Implementer

You are an implementer. Given a task, write clean code that follows the
project's conventions...
```

| Key | Required | Description |
|---|---|---|
| `name` | yes | Unique slug for the role |
| `description` | yes | One-line summary (used in delegation prompt) |
| `metadata.version` | no | Semver version string |
| `metadata.tags` | no | Category tags for discovery |
| `metadata.author` | no | Creator/organization name |
| `metadata.strawpot.dependencies.skills` | no | Skill dependencies (resolved by strawhub) |
| `metadata.strawpot.dependencies.roles` | no | Delegatable sub-roles (shown in delegation section of prompt) |
| `metadata.strawpot.default_model` | no | Preferred model for this role |
| `metadata.strawpot.tools` | no | Required tools with per-OS install instructions |

Dependency version specifiers: `slug` (latest), `slug==X.Y.Z` (exact),
`slug>=X.Y.Z` (minimum), `slug^X.Y.Z` (compatible — same major).

The markdown body (after frontmatter) is used as the role's system prompt
content. Only the body is included in the agent's prompt — frontmatter is
stripped by `context.py`.

Roles can declare other roles as dependencies via `metadata.strawpot.dependencies.roles`.
These are the roles the agent is allowed to delegate to. The delegation section
of the prompt lists these roles with their `name` and `description` from
frontmatter.

---

## CLI

```
strawpot start  [--role SLUG] [--runtime NAME]
                [--isolation none|worktree|docker]
                [--merge-strategy auto|local|pr]
                [--pull auto|always|never|prompt]
                [--host HOST] [--port PORT]
strawpot sessions                    # list all running sessions
strawpot agents <session_id>         # list agents for a session
strawpot config

# Passthrough to strawhub CLI (all args forwarded):
strawpot install [...]           # install from strawpot.toml or specific package
strawpot uninstall [...]         # remove a skill or role
strawpot update [...]            # update packages to latest
strawpot search [...]            # search the registry
strawpot list [...]              # browse the registry
strawpot info [...]              # show package details
strawpot init [...]              # create strawpot.toml from installed packages
strawpot install-tools [...]     # install system tools declared by packages
strawpot resolve [...]           # resolve slug to installed path
strawpot publish [...]           # publish to registry
strawpot login [...]             # authenticate with registry
strawpot logout [...]            # remove stored credentials
strawpot whoami [...]            # show current user
```

`--runtime NAME` accepts any agent name resolvable by the registry (project-local,
global install, or built-in). Not limited to a hardcoded list.

`--merge-strategy` and `--pull` override the `[session]` config values for
this run. Useful for one-off runs: e.g. `strawpot start --pull never` to
skip pulling when you want to work on the current HEAD.

`start` runs in the foreground — on exit (Ctrl+C or agent quit), the session
runs the cleanup flow (see Session Cleanup). For local strategy, the user is
prompted for conflict resolution. For PR strategy, the branch is pushed and
a PR is created automatically.

`sessions` reads all session directories from `.strawpot/sessions/`,
loads `session.json` from each, checks if each process is still alive (via
`pid`), and displays a table of running sessions with run_id, isolation mode,
runtime, denden port, and uptime. Stale sessions (dead pid) are marked
accordingly.

`agents <session_id>` reads a specific session's `session.json` and displays
the agent tree — role, runtime, parent, pid, and whether each agent is still
alive.

---

## Implementation Order

### Phase 1 — Core (complete)

1. `config.py` — add `agents: dict` field, parse `[agents.*]` sections
2. `agents/protocol.py` + `isolation/protocol.py` — types
3. `agents/registry.py` — discover `AGENT.md`, validate env, merge config
4. `agents/wrapper.py` — `WrapperRuntime` (calls wrapper CLI via subprocess)
5. `_builtin_agents/claude_code/` — `AGENT.md` + Go wrapper binary
6. `isolation/worktree.py`
7. `context.py`
8. `delegation.py`
9. `session.py`
10. `cli.py` + `__main__.py` — wire `start` command, add strawhub passthrough
    (`install`, `uninstall`, `search`, `list`, `install-tools`)

### Phase 2 — Session Lifecycle

11. `session.py` cleanup — worktree merge strategies (local/pr/auto), patch
    application (`git apply` vs `patch`), conflict resolution prompts
12. `session.py` crash recovery — detect stale sessions on `strawpot start`,
    run cleanup for dead-pid sessions before starting new one
13. `cli.py` signal handling — single Ctrl+C cancels current task and kills
    sub-agents, double Ctrl+C quits immediately
14. `cli.py` noninteractive mode — `strawpot start --task "..."` runs
    orchestrator with a task string instead of interactive terminal
15. `delegation.py` retry policy — validate sub-agent output against
    requester's expected format, retry on invalid output (configurable
    max retries)
16. `session.py` denden port auto-resolution — if configured port is taken,
    bind to port 0 (OS assigns free port); record actual bound addr in
    session file and pass to agents via `DENDEN_ADDR` env var

### Phase 3 — Memory

17. `memory/protocol.py` — `MemoryProvider` protocol, `ContextCard`,
    `ControlSignal`, `DumpReceipt` types
18. `memory/registry.py` — discover `MEMORY.md`, resolve provider,
    validate deps (same pattern as agent registry)
19. `delegation.py` — integrate `memory.get` before spawn and `memory.dump`
    after wait in the delegation flow
20. `config.py` — add `memory` and `memory_config` fields

### Phase 4 — Web GUI

21. Central management platform — project management, multi-session
    monitoring, session history tracking, agent tree visualization,
    denden status, EM replay

### Phase 5 — Docker Isolation

22. `isolation/docker.py` — `DockerIsolator` implementing `Isolator` protocol
    (container create, patch export, cleanup)
23. `session.py` cleanup — docker merge strategies (local/pr), patch
    extraction from container via `docker exec git diff`

### Phase 6 — Ecosystem & Extensibility

24. Community agents — documentation + strawhub publishing flow
25. Cron jobs — invoke orchestrator periodically or conditionally
26. Automation inputs — GitHub issue watcher, email, Telegram → feed tasks
27. Hooks — pre/post spawn, pre/post cleanup extension points

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

StrawPot calls the memory provider to retrieve relevant context before
building the agent's prompt.

```
Inputs:
  session_id
  agent_id
  parent_agent_id             (optional)
  role
  behavior_ref                (loaded role description text)
  task
  budget                      (token budget hint, optional)

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

StrawPot calls the memory provider to record what happened.

```
Inputs:
  session_id
  agent_id
  parent_agent_id             (optional)
  role
  behavior_ref                (loaded role description text)
  task
  status                      (success/failure/timeout)
  output                      (assistant output text)
  tool_trace                  (tool call trace text, optional)
  artifacts                   (commit hash, patch refs, etc., optional)

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

Memory providers are Python modules loaded directly into the strawpot
process (unlike agent wrappers which are CLI subprocesses). Each provider
implements the `MemoryProvider` protocol defined in
`strawpot.memory.protocol`:

```python
class MemoryProvider(Protocol):
    name: str
    def get(self, *, session_id, agent_id, role, behavior_ref,
            task, budget=None, parent_agent_id=None) -> GetResult: ...
    def dump(self, *, session_id, agent_id, role, behavior_ref,
             task, status, output, tool_trace="",
             parent_agent_id=None, artifacts=None) -> DumpReceipt: ...
```

### Memory Manifest (`MEMORY.md`)

Memory providers follow the same [Agent Skills](https://agentskills.io) open
format — YAML frontmatter (`name`, `description`) + markdown body. The body
describes the provider's capabilities and storage approach. StrawPot-specific
config (wrapper, tools, params, env) lives under `metadata.strawpot`:

```yaml
---
name: strawpot-memory-local
description: File-based local memory provider
metadata:
  version: "0.1.0"
  strawpot:
    wrapper:
      script: wrapper.py
      # OR: command: strawpot-memory-local
    # tools:
    #     some-tool:
    #       description: ...
    #       install:
    #         macos: brew install some-tool
    #         linux: apt install some-tool
    params:
      storage_dir:
        type: string
        default: .strawpot/memory
      em_max_events:
        type: int
        default: 10000
    env:
      # e.g. for a vector-db-backed provider:
      # PINECONE_API_KEY:
      #   required: true
      #   description: Pinecone API key
---

# Local Memory Provider

File-based memory provider for local development. Stores event memory,
short-term memory, and semantic memory as local files.
```

Installed to `~/.strawpot/memory/<name>/`, resolved the same way as agents:
project-local → global → built-in.

### EM Event Schema

Every event in the append-only event log:

```json
{
  "session_id": "run_abc123",
  "agent_id": "agent_xyz",
  "parent_agent_id": null,
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

Memory providers will be installable via strawhub once the `memory` package
type is added (planned strawhub addition):

```
strawpot install memory <slug>     →  strawhub install memory <slug>
strawpot uninstall memory <slug>   →  strawhub uninstall memory <slug>
```

---

## Web GUI (Planned)

Central management platform for strawpot. Runs as a local web server that
reads strawpot runtime state and provides a dashboard for managing projects,
monitoring sessions, and reviewing history.

### Architecture

```
Browser
  │
  ▼
Web Server (FastAPI)          ← strawpot-gui package
  │
  ├─ reads .strawpot/sessions/*/session.json     (live session state)
  ├─ reads .strawpot/sessions/*/session.jsonl    (session logs)
  ├─ reads .strawpot/sessions/*/agents/*/.log    (agent output)
  ├─ connects to denden gRPC server              (live status)
  └─ reads EM event store                        (when memory is configured)
```

The GUI is a separate installable package (`pip install strawpot-gui`), not
bundled with the core CLI. It has no write access to strawpot state — it is
a read-only observer that renders existing runtime data.

### Features

**Project Management**
- Register projects (directories with `.strawpot/config.toml`)
- View project config and installed agents/skills/roles
- Quick-launch sessions from the GUI

**Session Monitoring**
- Real-time dashboard of active sessions across all registered projects
- Agent tree visualization — hierarchy, roles, status (running/exited)
- Live denden status — connected agents, pending requests
- Session log stream — tail JSONL logs in real time

**Session History**
- Browse past sessions with timestamps, duration, isolation mode
- View session logs and agent output for completed sessions
- Filter by project, date range, role, or outcome

**EM Replay** (when memory is configured)
- Timeline view of event memory for a session
- Step through agent spawns, tool calls, and results
- Visualize delegation chains and agent communication

### Data Sources

The GUI reads existing runtime artifacts — no new data formats needed:

| Data | Source | Format |
|---|---|---|
| Active sessions | `.strawpot/sessions/*/session.json` | JSON |
| Session logs | `.strawpot/sessions/*/session.jsonl` | JSONL |
| Agent output | `.strawpot/sessions/*/agents/*/.log` | Text |
| Denden status | gRPC connection to running server | Live |
| Event memory | Memory provider store | Provider-specific |
| Project config | `.strawpot/config.toml` | TOML |

### CLI Integration

```
strawpot gui                         # start web server on localhost:9800
strawpot gui --port 9801             # custom port
strawpot gui --host 0.0.0.0         # bind to all interfaces
```

The `gui` command is a thin launcher — available only when `strawpot-gui` is
installed. If not installed, `strawpot gui` prints an install hint and exits.

