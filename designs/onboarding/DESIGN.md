# Onboarding: First-Run Setup

## Problem

First-time users must manually discover and install agent CLIs, authenticate,
install wrappers, and configure env vars — across multiple tools and repos.
There is no guided setup experience for `strawpot start` or `strawpot gui`.

## Goal

When a user runs `strawpot start` or `strawpot gui` for the first time (no
`runtime` set in config, no agent installed), present an interactive terminal
wizard that gets them to a working session in one flow.

## Flow

```
strawpot start / strawpot gui  (first run detected)
  │
  ├─ 1. Agent selection
  │     "Choose your default agent:"
  │       1) strawpot-claude-code   — Anthropic Claude Code
  │       2) strawpot-gemini        — Google Gemini CLI
  │       3) strawpot-codex         — OpenAI Codex CLI
  │       4) strawpot-openhands     — OpenHands
  │       5) strawpot-pi            — Pi coding-agent
  │
  ├─ 2. Install agent wrapper
  │     strawhub install agent <selected> --global
  │     (automatic, show progress)
  │
  ├─ 3. Install underlying CLI tool
  │     Check AGENT.md tools — if missing, run install command from
  │     tools.<name>.install.<os> (already declared in each AGENT.md)
  │     Show command, ask confirmation, execute.
  │
  ├─ 4. Authentication
  │     "Authenticate with API key or login session?"
  │       a) API key → prompt, validate, save to strawpot.toml
  │       b) Login   → run `<wrapper> setup` (e.g. strawpot_claude_code setup)
  │
  ├─ 5. Validate
  │     Run a lightweight auth probe to confirm credentials work.
  │     On failure → retry step 4, or exit with clear error.
  │
  ├─ 6. Save defaults
  │     Write runtime = "<selected>" to ~/.strawpot/strawpot.toml
  │     If API key provided, save to [agents.<name>.env] in strawpot.toml
  │
  └─ 7. Continue
        Proceed to normal strawpot start / strawpot gui execution.
        Auto-install skills (denden, strawpot-session-recap) and roles
        (ai-ceo, ai-employee) silently — this already happens today.
```

## First-Run Detection

Trigger the wizard when **all** of these are true:

1. `~/.strawpot/strawpot.toml` either doesn't exist or has no explicit
   `runtime` key (i.e. still using the hardcoded default)
2. No agent is installed locally (no AGENT.md found for the default runtime)
3. Session is interactive (not `--headless`)

If `--headless`, skip the wizard entirely and fail fast with a clear message
listing what needs to be configured.

## Shared Between CLI and GUI

Both `strawpot start` and `strawpot gui` run in a terminal. The onboarding
wizard is the same for both — it happens before the GUI server starts. No
separate GUI-based setup wizard is needed.

## Agent Descriptions for Picker

Each choice in the picker should show a brief description to help users decide:

| Agent | Description |
|-------|-------------|
| strawpot-claude-code | Anthropic's Claude Code — requires Anthropic account or API key |
| strawpot-gemini | Google Gemini CLI — requires Google account or API key |
| strawpot-codex | OpenAI Codex CLI — requires OpenAI API key |
| strawpot-openhands | OpenHands — open-source, configurable LLM backend |
| strawpot-pi | Pi coding-agent — requires Anthropic account or API key |

Descriptions can be pulled from each AGENT.md's `description` field.

## Auth: API Key vs Login Session

Each agent wrapper already implements a `setup` subcommand that runs the
underlying CLI's login flow (e.g. `claude /login`, `gemini auth login`).

For the "API key" path:
- Prompt for the key
- Save to `[agents.<name>.env]` in `strawpot.toml` using the existing
  `save_resource_config("agents", name, env_values={...})` function
- The key name comes from AGENT.md `env` schema (e.g. `ANTHROPIC_API_KEY`)

For the "login session" path:
- Run `<wrapper_bin> setup` with stdin/stdout attached
- The wrapper handles the full auth flow
- No env var persistence needed — auth tokens are managed by the underlying CLI

## Env Var Persistence

### Current state

- **Skills**: `save_skill_env()` / `save_resource_config("skills", ...)` writes
  to `[skills.<name>.env]` in `strawpot.toml` — plaintext TOML.
- **Agents**: `save_resource_config("agents", ...)` writes to
  `[agents.<name>.env]` in `strawpot.toml` — same plaintext TOML.
- **Gap**: When `strawpot start` prompts for missing agent env vars (cli.py
  lines 368-370), it sets `os.environ[var] = value` but **does not persist**
  the value. The user is re-prompted on every session.

