# StrawPot

One engineer. One laptop. One AI company.

One engineer. A full AI workforce — CEO, product manager, engineer, tester, reviewer — collaborating to ship your product.

**StrawPot**: https://strawpot.com

**StrawHub** (Registry): https://strawhub.dev

<p align="center">
  <a href="https://github.com/strawpot/strawpot/actions/workflows/release.yml"><img src="https://img.shields.io/github/actions/workflow/status/strawpot/strawpot/release.yml?branch=main&style=for-the-badge&label=PyPI" alt="PyPI Release"></a>
  <a href="https://discord.gg/buEbvEMC"><img src="https://img.shields.io/discord/1476285531464929505?label=Discord&logo=discord&logoColor=white&color=5865F2&style=for-the-badge" alt="Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
</p>

```
             You
              │
           ┌──┴──┐
           │ CEO │
           └──┬──┘
     ┌────────┼─────────┐
  ┌──┴──┐   ┌─┴───┐  ┌──┴──┐
  │  PM │   │ Eng │  │  QA │
  └──┬──┘   └──┬──┘  └──┬──┘
     │         │        │
  Analyst    Tester  Reviewer
```

You're an engineer, not a CEO. Building technology is the easy part — strategy, product planning, coordination, documentation, sales, testing, and finance are the rest. StrawPot replaces all of that with AI agents you define in Markdown.

## Quick Start

```bash
pip install strawpot
strawpot install role ai-ceo
strawpot start
```

## Your CEO Is a Markdown File

```yaml
# ai-ceo/ROLE.md
---
name: ai-ceo
description: "Plans strategy and delegates to the team"
metadata:
  strawpot:
    dependencies:
      roles: [pm, implementer, reviewer]
    default_agent: strawpot-claude-code
---

# CEO

Plan strategy and break it into deliverables.
Delegate planning, implementation, and review to sub-roles.
```

No Python. No orchestration code. One file.

## How It Compares

| | CrewAI | OpenClaw | StrawPot |
|---|---|---|---|
| **Format** | YAML + Python | JSON5 + Markdown | Markdown only |
| **Skills / Tools** | Python (tools) | Markdown (skills) | Markdown (skills) |
| **Roles** | Agent attribute | — | Standalone Markdown |
| **Memory** | Python config | Markdown/YAML (local) | Markdown (installable) |
| **Skill dependency resolution** | — | — | Automatic |
| **Multi-agent delegation** | Python config | Runtime (subagent spawn) | Declarative (role deps) |

## Why StrawPot?

- **Zero boilerplate** — A role is a Markdown file with YAML frontmatter. That's it.
- **Automatic dependency resolution** — Install a role and every skill it needs comes with it.
- **Declarative delegation** — An ai-ceo role depends on other roles. StrawPot handles the orchestration.
- **Installable memory** — Memory banks are packages. Install shared context and patterns from StrawHub.
- **Agent-agnostic** — Same role works with Claude Code, Codex, Gemini, or your own runtime.

## How It Works

```
User task → StrawPot → Role (ai-ceo)
                         ├─ Sub-role (implementer)
                         │   ├─ Skills (git-workflow, python-dev)
                         │   └─ Agent (strawpot-claude-code)
                         └─ Sub-role (reviewer)
                             ├─ Skills (code-review, security-baseline)
                             └─ Agent (gemini)
```

When you run `strawpot start`:

1. Creates an isolated git worktree
2. Starts the Denden gRPC server for agent communication
3. Retrieves memory context from past sessions
4. Launches the orchestrator agent (e.g. ai-ceo)
5. Agents delegate tasks to sub-roles automatically
6. Required roles and skills are resolved from StrawHub
7. On exit, records results to memory and cleans up

## The Workforce Model

Skills are abilities. Roles are jobs. Teams are roles collaborating.

- **Skills** — Atomic capabilities such as writing code, searching documents, or running tests.
- **Roles** — Job definitions that automatically load the skills needed for the work.
- **Teams** — Roles collaborating to complete tasks.
- **Memories** — Persistent knowledge banks shared across sessions.

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
strawpot start --role ai-ceo --runtime strawpot-claude-code

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
runtime = "strawpot-claude-code"       # strawpot-claude-code | codex | gemini
isolation = "worktree"        # worktree | docker

[denden]
addr = "127.0.0.1:9700"

[orchestrator]
role = "ai-ceo"

[policy]
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

---

<p align="center">
The future company may look different.<br>
One human. Hundreds of AI workers.<br>
<strong>StrawPot is an operating system for that future.</strong>
</p>
