# StrawPot

Define your AI team in Markdown. No Python. No orchestration code.

<p align="center">
  <a href="https://github.com/strawpot/strawpot/actions/workflows/release.yml"><img src="https://img.shields.io/github/actions/workflow/status/strawpot/strawpot/release.yml?branch=main&style=for-the-badge&label=PyPI" alt="PyPI Release"></a>
  <a href="https://discord.gg/buEbvEMC"><img src="https://img.shields.io/discord/1476285531464929505?label=Discord&logo=discord&logoColor=white&color=5865F2&style=for-the-badge" alt="Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
</p>

```
# CrewAI: 40 lines of Python to define a 2-agent team
# OpenClaw: Skills in Markdown, but no roles or dependency resolution
# StrawPot: One ROLE.md file. Done.
```

| | CrewAI | OpenClaw | StrawPot |
|---|---|---|---|
| **Format** | YAML + Python | JSON5 + Markdown | Markdown only |
| **Skills / Tools** | Python (tools) | Markdown (skills) | Markdown (skills) |
| **Roles** | Agent attribute | — | Standalone Markdown |
| **Skill dependency resolution** | — | — | Automatic |
| **Multi-agent delegation** | Python config | Runtime (subagent spawn) | Declarative (role deps) |
| **Persistent memory** | — | — | Built-in (pluggable providers) |

## Quick Start

```bash
pip install strawpot
strawpot install role team-lead
strawpot start
```

## Why StrawPot?

- **Zero boilerplate** — A role is a Markdown file with YAML frontmatter. That's it.
- **Automatic dependency resolution** — Install a role and every skill it needs comes with it.
- **Declarative delegation** — A team-lead role depends on other roles. StrawPot handles the orchestration.
- **Persistent memory** — Agents learn from past sessions. Context is retrieved before each run and results are recorded after.
- **Agent-agnostic** — Same role works with Claude Code, Codex, Gemini, or your own runtime.

## How It Works

```
User task → StrawPot → Role (team-lead)
                         ├─ Sub-role (implementer)
                         │   ├─ Skills (git-workflow, python-dev)
                         │   └─ Agent (claude_code)
                         └─ Sub-role (reviewer)
                             ├─ Skills (code-review, security-baseline)
                             └─ Agent (gemini)
```

When you run `strawpot start`:

1. Creates an isolated git worktree
2. Starts the Denden gRPC server for agent communication
3. Retrieves memory context from past sessions
4. Launches the orchestrator agent (e.g. team-lead)
5. Agents delegate tasks to sub-roles automatically
6. Required roles and skills are resolved from StrawHub
7. On exit, records results to memory and cleans up

## The Workforce Model

Skills are abilities. Roles are jobs. Teams are roles collaborating.

- **Skills** — Atomic capabilities such as writing code, searching documents, or running tests.
- **Roles** — Job definitions that automatically load the skills needed for the work.
- **Teams** — Roles collaborating to complete tasks.

```
Role: implementer
 ├─ git-workflow
 ├─ python-dev
 ├─ run-tests
 └─ code-review
```

## Ecosystem

| Project | Role |
|---------|------|
| [**StrawPot**](https://strawpot.com) | Runtime — runs role-based AI agents locally |
| [**StrawHub**](https://strawhub.dev) | Registry — distributes roles, skills, agents, and memories |
| [**Denden**](https://github.com/strawpot/denden) | Transport — gRPC bridge between agents and the orchestrator |

## Usage

```bash
# Start a session
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

[memory]
provider = "dial"             # default; "" to disable
```

## Repository Structure

```
cli/          StrawPot CLI implementation
gui/          Web GUI (planned)
DESIGN.md     System architecture
```

See [DESIGN.md](DESIGN.md) for architecture details.
