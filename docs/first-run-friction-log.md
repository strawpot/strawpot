# First-Run Friction Log

**Date:** 2026-03-23
**Tester:** Automated (implementation-executor agent)
**Parent issue:** strawpot/strawpot#406
**Sub-issue:** strawpot/strawpot#408

## Environment

| Property | Value |
|---|---|
| Method | Docker container (clean, no pre-installed tools) |
| Image | `python:3.11-slim` |
| OS | Debian GNU/Linux 13 (trixie) |
| Python | 3.11.15 |
| Architecture | aarch64 |
| Pre-installed tools | pip, setuptools, wheel (nothing else) |

## Timeline

| Step | Start | End | Duration |
|---|---|---|---|
| `pip install strawpot` | 22:12:39 | 22:12:47 | ~8 seconds |
| `strawpot --help` | 22:12:47 | 22:12:47 | <1 second |
| `strawpot start --task "Review my latest PR"` | 22:12:47 | 22:12:47 | <1 second (crashed) |
| Full test protocol | 22:12:39 | 22:12:49 | ~10 seconds |

**Total time from pip install to first useful output: NEVER REACHED.**
The user cannot get to a useful output without manual intervention outside of StrawPot.

## Test Results

### Step 1: pip install strawpot

**Result:** SUCCESS

`pip install strawpot` installs cleanly with no errors. Version 0.1.57 was fetched from PyPI.

- **37 packages** installed as transitive dependencies
- **99 MB** total site-packages size
- Notably heavy dependencies: grpcio (6.5 MB wheel), uvloop (3.8 MB), pydantic-core (1.9 MB), strawpot-gui (1.5 MB)
- No dependency conflicts
- No compilation required (all wheels available for aarch64)

**Friction points:** None. Clean install.

### Step 2: strawpot --help

**Result:** SUCCESS

Help text renders correctly. Lists 20 commands. The output is clear and well-organized.

| Severity | Issue | Details |
|---|---|---|
| MEDIUM | No "Getting Started" guidance in help output | A new user sees 20 commands but no hint about which one to run first. The most important command (`start`) is buried alphabetically between `sessions` and `uninstall`. |
| LOW | No description of what StrawPot actually does | The tagline "lightweight agent orchestration" is vague. A new user who just installed it does not know what agents, skills, roles, or sessions are. |

### Step 3: strawpot start --task "Review my latest PR"

**Result:** CRASH (exit code 1, unhandled ValueError traceback)

This is the critical test. Here is what happens:

1. StrawPot detects no agent is configured and launches the onboarding wizard
2. The wizard presents a 3-choice menu (Claude Code, Gemini, Codex)
3. User selects option 1 (strawpot-claude-code)
4. StrawPot installs the agent package from StrawHub (succeeds)
5. StrawPot tries to run the agent's install script via `curl | sh` -- **fails because `curl` is not installed**
6. StrawPot tries `npm install -g @anthropic-ai/claude-code` -- **fails because `npm` is not installed**
7. StrawPot prints a warning about failed tool install but continues
8. StrawPot tries to resolve the agent binary at `~/.strawpot/agents/strawpot-claude-code/strawpot_claude_code` -- **crashes with an unhandled ValueError**

The full traceback is:
```
ValueError: Agent binary not found: /root/.strawpot/agents/strawpot-claude-code/strawpot_claude_code
```

This is a hard crash. The user sees a Python traceback, not a helpful error message.

### Step 4: Additional commands

| Command | Result | Notes |
|---|---|---|
| `strawpot --version` | SUCCESS | Prints `strawpot, version 0.1.57` |
| `strawpot config` | SUCCESS | Shows default config with sensible defaults |
| `strawpot init` | ERROR | `No local packages installed. Install packages first with 'strawhub install'.` |
| `strawpot search --query "code-reviewer"` | ERROR | Wrong syntax. The `--query` flag does not exist. Correct usage: `strawpot search code-reviewer` (positional arg). |
| `strawpot list roles` | ERROR | `Got unexpected extra argument (roles)`. The `list` command does not accept a positional filter. |
| `strawpot install role code-reviewer` | SUCCESS | Installs role + skill dependency. Prompts for `gh` tool install, but non-interactive so it skips. |
| `strawpot info role code-reviewer` | SUCCESS | Shows clean role metadata. |