### Fix

After prompting for agent env vars, save them to `strawpot.toml` via
`save_resource_config("agents", ...)` — same as skills already do. Offer the
user a choice:

```
Save ANTHROPIC_API_KEY to config for future sessions? [Y/n]
```

This applies to both the onboarding wizard (step 4) and the existing
`validate_agent` prompt loop in `strawpot start`.

### Security note

Both skill and agent env vars are stored as **plaintext** in
`~/.strawpot/strawpot.toml`. This is acceptable for local-only use but should
be documented. A future enhancement could use OS keychain integration
(macOS Keychain, Linux secret-service) but that is out of scope for this
design.

## Tool Installation

Each AGENT.md declares required tools with install commands. The onboarding
wizard checks these via `validate_agent()` (`shutil.which`) and offers to
install missing ones interactively.

### Package manager prerequisites

The underlying CLI tools are installed via `npm` (4 agents) or `pip` (1 agent).
These package managers must be declared as tool dependencies in each AGENT.md
so the validation pipeline catches them early — before attempting to install
the CLI tool itself.

| Agent | Package manager | CLI tool install |
|-------|----------------|-----------------|
| strawpot-claude-code | `npm` | `npm install -g @anthropic-ai/claude-code` |
| strawpot-gemini | `npm` | `npm install -g @google/gemini-cli` |
| strawpot-codex | `npm` | `npm install -g @openai/codex` |
| strawpot-pi | `npm` | `npm install -g @mariozechner/pi-coding-agent` |
| strawpot-openhands | `pip` | `pip install openhands-ai` |

Each AGENT.md should declare the package manager as a tool **without** an
install command (installation varies by platform/preference). Example:

```yaml
tools:
  npm:
    description: Node.js package manager (https://nodejs.org)
  claude:
    description: Claude Code CLI
    install:
      macos: npm install -g @anthropic-ai/claude-code
      linux: npm install -g @anthropic-ai/claude-code
```

For `pip`, strawpot itself is a Python package so `pip` is almost certainly
present, but declaring it catches edge cases (e.g. `pipx`-only installs).

### Onboarding behavior

During onboarding, instead of just printing the install hint and exiting:

1. Show the install command
2. Ask "Install now? [Y/n]"
3. Run the command if confirmed
4. Re-validate

## Files to Change

| File | Change |
|------|--------|
| `cli/src/strawpot/cli.py` | Add `_onboarding_wizard()`, call it from `start` and `gui` commands when first-run detected |
| `cli/src/strawpot/config.py` | No changes needed — `save_resource_config` already supports agents |
| `cli/src/strawpot/agents/registry.py` | Add `probe_auth(spec)` for lightweight credential validation |
| `strawpot_claude_code_cli: AGENT.md` | Add `npm` as tool dependency |
| `strawpot_gemini_cli: AGENT.md` | Add `npm` as tool dependency |
| `strawpot_codex_cli: AGENT.md` | Add `npm` as tool dependency |
| `strawpot_pi_cli: AGENT.md` | Add `npm` as tool dependency |
| `strawpot_openhands_cli: AGENT.md` | Add `pip` as tool dependency |

## Implementation Status

| # | Item | Status |
|---|------|--------|
| 1 | First-run detection (no runtime in config + no agent installed) | Planned |
| 2 | Interactive agent picker (5 seeded agents with descriptions) | Planned |
| 3 | Auto-install agent wrapper from StrawHub | Planned |
| 4a | Add `npm`/`pip` as tool prerequisites in AGENT.md (5 wrapper repos) | Planned |
| 4b | Auto-install underlying CLI tool (from AGENT.md `tools.*.install`) | Planned |
| 5 | Auth flow: API key prompt or `<wrapper> setup` login | Planned |
| 6 | Lightweight auth probe / credential validation | Planned |
| 7 | Save default runtime to `strawpot.toml` | Planned |
| 8 | Persist prompted agent env vars via `save_resource_config` | Planned |
| 9 | Persist prompted skill env vars via `save_resource_config` (same gap) | Planned |
| 10 | Headless mode: fail fast with clear missing-config message | Planned |

## Not in Scope

- GUI-based setup wizard (terminal wizard is sufficient)
- OS keychain integration for env var storage
- Adding more agents to the picker (users can `strawpot install agent <name>` anytime)
- OS-level package manager auto-install (e.g. installing Node.js/npm itself)
