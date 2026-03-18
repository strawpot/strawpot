# StrawPot

Role-based orchestration for AI workers.

Run teams of agents locally, resolve skills automatically, and share roles through StrawHub.

<p align="center">
  <a href="https://github.com/strawpot/strawpot/actions/workflows/release.yml"><img src="https://img.shields.io/github/actions/workflow/status/strawpot/strawpot/release.yml?branch=main&style=for-the-badge&label=PyPI" alt="PyPI Release"></a>
  <a href="https://discord.gg/6RMpzuKrRd"><img src="https://img.shields.io/discord/1476285531464929505?label=Discord&logo=discord&logoColor=white&color=5865F2&style=for-the-badge" alt="Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
</p>

<p align="center">
  <img src="docs/demo.png" alt="StrawPot demo" width="1280">
</p>

## Example

Input: "Add dark mode to the app"

Agents may produce structured outputs such as:
- A launch plan with rollout timeline
- A draft announcement post
- Engineering tasks with sub-issues

AI output quality is still evolving. The orchestration infrastructure is robust.

## Quick Start

```bash
pip install strawpot
strawpot gui
```

## What StrawPot does

An orchestration system where AI agents take roles, delegate sub-tasks, and coordinate in a shared workspace.

- **Concurrent delegation** — agents spawn sub-agents in parallel, not sequential task queues
- **Agent-agnostic** — one wrapper protocol, any runtime (Claude Code, Codex, Gemini, custom)
- **Git worktree isolation** — each session gets its own branch, concurrent sessions safe, crash recovery automatic
- **Persistent memory** — 3-tier context cards (semantic, retrieval, event) that agents read and write across sessions
- **Structured tracing** — every delegation, spawn, and memory access recorded to JSONL with full call tree reconstruction
- **Policy enforcement** — depth limits, timeouts, delegation caching, role-based access control
- **Conversation context** — automatic condensed summaries of prior turns, tiered detail, recap extraction
- **Scheduled tasks** — cron-based recurring and one-time, REST API, skip-if-running

Roles and skills are Markdown files. No Python, no orchestration code.

## What the AI outputs are not (yet)

- Not fully reliable — output quality varies across tasks and models
- Not deterministic — same input may produce different artifacts
- Not autonomous — agents need well-defined roles to be effective

The orchestration, isolation, tracing, and memory systems are solid. The AI output quality improves through better roles, skills, and community iteration.

## Why StrawHub matters

StrawHub is the registry that makes StrawPot an ecosystem, not just a tool.

- **Roles are reusable** — install a role once, use it across projects
- **Skills are composable** — roles pull in the skills they need automatically
- **Behaviors can be shared** — what works for one team benefits everyone
- **Dependency resolution** — topological sort, cycle detection, semver constraints
- **The ecosystem grows** through shared role definitions and community iteration

Without shared roles, you're writing prompts from scratch every time. StrawHub is the compounding mechanism.

[strawhub.dev](https://strawhub.dev)

## Architecture

```
StrawPot (runtime)              StrawHub (ecosystem)
 ├─ Role engine                  ├─ Roles
 ├─ Skill executor               ├─ Skills
 ├─ Memory providers             ├─ Agents
 ├─ Agent adapters               ├─ Integrations
 └─ Web dashboard                └─ Memory providers
```

```
User task → StrawPot → Role (ai-ceo)
                         ├─ Sub-role (implementer)
                         │   ├─ Skills (git-workflow, python-dev)
                         │   └─ Agent (strawpot-claude-code)
                         └─ Sub-role (reviewer)
                             ├─ Skills (code-review, security-baseline)
                             └─ Agent (gemini)
```

## Status

StrawPot provides production-grade orchestration for role-based AI workers.

- Agent coordination, memory, and execution are stable
- Roles and workflows are extensible
- The infrastructure is ready

AI-generated outputs are still evolving and may vary depending on model and task.

## Contributing

Looking for:
- New roles and skills
- Improved agent behaviors and role definitions
- Real workflow examples
- Agent wrapper implementations for new runtimes
- Bug reports and feedback

This project is designed to be extended. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Community

- [Discord](https://discord.gg/6RMpzuKrRd) — questions, feedback, and discussion
- [GitHub Issues](https://github.com/strawpot/strawpot/issues) — bug reports and feature requests

## License

[MIT](LICENSE)

---

<p align="center">
<em>One engineer. One laptop. One AI company.</em><br/>
<strong>StrawPot</strong> — runtime &nbsp;·&nbsp; <strong>StrawHub</strong> — ecosystem &nbsp;·&nbsp; <strong>Denden</strong> — transport
</p>