## Friction Points (ordered by severity)

### BLOCKER-1: strawpot start crashes with unhandled ValueError

**What happens:** After the onboarding wizard installs the agent package, `resolve_agent()` throws `ValueError: Agent binary not found` because the underlying CLI tool (e.g., `claude`) was never installed. This surfaces as a raw Python traceback.

**Impact:** 100% of new users will hit this. No one can use StrawPot after a fresh install.

**Suggested fix:**
1. Catch the `ValueError` in `cli.py` and print a user-friendly error: "The Claude Code CLI is not installed. Install it with: `npm install -g @anthropic-ai/claude-code`, then run `strawpot start` again."
2. Before attempting to resolve the agent binary, check if the required system tools (curl, npm, node) are present and give actionable guidance if they are missing.
3. Do not proceed past onboarding if the agent binary does not exist.

### BLOCKER-2: Agent install script requires curl, which is not bundled

**What happens:** The `strawpot-claude-code` agent's install script runs `curl -fsSL <url> | sh`. On minimal systems (Docker, minimal Linux), `curl` is not installed.

**Impact:** The install silently fails (`/bin/sh: 1: curl: not found`) and StrawPot continues as if it succeeded, leading to the crash in BLOCKER-1.

**Suggested fix:**
1. Check for `curl` (or `wget` as fallback) before running the install script.
2. If neither is available, print: "curl is required to install the agent runtime. Install it with your package manager (e.g., `apt install curl`) and try again."
3. Alternatively, use Python's `urllib` or `httpx` (already a dependency) to download the install script, removing the curl dependency entirely.

### BLOCKER-3: npm/node not detected before attempting Claude Code install

**What happens:** `npm install -g @anthropic-ai/claude-code` fails because npm is not installed. The error is: `/bin/sh: 1: npm: not found` with exit code 127. StrawPot prints a warning but then crashes anyway.

**Impact:** Even if curl were present, the Claude Code CLI requires Node.js/npm. A user without Node.js installed will always fail.

**Suggested fix:**
1. Before running `npm install`, check if `npm` and `node` are in PATH.
2. If not, print: "Claude Code requires Node.js. Install Node.js from https://nodejs.org (v18+), then run `strawpot start` again."
3. Add a `strawpot doctor` command that checks all prerequisites.

### HIGH-1: No prerequisite checker or "doctor" command

**What happens:** StrawPot has hidden dependencies that are not documented or checked:
- `curl` (for agent install scripts)
- `npm` / `node` (for Claude Code)
- `git` (for worktree isolation, PR workflows)
- `gh` (GitHub CLI, for PR creation)
- `ANTHROPIC_API_KEY` or equivalent (for the LLM backend)

None of these are checked upfront. Users discover them one at a time through cryptic errors.

**Suggested fix:**
1. Add a `strawpot doctor` command that checks all prerequisites and reports their status.
2. Run prerequisite checks automatically on first `strawpot start` before the onboarding wizard.
3. Print a clear checklist: "StrawPot needs: [x] Python 3.11+ [x] pip [ ] Node.js 18+ [ ] git [ ] gh CLI"

### HIGH-2: No getting-started guide in the CLI

**What happens:** After `pip install strawpot`, the user runs `strawpot --help` and sees 20 commands with no guidance on where to start. There is no `strawpot quickstart`, no post-install message, and no indication that `strawpot start` is the entry point.

