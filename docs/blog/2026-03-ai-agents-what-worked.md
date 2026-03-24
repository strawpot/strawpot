# I Tried to Automate My Entire Company with 32 AI Agents. Here's What Actually Worked.

I'm a solo founder. Over the past month, I built 32 AI agents and
pointed them at every job in my company — engineering, marketing,
DevOps, code review, issue triage, even writing release notes. Then I
stepped back and watched what happened. Some of it worked shockingly
well. Some of it failed in ways I didn't expect. This is the honest
version.

## The Setup

[StrawPot](https://github.com/strawpot/strawpot) is the system I
built to run all of this. It's an open-source CLI for multi-agent
orchestration: you define **roles** (specialized agent configurations
with instructions, skills, and permissions), and a central
**orchestrator** delegates work to them over gRPC via
[Denden](https://github.com/strawpot/denden).

Each role is a self-contained unit. A `code-reviewer` role knows how
to review pull requests. A `github-triager` role knows how to label
and prioritize issues. A `pipeline-orchestrator` manages entire issue
lifecycles — from triage to implementation to PR review — by
delegating to other roles in sequence.

Here's what a month of running this looked like:

- **392 commits** across 28 days
- **56 releases** shipped to PyPI
- **32 roles** (AI agents) across 16 repositories
- **27k monthly PyPI downloads**
- Scheduled agents running autonomously every 2 hours

The system runs on Claude Code under the hood, but StrawPot is
agent-agnostic — it supports Codex, Gemini CLI, OpenHands, and
anything that implements the wrapper protocol.

## What Actually Worked

### Issue Triage and PR Review Pipeline

This was the first thing that paid off, and it's still the most
reliable part of the system. The `github-triager` reads every new
issue, categorizes it (bug, feature, enhancement, chore), assigns
priority labels (p0 through p3), and posts a triage summary comment
explaining its rationale. It handles edge cases well — it knows the
difference between a user-facing bug and an internal chore, and it
catches duplicate issues. It's not revolutionary, but it means I never
look at a wall of unlabeled issues anymore.

The `pipeline-orchestrator` takes it further. When an issue is labeled
`pipeline/ready`, it kicks off a full lifecycle: it delegates to
`implementation-planner` to break the issue into ordered sub-issues,
then to `implementation-executor` to implement them one by one, each
getting its own branch and PR. The PRs go through `pr-reviewer`, which
orchestrates `code-reviewer`, `silent-failure-hunter`,
`type-design-analyzer`, and `pr-test-analyzer` in parallel.

The result: I open an issue describing what I want, and within an
hour, I have a set of scoped PRs ready for my review. The code isn't
always perfect — I reject maybe 20% of PRs or ask for changes — but
the throughput increase is enormous. I went from shipping maybe one
feature a day to shipping three or four.

### The imu Bot

This is the one I'm most proud of. [imu](https://github.com/strawpot/strawpot)
is a chat integration that connects Telegram (or Slack, or Discord) to
the full StrawPot agent system.

<!-- TODO: Embed demo video from #410 when available -->
<!-- [Demo video: imu bot in action](VIDEO_URL_HERE) -->

I message imu on Telegram: "The version number in pyproject.toml
doesn't match the latest PyPI release. Fix it." imu creates a
StrawPot session, delegates to the right agent, opens a PR, runs
tests, and messages me back with the PR link. The whole exchange takes
about 3 minutes.

It sounds like a gimmick, but it changed how I work. Instead of
context-switching into my IDE, I fire off quick tasks from my phone
while walking the dog. The latency is low enough that by the time I'm
back at my desk, the PR is waiting.

### Memory System

Agents are stateless by default — each session starts from scratch.
The memory system fixes this. After every session, StrawPot persists
key context: what was decided, what conventions were established, what
failed last time. The next session loads this context automatically.

This matters more than I expected. Without memory, agents repeat the
same mistakes. They re-discover that the docs site is at
docs.strawpot.com (not docs.strawpot.dev). They forget which repos
exist and where they live. With memory, they just know.

The implementation is simple — a pluggable memory provider that stores
key-value observations. Nothing fancy. But the compounding effect of
agents that remember is significant.

### Scheduled Agents

StrawPot has a scheduler (via `strawpot schedule` or the web GUI) that
runs agents on a cron schedule. I have agents that:

- Triage new issues every 2 hours
- Check for stale PRs daily
- Run a session recap agent after every session

These are the "set and forget" wins. None of them are individually
impressive, but together they mean the project never falls behind on
housekeeping. Before the scheduler, I'd come back from a weekend to
find 15 untriaged issues and a pile of stale PRs. Now the backlog is
always clean when I sit down on Monday.

## What Spectacularly Failed

### Marketing Automation: Zero Tweets Produced

I built a `strawpot-twitter-marketer` role. It was supposed to analyze
the product, draft tweets, evaluate them for quality, and post
automatically. I spent real engineering time on this — the role had an
evaluator, a content strategy, tone guidelines, the works.

Total tweets produced in a month: **zero**.

Here's what happened. First, Twitter's free API tier was eliminated in
February 2026. The agent kept hitting a `402 CreditsDepleted` error.
Fine — I pivoted to a "draft-to-Telegram" mode where it would draft
tweets and send them to me for manual posting. But even the drafts
were mediocre. The agent could write grammatically correct, technically
accurate tweets. They were also completely generic and uninteresting.
Nobody would click on "StrawPot v0.1.52 is out! New features include
improved session isolation and memory persistence." Riveting stuff.

The deeper problem: **you can't automate your way to an audience you
don't have.** Marketing automation assumes you have a distribution
channel. I had zero followers, zero community, zero organic reach. No
amount of AI-generated content was going to fix that. The bottleneck
wasn't content production — it was that nobody was listening.

This was the most expensive lesson of the month, measured in
engineering hours wasted.

### The Insight

The failure forced a strategic rethink. Instead of automating
distribution, I needed to do the one thing that can't be automated:
build trust through authentic engagement. Write honest content (like
this post). Show up in communities. Respond to real people.

AI agents are force multipliers. But a multiplier applied to zero is
still zero.

## The Honest Assessment

Let me be direct about what's real and what's not:

**Real:**
- The orchestration pipeline works. Agents triage, plan, implement,
  review, and ship code with minimal human intervention.
- Session isolation is solid. Agents work in git worktrees, changes
  merge back cleanly.
- The memory system genuinely improves agent performance over time.
- imu is a real productivity tool I use daily.

**Not yet real:**
- I'm the only user. The first-run experience hasn't been validated on
  a non-founder machine yet. There are probably sharp edges I can't
  see because my environment is perfectly configured.
- The 27k PyPI downloads number is real but doesn't mean 27k users.
  Most are CI bots and mirrors. Actual human users: probably single
  digits.
- Some of the 32 roles are barely used. The core 8-10 roles do 90% of
  the useful work. The rest are experiments.

I'm not pretending this is a polished product with thousands of happy
users. It's a working system that one person uses every day, and the
bones are solid enough to share. The gap between "works on my machine"
and "works for anyone" is exactly what I'm closing right now.

## The Tech

For the HN audience who wants to know how it works:

**StrawPot** is the orchestrator CLI. It manages sessions, spawns
agents, and coordinates delegation.

```bash
pip install strawpot
strawpot start --role team-lead
```

On first run, an onboarding wizard walks you through agent selection
(Claude Code, Codex, Gemini CLI, OpenHands) and configuration.

**Architecture:**
- **Denden** — gRPC transport between agents and the orchestrator.
  Each agent connects as a client; the orchestrator routes delegation
  requests to the right role.
- **StrawHub** — Public registry at [strawhub.dev](https://strawhub.dev)
  for skills, roles, and integrations. Think npm for agent
  configurations.
- **Roles** — YAML + Markdown definitions that specify an agent's
  system prompt, skills, permissions, and delegation rules.
- **Skills** — Reusable knowledge modules (like "how to use git" or
  "how to work with GitHub PRs") that get injected into agent context.
- **Memory** — Pluggable providers that persist observations across
  sessions.

Everything is open source:
[github.com/strawpot](https://github.com/strawpot).

## What I'd Do Differently

1. **Skip marketing automation entirely.** Build the product, write
   one honest post, share it. Let the work speak.
2. **Test the first-run experience earlier.** I was 300 commits deep
   before realizing nobody else had ever run `strawpot start` on a
   clean machine.
3. **Fewer roles, deeper.** I didn't need 32 agents. I needed 8 good
   ones. The rest were yak-shaving.

## Try It

If multi-agent orchestration sounds interesting:

```bash
pip install strawpot
strawpot start
```

GitHub: [github.com/strawpot/strawpot](https://github.com/strawpot/strawpot)
Docs: [docs.strawpot.com](https://docs.strawpot.com)
Registry: [strawhub.dev](https://strawhub.dev)

I'm genuinely curious whether this is useful to anyone else, or if
I've built the world's most elaborate yak-shaving machine. Either way,
the agents will keep triaging my issues while I wait to find out.

---

*Show HN title: Show HN: I automated my company with 32 AI agents -- here's what actually worked*
