# StrawPot

A production-grade multi-agent execution system.

Most AI agents follow predefined workflows.

StrawPot lets agents figure out how to solve the task.

Agents decide how to solve tasks by composing other agents. No fixed pipelines. No hardcoded flows.

Concurrent execution with isolation, memory, and full traceability. Outputs vary. Infrastructure does not.

<p align="center">
  <a href="https://github.com/strawpot/strawpot/actions/workflows/release.yml"><img src="https://img.shields.io/github/actions/workflow/status/strawpot/strawpot/release.yml?branch=main&style=for-the-badge&label=PyPI" alt="PyPI Release"></a>
  <a href="https://discord.gg/6RMpzuKrRd"><img src="https://img.shields.io/discord/1476285531464929505?label=Discord&logo=discord&logoColor=white&color=5865F2&style=for-the-badge" alt="Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
</p>

<p align="center">
  <img src="docs/demo.png" alt="StrawPot demo" width="1280">
</p>

## Example: how agents coordinate

Input: "Add dark mode to the app"

Agents break down the task, assign roles, and coordinate:
- **ai-ceo** plans the rollout and delegates
- **implementer** writes code in an isolated worktree
- **reviewer** checks the changes and approves

Structured artifacts land in your workspace — a plan, draft post, and engineering tasks. Outputs vary depending on model and task.

## What you can do with StrawPot today

**Automatically triage and plan GitHub issues**
Agents prioritize based on project direction, break approved issues into ordered sub-tasks, and delegate implementation — using role-based coordination.

**Turn an idea into a PR**
Automatically go from idea to shipped code — ideation, approval, implementation in an isolated worktree, code review, and QA.

**Create and refine roles automatically**
Define new roles, test them through evaluation and iteration, and publish to StrawHub for reuse.

Workflows improve over time as roles are reused and refined.

## Quick Start

```bash
pip install strawpot
strawpot gui
```

## Why this exists

Most AI agent systems stop at orchestration. They run prompts. They don't evolve behavior, share reusable roles, or build on each other.

StrawPot is designed to make AI workers composable, reusable, and evolvable — and to distribute what works through StrawHub.

The infrastructure is ready. The next problem is how agent behaviors evolve and improve. That's what we're building toward.

## What StrawPot does

A system where agents dynamically compose roles to complete tasks.

- Agents choose which roles to delegate to
- Roles define behavior and can be reused
- Workflows emerge from role composition, not hardcoded pipelines
**Hierarchical multi-agent delegation**
A CEO role delegates to PM, PM delegates to implementer, implementer delegates to code-reviewer — recursively, concurrently, with full traceability. Each delegation is policy-controlled (depth limits, timeouts, caching) and traced to JSONL with span IDs for complete call tree reconstruction.

**Agent-agnostic runtime**
One wrapper protocol, any AI tool. Claude Code, Codex, Gemini, or your own — assigned per role, mixed in the same session. Adding a new runtime means implementing two commands: `setup` and `build`.

**Git worktree isolation**
Every session gets its own git branch in an isolated worktree. Multiple sessions run concurrently without conflicts. Crash recovery is automatic. Changes merge back via configurable strategies (local patch, PR, or auto-detect).

**Persistent memory across sessions**
Three-tier context cards — semantic (always included), retrieval (matched by task keywords), and event (append-only log). Agents read and write memory dynamically. Persists across sessions and projects through pluggable providers.

**Conversation context handover**
Multi-turn conversations carry condensed summaries of prior turns, file change tracking, and structured recaps. Agents pick up where the last one left off.

**Scheduled automation**
Cron-based recurring and one-time sessions with skip-if-running, REST API, and run history. Agents work on your projects while you sleep.

Roles and skills are Markdown files. No Python, no orchestration code.

## What the AI outputs are not (yet)

- Not fully reliable — output quality varies across tasks and models
- Not deterministic — same input may produce different artifacts
- Not autonomous — agents need well-defined roles to be effective

The orchestration, isolation, tracing, and memory systems are solid. The AI output quality improves through better roles, skills, and community iteration.

## StrawHub — why this project matters

StrawPot without StrawHub is just another orchestration tool. StrawHub is what makes it an ecosystem.

A registry for AI worker behaviors:
- **Share roles** that work — install them across projects with one command
- **Reuse workflows** — skills compose automatically through dependency resolution
- **Evolve behaviors** — roles improve through community iteration, not just prompt engineering

Without shared roles, agent systems reset every time. StrawHub prevents that. The system improves as roles are shared and refined.

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

## Why contribute?

- Define new roles that other teams can install
- Improve agent behaviors through iteration
- Build reusable workflows for real problems
- Add support for new AI runtimes

This system is designed to grow through shared contributions. Every role you publish to StrawHub makes the ecosystem stronger.

See [CONTRIBUTING.md](CONTRIBUTING.md).

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
