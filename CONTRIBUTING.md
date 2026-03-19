# Contributing to StrawPot

Thank you for your interest in contributing to StrawPot! This guide covers
both human developers and AI agents working on the codebase.

## Project Structure

```
strawpot/
  cli/          Python CLI — agent orchestration, sessions, delegation
  gui/          FastAPI backend + React frontend (dashboard)
  designs/      Design documents and decision tracking
  docs/         Additional documentation
  scripts/      Utility scripts
```

**Related repositories:**

| Repo | Purpose |
|------|---------|
| [strawhub](https://github.com/strawpot/strawhub) | Registry CLI + server (strawhub.dev) |
| [denden](https://github.com/strawpot/denden) | gRPC transport for agent communication |
| [integrations](https://github.com/strawpot/integrations) | Chat platform adapters (Telegram, Slack, Discord) |

## Development Setup

**Requirements:** Python 3.11+, Node.js 18+

### Backend (CLI + GUI)

```bash
# CLI
cd cli
pip install -e ".[dev]"

# GUI (depends on CLI)
cd gui
pip install -e ../cli
pip install -e ".[dev]"
```

### Frontend

```bash
cd gui/frontend
npm install
npm run dev       # Vite dev server
npm run build     # Production build
```

## Running Tests

```bash
# CLI unit tests
cd cli
pytest tests/ --ignore=tests/e2e --cov=strawpot --cov-report=term-missing

# CLI E2E tests (slower, requires git)
pytest tests/e2e -v --timeout=30

# GUI tests
cd gui
pytest tests/ -v --timeout=30
```

CI runs on Python 3.11, 3.12, and 3.13 across Ubuntu and macOS.

## Git Workflow

1. **Never push directly to `main`.** Always create a branch and open a PR.
2. Branch naming: `claude/<description>` for AI agents, `<username>/<description>` for humans.
3. Keep PRs focused — one logical change per PR.
4. Rebase from `main` before opening a PR:
   ```bash
   git fetch origin && git rebase origin/main
   ```
5. Once a PR is merged, create a fresh branch for the next change. Don't reuse merged branches.

## Design Documents

Major features start with a design document in `designs/`. Each design
includes an **Implementation Status** table tracking individual items.
Check the relevant design doc before working on a feature area:

| Area | Design doc |
|------|-----------|
| Core architecture | `designs/DESIGN.md` |
| GUI | `designs/gui/DESIGN.md` |
| Integrations | `designs/integration/DESIGN.md` |
| Context & history | `designs/context/DESIGN.md` |
| Scheduling | `designs/schedule/DESIGN.md` |
| Onboarding | `designs/onboarding/DESIGN.md` |
| imu (self-operation) | `designs/imu/DESIGN.md` |

## For AI Agents

- Read `CLAUDE.md` for git workflow rules and conventions.
- Read the relevant design doc before making changes to a feature area.
- Show the full `git diff` for review before committing.
- Wait for explicit approval before committing or pushing.
- Don't over-engineer — make the minimum change needed for the task.

## For Human Contributors

- Check `TODO.md` for open work items.
- For questions or discussion, join the [Discord](https://discord.gg/6RMpzuKrRd).
- If you're unsure where to start, look at design docs with items that aren't marked "Done".

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE).
