# StrawPot

Run an AI company on your laptop.

One task. Six AI agents. Zero coordination.

<p align="center">
  <a href="https://github.com/strawpot/strawpot/actions/workflows/release.yml"><img src="https://img.shields.io/github/actions/workflow/status/strawpot/strawpot/release.yml?branch=main&style=for-the-badge&label=PyPI" alt="PyPI Release"></a>
  <a href="https://discord.gg/6RMpzuKrRd"><img src="https://img.shields.io/discord/1476285531464929505?label=Discord&logo=discord&logoColor=white&color=5865F2&style=for-the-badge" alt="Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
</p>

<p align="center">
  <img src="docs/demo.png" alt="StrawPot demo — one task, six AI agents, zero coordination" width="1280">
</p>

**Input:** "Add dark mode to the app"

**Output:**
- ✓ Launch plan with rollout timeline
- ✓ X post: "Dark mode shipped. Built with AI agents."
- ✓ Engineering tasks: update UI theme, add toggle, test contrast
- ✓ Code reviewed and approved

You give one task. It produces the plan, content, and execution.

## Quick Start

```bash
pip install strawpot
strawpot gui
```

## Why

Engineers hate PM, ops, and marketing overhead.

StrawPot replaces those roles with AI agents — defined in Markdown, orchestrated automatically, running locally on your machine.

## What makes it different

- **Role-based agents** — CEO, engineer, reviewer, marketer — each with defined responsibilities
- **Local-first** — runs on your laptop, no cloud, no accounts, SQLite on disk
- **Markdown-defined** — roles and skills are just Markdown files, not Python code
- **StrawHub ecosystem** — install roles and skills with one click from the registry
- **Multi-agent delegation** — agents spawn sub-agents and coordinate automatically

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

## Ecosystem

| Project | What it does |
|---------|------|
| [**StrawPot**](https://strawpot.com) | Runtime — executes role-based AI agents locally |
| [**StrawHub**](https://strawhub.dev) | Registry — distributes roles, skills, agents, and integrations |
| [**Denden**](https://github.com/strawpot/denden) | Transport — gRPC bridge between agents and the runtime |

## Community

- [Discord](https://discord.gg/6RMpzuKrRd) — questions, feedback, and discussion
- [GitHub Issues](https://github.com/strawpot/strawpot/issues) — bug reports and feature requests

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[MIT](LICENSE)

---

<p align="center">
<em>One engineer. One laptop. One AI company.</em><br/>
<strong>StrawPot</strong> — runtime &nbsp;·&nbsp; <strong>StrawHub</strong> — ecosystem &nbsp;·&nbsp; <strong>Denden</strong> — transport
</p>
