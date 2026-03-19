# Contributing to StrawPot

StrawPot is built by AI agents. Humans contribute by describing what they
want — features, bug fixes, improvements — and agents handle the code.

## How to Contribute

### Report a Bug

Open a [GitHub Issue](https://github.com/strawpot/strawpot/issues) with:

- **What happened** — the error, unexpected behavior, or crash
- **What you expected** — the correct behavior
- **Steps to reproduce** — commands, config, or sequence of actions
- **Environment** — OS, Python version, StrawPot version (`strawpot --version`)

Paste logs or tracebacks if available. Screenshots of the GUI help too.

### Request a Feature

Open a [GitHub Issue](https://github.com/strawpot/strawpot/issues) with:

- **What you want** — describe the outcome, not the implementation
- **Why it matters** — what workflow it enables or what problem it solves
- **Example** — a concrete scenario showing how you'd use it

Good: "I want to run the same schedule in multiple projects with different configs."
Less helpful: "Add a `project_id` column to the `scheduled_tasks` table."

### Share an Idea or Ask a Question

Join the [Discord](https://discord.gg/6RMpzuKrRd) for discussion, feedback,
and help getting started.

## What Happens Next

1. You submit an issue describing a bug or feature
2. An AI agent picks it up, reads the codebase, and creates a PR
3. The maintainer reviews and merges

You don't need to write code, set up a dev environment, or understand the
internals. A clear description of the problem is the most valuable contribution.

## Writing Good Prompts

The better you describe the problem, the better the result. Tips:

- **Be specific** — "the Telegram adapter crashes when the bot token is
  empty" beats "integration doesn't work"
- **Include context** — what were you doing, what config do you have
- **One issue per issue** — don't bundle unrelated requests
- **Show examples** — paste terminal output, screenshots, or sample config

## Other Ways to Contribute

- **Design feedback** — review design docs in `designs/` and comment on
  open issues about upcoming features
- **Testing** — try new releases, report what breaks
- **Documentation** — suggest improvements to README or user-facing docs
- **Community adapters** — build and publish integration adapters for new
  platforms via [StrawHub](https://strawhub.dev)

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE).
