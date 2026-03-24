# StrawPot for gstack Users

If you're already using [gstack](https://github.com/garrytan/gstack) — Garry Tan's
open-source AI agent stack for Claude Code — you have a solid foundation of
role-based agents: a CEO that rethinks your product, an eng manager that locks
architecture, a QA lead that opens a real browser, and more. gstack gives you
a collection of specialists as slash commands, all Markdown, all free.

StrawPot builds on top of that foundation. It doesn't replace gstack — it adds
the infrastructure layer that turns ad-hoc agent sessions into persistent,
schedulable, multi-runtime workflows: scheduling, memory, delegation chains,
and a registry that works across Claude Code, Gemini CLI, Codex, OpenHands,
and more.

This guide shows what StrawPot adds and how to get started if you're already
a gstack user.

## What StrawPot adds to gstack

| Capability | gstack | gstack + StrawPot |
|---|---|---|
| **Role-based agents** | Roles as slash commands in Claude Code | Same roles, plus scheduling and persistent memory |
| **Scheduling** | Manual — you run `/review` when needed | Cron-based autonomous execution (e.g., triage every 2 hours) |
| **Memory** | None — each session starts fresh | Persistent memory across sessions via Dial |
| **Delegation** | Single agent per slash command | Multi-agent delegation chains (CEO → planner → implementer → reviewer) |
| **Registry** | `git clone` into `.claude/skills/` | `strawpot install role code-reviewer` — versioned, dependency-resolved |
| **Cross-runtime** | Claude Code (+ Codex/Gemini via SKILL.md) | Native support for Claude Code, Gemini CLI, Codex, OpenHands, Pi |

### Scheduling

StrawPot lets you set up cron-based schedules so agents work autonomously.
Schedules are managed through the web dashboard (`strawpot gui`) or the
REST API:

```bash
# Create a recurring schedule via the API
curl -X POST http://localhost:8741/api/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "triage-every-2h",
    "project_id": 1,
    "task": "Triage all open issues without priority labels",
    "cron_expr": "0 */2 * * *",
    "role": "github-triager"
  }'
```

Or use the dashboard UI: go to **Schedules > Recurring**, click **Create
Schedule**, and fill in the cron expression, role, and task. The scheduler
runs as a background process inside the GUI server, firing
`strawpot start --headless` when a schedule is due. Agents complete their
work and post results directly to GitHub.

### Memory

StrawPot's memory system (powered by Dial) persists knowledge across sessions:

- An agent remembers architectural decisions from last week
- Triage patterns learned in one session carry over to the next
- Code review feedback accumulates into a project-specific knowledge base

Memory is injected automatically — agents don't need special prompting to
benefit from it.

```toml
# strawpot.toml — to disable memory, set provider to ""
[memory]
provider = "dial"  # enabled by default; no config needed unless customizing
```

### Multi-agent delegation

StrawPot enables delegation chains where agents hand off work to specialized
sub-agents:

```
pipeline-orchestrator
  ├── github-triager        (triages the issue)
  ├── implementation-planner (breaks it into sub-issues)
  └── implementation-executor
        ├── implementer     (writes code)
        ├── code-simplifier (simplifies the diff)
        └── pr-reviewer     (reviews the PR)
              ├── code-reviewer
              ├── silent-failure-hunter
              └── type-design-analyzer
```

Each agent has a focused role and delegates to the next. The orchestrator
manages the full lifecycle — from issue triage to opened PR — with
minimal human intervention for routine tasks.

### Registry

StrawPot provides a versioned registry via [StrawHub](https://strawhub.dev):

```bash
# Install a single role with all its dependencies
strawpot install role code-reviewer

# Install a skill
strawpot install skill git-workflow

# Search for available resources
strawpot search "code review"

# List what's installed
strawpot list
```

Roles are versioned, updates are a single command, and dependencies are
resolved automatically.

## Quick start for gstack users

### 1. Install StrawPot

```bash
pip install strawpot
```

### 2. Run your first session

From any git repository:

```bash
strawpot start
```

On first run, StrawPot launches an onboarding wizard that configures your
agent runtime (Claude Code by default — the same runtime gstack uses).

### 3. Run with a task

```bash
strawpot start --task "Triage all open issues in my repo"
```

This starts a session with the pipeline orchestrator, which delegates to
specialized agents as needed. No slash commands required — describe what
you want done and the orchestrator figures out which agents to involve.

### 4. Set up scheduled agents

Launch the web dashboard:

```bash
strawpot gui
```

In the dashboard at `http://localhost:8741`, go to **Schedules > Recurring**
and create a schedule. For example, to triage issues every 2 hours:

| Field | Value |
|-------|-------|
| Name | `triage-every-2h` |
| Project | *(your project)* |
| Task | `Triage all open issues without priority labels` |
| Cron Expression | `0 */2 * * *` |
| Role | `github-triager` |

The scheduler runs in the background while the GUI server is running, firing
headless sessions on each cron tick. The dashboard also lets you manage
projects, browse installed roles and skills, and view run history.

## Example: before and after

### With gstack alone

1. Open Claude Code
2. Run `/review` on your current branch
3. Read the review, make changes
4. Run `/qa` on staging
5. Run `/ship` to create the PR

Each step is manual and each session starts from scratch.

### With gstack + StrawPot

**Scheduled (via the GUI scheduler):**
1. **github-triager** runs every 2 hours — new issues get labeled and prioritized
2. **pr-reviewer** runs nightly — open PRs get comprehensive reviews posted as GitHub comments

**Interactive (via `strawpot start`):**
3. **pipeline-orchestrator** picks up high-priority issues and delegates:
   planner breaks it into sub-issues, implementer writes the code,
   reviewer checks the PR

**Across all sessions:**
4. Memory carries context forward — the reviewer knows your project's patterns,
   the triager learns your labeling conventions

You still use gstack's slash commands for ad-hoc interactive work. StrawPot
adds the scheduled automation and cross-session memory on top.

## What StrawPot requires

- **Python 3.11+** — `pip install strawpot`
- **An AI agent CLI** — Claude Code (which you already have), Gemini CLI, Codex, etc.
- **tmux** (recommended) — for interactive sessions
- **Denden gRPC server** — starts automatically with `strawpot start`
- **Configuration** — `strawpot.toml` per project, `~/.strawpot/strawpot.toml` for global settings

The tradeoff versus gstack is more setup for more automation. gstack is a set of
Markdown files; StrawPot is a CLI + server + registry + memory system.

## Using gstack roles alongside StrawPot

gstack roles and StrawPot roles coexist without conflict:

- **gstack roles** live in `.claude/skills/gstack/` and are invoked via slash commands
- **StrawPot roles** are installed via StrawHub and invoked via delegation through Denden

You can use gstack's `/review` for interactive reviews in your terminal and
StrawPot's scheduled `pr-reviewer` for autonomous nightly reviews. They serve
different workflows.

## Further reading

- [StrawPot Quickstart](https://docs.strawpot.com/quickstart) — Full installation and configuration guide
- [Architecture](https://docs.strawpot.com/concepts/architecture) — How the delegation and memory systems work
- [StrawHub](https://strawhub.dev) — Browse available roles and skills
- [Memory](https://docs.strawpot.com/concepts/memory) — How persistent memory works across sessions
- [GitHub](https://github.com/strawpot/strawpot) — Source code, issues, and discussions
