# Contributing to StrawPot

StrawPot grows through builders solving real problems and sharing
what works. Whether you create a role, write a skill, build a
memory provider, or improve the core — every contribution makes
the ecosystem stronger for everyone.

If you've built something useful for your own workflow, consider
publishing it. The next person shouldn't have to start from
scratch.

---

## What You Can Contribute

| Contribution | What It Is | Where It Lives |
|---|---|---|
| **Role** | A markdown file that defines an agent's behavior, responsibilities, and delegation rules | Your project's `roles/<role-name>/ROLE.md` |
| **Skill** | A markdown file that gives an agent domain-specific knowledge or capabilities | Your project's `skills/<skill-name>/SKILL.md` |
| **Memory provider** | A pluggable backend for persistent agent memory (e.g., Dial) | Core or StrawHub |
| **Agent adapter** | Runtime integration for a new AI tool (Claude Code, Codex, Gemini, etc.) | Core |
| **Integration** | Connect StrawPot to external platforms (GitHub, Slack, etc.) | StrawHub |
| **Documentation** | Guides, tutorials, API references at [docs.strawpot.com](https://docs.strawpot.com) | `docs/` |
| **Bug reports & ideas** | Issues describing problems or improvements | [GitHub Issues](https://github.com/strawpot/strawpot/issues) |

You don't need deep StrawPot expertise to contribute. If you can
write markdown, you can write a role.

---

## Getting Started

### Prerequisites

- Python 3.11+
- Git
- A supported AI runtime (Claude Code, Codex, or Gemini)

### Install StrawPot

```bash
pip install strawpot
```

Verify the installation:

```bash
strawpot --version
```

### Set Up a Dev Environment

1. Fork and clone the repository:

   ```bash
   git clone https://github.com/<your-username>/strawpot.git
   cd strawpot
   ```

2. Install the CLI in development mode:

   ```bash
   pip install -e "./cli[dev]"
   ```

3. Run the test suite to confirm everything works:

   ```bash
   pytest cli/tests/
   ```

4. Start the GUI to explore the system:

   ```bash
   strawpot gui
   ```

---

## Creating a Role

A role is a markdown file that tells an agent what it does, how it
behaves, and who it can delegate to. Roles are the building blocks
of every StrawPot workflow.

### Quick example

Create `roles/my-role/ROLE.md` in your project:

```markdown
---
name: my-role
description: Generates inline documentation for source files
metadata:
  strawpot:
    dependencies:
      skills:
        - git-workflow
        - python-dev
      roles:
        - code-reviewer
---
You are a code documentation generator. You read source files
and produce clear, concise inline documentation.
```

Roles use YAML frontmatter for metadata (name, description,
dependencies) and plain markdown for the agent's instructions.

### Key concepts

- **One role = one responsibility.** A role should do one thing
  well. Use delegation for multi-step workflows.
- **Skills extend roles.** List skills under
  `metadata.strawpot.dependencies.skills` to give a role
  specific knowledge.
- **Delegation chains.** List delegatable roles under
  `metadata.strawpot.dependencies.roles`. Roles delegate to
  other roles, forming a coordination tree with policy controls.

For the full guide — including delegation rules, memory
configuration, and evaluation workflows — see the
[roles documentation](https://docs.strawpot.com).

---

## Creating a Skill

A skill is domain-specific knowledge packaged as a markdown file.
Roles reference skills to gain capabilities without duplicating
instructions.

### Quick example

Create `skills/my-skill/SKILL.md` in your project:

```markdown
# My Custom Skill

Use this skill when the user asks to format Python code
according to the project's style guide.

## Style Rules

- Use Black with line length 88
- Sort imports with isort
- Type hints required on all public functions
```

### Guidelines

- **Trigger condition first.** Start with "Use this skill
  when..." so agents know when to activate it.
- **Focused scope.** One skill covers one domain. Don't combine
  unrelated knowledge into a single skill.
- **Actionable content.** Include the actual instructions an
  agent needs — not just pointers to external docs.

Full skill authoring guide:
[docs.strawpot.com](https://docs.strawpot.com)

---

## Publishing to StrawHub

[StrawHub](https://strawhub.dev) is the package registry for
roles, skills, agents, and integrations. Install what the
community built. Publish what you've built.

### Install a package

```bash
strawhub install role code-reviewer
strawhub install skill git-workflow
```

### Publish your work

```bash
strawhub publish role my-custom-role
strawhub publish skill my-custom-skill
```

The publish command validates your package, bundles it, and
uploads it to the registry. Once published, anyone can install
it with a single command.

For publishing requirements and package metadata, see the
[publishing guide](https://docs.strawpot.com).

---

## Code Standards and Conventions

- **Roles and skills are markdown.** No Python, no orchestration
  code. Define behavior in plain text.
- **Configuration is TOML.** Project-level config lives in
  `strawpot.toml`.
- **Branch naming:** `claude/<branch-name>` for all feature
  branches.
- **Never push directly to `main`.** Always open a PR.
- **Tests:** Run `pytest` before submitting. Add tests for new
  functionality when applicable.
- **Linting:** Follow the project's existing code style.

For architecture details, see the
[concepts documentation](https://docs.strawpot.com).

---

## Pull Request Process

1. **Create a branch** from `main`:

   ```bash
   git checkout -b claude/my-feature
   ```

2. **Make your changes.** Keep commits focused — one logical
   change per commit.

3. **Rebase from main** before opening the PR:

   ```bash
   git fetch origin && git rebase origin/main
   ```

4. **Open a PR** with a clear title and description:
   - What changed and why
   - How to test it
   - Link to the related issue, if any

5. **Wait for review.** A maintainer will review your PR. Address
   feedback by pushing new commits (don't force-push unless
   asked).

6. **Merge.** Once approved, the maintainer merges your PR.
   Don't reuse merged branches — create a fresh branch for the
   next change.

---

## Community Guidelines

We keep it straightforward:

- **Be respectful.** Disagree on ideas, not people.
- **Be constructive.** Criticism is welcome when paired with
  suggestions.
- **Be inclusive.** No gatekeeping — first-time contributors are
  as welcome as experienced ones.
- **Be honest.** If something doesn't work, say so. If you're
  unsure, ask.
- **Credit others.** When featuring community work, name the
  creator.

We don't tolerate harassment, discrimination, or bad-faith
engagement.

---

## Where to Get Help

| Channel | Use For |
|---|---|
| [Discord](https://discord.gg/6RMpzuKrRd) | Questions, feedback, real-time discussion |
| [GitHub Issues](https://github.com/strawpot/strawpot/issues) | Bug reports, feature requests |
| [docs.strawpot.com](https://docs.strawpot.com) | Guides, API reference, tutorials |
| [StrawHub](https://strawhub.dev) | Browse and publish packages |

---

## License

By contributing, you agree that your contributions will be
licensed under the [MIT License](LICENSE).
