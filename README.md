# StrawPot

AI agents work better in teams.

<p align="center">
  <a href="https://github.com/strawpot/strawpot/actions/workflows/release.yml"><img src="https://img.shields.io/github/actions/workflow/status/strawpot/strawpot/release.yml?branch=main&style=for-the-badge&label=PyPI" alt="PyPI Release"></a>
  <a href="https://discord.gg/buEbvEMC"><img src="https://img.shields.io/discord/1476285531464929505?label=Discord&logo=discord&logoColor=white&color=5865F2&style=for-the-badge" alt="Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
</p>

Install roles like Team Lead, Implementer, or Analyst.
StrawPot automatically resolves the skills needed for the job and launches the team.

It orchestrates multiple agents (Claude Code, Codex, Gemini)
in isolated environments using roles and skills from
[StrawHub](https://strawhub.dev). Agents communicate through
[Denden](https://github.com/strawpot/denden), a gRPC transport layer.

```
strawpot start --role team-lead
```

## Architecture

StrawPot coordinates three components:

- **StrawPot** — local orchestrator CLI
- **[Denden](https://github.com/strawpot/denden)** — agent-to-orchestrator communication layer
- **[StrawHub](https://strawhub.dev)** — registry for roles and skills

```
User task
  ↓
StrawPot CLI
  ↓
Orchestrator agent (team-lead)
  ↓
Sub-agents (implementer, reviewer, etc.)
  ↓
Roles & skills resolved from StrawHub
```

## Execution Flow

When you start a session:

1. StrawPot creates an isolated git worktree
2. Starts the Denden gRPC server for agent communication
3. Launches the orchestrator agent (e.g. team-lead)
4. Agents delegate tasks to other roles
5. StrawPot installs required roles and skills from StrawHub
6. Sub-agents run inside the same environment
7. On exit, everything is cleaned up automatically

## The Workforce Model

Skills are abilities. Roles are jobs. Teams are roles collaborating.

- **Skills** — Atomic capabilities such as writing code, searching documents, or running tests.
- **Roles** — Job definitions that automatically load the skills needed for the work.
- **Teams** — Roles collaborating to complete tasks.

Install a role. StrawPot resolves the skills automatically.

```
Role: implementer
 ├─ git-workflow
 ├─ python-dev
 ├─ run-tests
 └─ code-review
```

## Supported Agent Runtimes

StrawPot can orchestrate different agent runtimes:

- Claude Code
- Codex
- Gemini

Mix and match per role. Additional runtimes can be added via agent configuration.

## Install

```
pip install strawpot
```

Or from source:

```
cd cli
pip install -e ".[dev]"
```

## Quick Start

Start a multi-agent session:

```bash
strawpot start --role team-lead
```

Install roles and skills:

```bash
strawpot install role implementer
strawpot install skill git-workflow
```

Search available roles:

```bash
strawpot search implementer
```

## Usage

```bash
# Start a session (foreground, interactive)
strawpot start
strawpot start --role team-lead --runtime claude_code

# Install skills and roles from StrawHub
strawpot install skill git-workflow
strawpot install role implementer

# Search and list
strawpot search "code review"
strawpot list

# Show merged config
strawpot config
```

## Configuration

Global: `$STRAWPOT_HOME/strawpot.toml` (default `~/.strawpot/strawpot.toml`)
Project: `strawpot.toml` (project root)

```toml
runtime = "claude_code"       # claude_code | codex | gemini
isolation = "worktree"        # worktree | docker

[denden]
addr = "127.0.0.1:9700"

[orchestrator]
role = "team-lead"

[policy]
allowed_roles = ["implementer", "reviewer", "fixer"]
max_depth = 3
```

## Repository Structure

```
cli/          StrawPot CLI implementation
gui/          Web GUI (planned)
DESIGN.md     System architecture
```

See [DESIGN.md](DESIGN.md) for architecture details.
