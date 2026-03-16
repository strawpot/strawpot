# StrawPot

One engineer. One laptop. One AI company.

Run an AI company locally — CEO, engineer, QA, and reviewer — collaborating to ship your product.

<p align="center">
  <a href="https://github.com/strawpot/strawpot/actions/workflows/release.yml"><img src="https://img.shields.io/github/actions/workflow/status/strawpot/strawpot/release.yml?branch=main&style=for-the-badge&label=PyPI" alt="PyPI Release"></a>
  <a href="https://discord.gg/2BRsCRUrKb"><img src="https://img.shields.io/discord/1476285531464929505?label=Discord&logo=discord&logoColor=white&color=5865F2&style=for-the-badge" alt="Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
</p>

<!-- TODO: Replace with actual demo GIF/video — this is the #1 factor for GitHub star conversion -->
<p align="center">
  <img src="https://strawpot.com/demo.gif" alt="StrawPot demo — AI workforce running locally" width="720">
</p>

Run an AI company on your laptop.

StrawPot launches a CEO agent that delegates tasks to engineers, reviewers, and testers automatically.

## Quick Start

```bash
pip install strawpot
strawpot gui
```

## Example Session

```
$ strawpot start "Build a landing page"

[CEO] Analyzing task...
  → Delegating implementation to Engineer
  → Delegating review to Reviewer

[Engineer] Generating HTML and CSS...
  ✓ Created index.html
  ✓ Created styles.css

[QA] Running tests...
  ✓ All checks passed

[Reviewer] Reviewing code...
  ✓ Code approved

You: Approve deployment? (y/n)
```

## What Is StrawPot?

StrawPot runs an AI company on your laptop.

- **Roles** — Jobs
- **Skills** — Abilities
- **Memory** — Shared knowledge
- **Integrations** — Chat adapters (Telegram, Slack, Discord)

```yaml
# ai-ceo/ROLE.md
---
name: ai-ceo
description: "Orchestrator that analyzes tasks and delegates to the best-fit role."
metadata:
  strawpot:
    dependencies:
      roles:
        - "*"
    default_agent: strawpot-claude-code
---

You are a routing layer with judgment. The user brings you a task —
you figure out which role on your team should handle it and delegate.
```

No Python. No orchestration code. One Markdown file.

## Features

- **Define an AI CEO in one Markdown file**
- **Install new roles from StrawHub**
- **Run an entire AI workforce locally**
- **Works with Claude, Codex, Gemini**
- **Persistent memory across sessions**
- **Chat integrations** — connect Telegram, Slack, or Discord as conversation interfaces

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

1. Creates an isolated environment (worktree or project dir)
2. Starts the Denden gRPC server for agent communication
3. Retrieves memory context from past sessions
4. Launches the orchestrator agent (e.g. ai-ceo)
5. Agents delegate tasks to sub-roles automatically
6. Required roles and skills are resolved from StrawHub
7. On exit, records results to memory and cleans up

## Chat Integrations

Connect chat platforms as conversation interfaces. Messages route through
**imu** (StrawPot's self-operation agent) — the same agent that powers the
GUI chat. Adapters are standalone processes managed from the GUI.

```
Telegram / Slack / Discord
        ↓
    Adapter (thin relay)
        ↓
    imu (project_id=0)
        ↓
    delegates to projects/roles
```

Install and manage from the GUI Integrations page, or via CLI:

```bash
strawhub install integration telegram
strawpot gui   # → Integrations page to configure and start
```

Adapters support auto-start, config via env vars, health checks, and
real-time log streaming. Community authors can build and publish adapters
for any platform through StrawHub.

## Ecosystem

| Project | What it does |
|---------|------|
| [**StrawPot**](https://strawpot.com) | Runtime — runs role-based AI agents locally |
| [**StrawHub**](https://strawhub.dev) | Registry — distributes roles, skills, agents, memories, and integrations |
| [**Denden**](https://github.com/strawpot/denden) | Transport — gRPC bridge between agents and the orchestrator |

## CLI Usage

```bash
# Start a session
strawpot start
strawpot start --role ai-ceo --runtime strawpot-claude-code

# Install skills, roles, and integrations from StrawHub
strawpot install skill git-workflow
strawpot install role implementer
strawhub install integration telegram

# Search and list
strawpot search "code review"
strawpot list

# Web dashboard
strawpot gui

# Show merged config
strawpot config
```

## Configuration

Global: `$STRAWPOT_HOME/strawpot.toml` (default `~/.strawpot/strawpot.toml`)
Project: `strawpot.toml` (project root)

```toml
runtime = "strawpot-claude-code"       # strawpot-claude-code | strawpot-codex | strawpot-gemini
isolation = "none"                     # none | worktree | docker

[orchestrator]
role = "ai-ceo"

[policy]
max_depth = 3
max_num_delegations = 0       # 0 = unlimited

[memory]
provider = "dial"             # default; "" to disable
```

---

<p align="center">
The future company may look different.<br>
One human. Hundreds of AI workers.<br>
<strong>StrawPot is an operating system for that future.</strong>
</p>