**Suggested fix:**
1. Add a post-install banner or first-run message: "Get started: run `strawpot start` to launch your first agent."
2. Reorder `--help` output to put `start` at the top or in a "Getting Started" group.
3. Add a `strawpot quickstart` alias or command that prints a step-by-step guide.

### HIGH-3: The --task flag is silently ignored during onboarding

**What happens:** `strawpot start --task "Review my latest PR"` triggers the interactive onboarding wizard. The `--task` flag is accepted but has no effect until onboarding completes. In non-interactive mode (piped input, CI), this means the task is lost.

**Suggested fix:**
1. If `--task` is provided and no agent is configured, either (a) auto-select the default agent or (b) print a clear message: "No agent configured. Run `strawpot start` first to set up, then re-run with --task."
2. Do not mix interactive prompts with non-interactive flags.

### MEDIUM-1: strawpot search and list have unintuitive syntax

**What happens:**
- `strawpot search --query "code-reviewer"` fails. The correct syntax is `strawpot search code-reviewer` (positional argument).
- `strawpot list roles` fails. The `list` command does not accept a filter argument.

A user guessing at the interface will fail on both.

**Suggested fix:**
1. Add `--query` as an alias for the positional argument in `search`.
2. Accept a positional filter in `list` (e.g., `strawpot list roles`, `strawpot list skills`).
3. Improve error messages to suggest the correct syntax.

### MEDIUM-2: Tool install prompts are not non-interactive-friendly

**What happens:** `strawpot install role code-reviewer` prompts `Install 'gh' (GitHub CLI)? Command: apt install gh [Y/n]:` and waits for input. In non-interactive contexts, this hangs or fails silently.

**Suggested fix:**
1. Add `--yes` / `-y` flag to auto-accept tool installs.
2. Add `--no-tools` flag to skip tool installation.
3. Detect non-interactive terminals and skip prompts (or default to "no").

### MEDIUM-3: Version gap between PyPI and local dev

**What happens:** PyPI has v0.1.57, but the local dev version is 0.1.0. The sub-issue notes this as a concern. While the install works fine from PyPI, anyone cloning the repo and running `pip install -e .` will get a stale version number that could cause confusion.

**Suggested fix:**
1. Align local dev version with PyPI release version.
2. Or use a dev suffix: `0.1.57.dev0`.

### LOW-1: `strawpot` with no args exits with code 2

**What happens:** Running `strawpot` with no arguments shows the help text but exits with code 2 (error). This is standard Click behavior but could confuse scripts.

**Suggested fix:** Set `invoke_without_command=True` on the CLI group to show help and exit 0, or add a note in documentation.

### LOW-2: pip "running as root" and "new release available" warnings

**What happens:** Standard pip warnings appear during install. Not a StrawPot issue, but it adds noise for new users.

**Suggested fix:** None needed. This is expected pip behavior.

## Honest Assessment

**Is StrawPot installable and usable by a stranger today? NO.**

**Evidence:**
- `pip install strawpot` works (installable: yes)
- `strawpot start` crashes 100% of the time on a clean machine (usable: no)
- The crash is an unhandled Python traceback, not a helpful error message
- There are at least 3 prerequisite tools (curl, npm/node, git) that must be installed separately, with no documentation or detection
- The total time from `pip install` to first useful output is **infinity** because the user cannot reach useful output without undocumented manual steps

**What it would take to be usable:**
1. Fix BLOCKER-1, BLOCKER-2, BLOCKER-3 (graceful error handling)
2. Add prerequisite detection (HIGH-1)
3. Add a getting-started guide (HIGH-2)
4. Ensure `strawpot start` can complete end-to-end on a machine with Node.js and git installed

**Estimated effort to fix blockers:** 2-4 hours of engineering work, mostly in `cli.py` and `agents/registry.py`.

## Raw Test Output

Full test output is available in the PR for reference. Key files tested:
- `strawpot/cli.py` (CLI entry point, onboarding wizard)
- `strawpot/agents/registry.py` (agent resolution, binary detection)
