# Content Launch Playbook

Step-by-step guide for distributing the blog post across channels.
This is a manual/operational task for the founder.

## Prerequisites

Before starting:

- [ ] Blog post (#412) is written and published
- [ ] Blog section on strawpot.com (#67) is live
- [ ] Canonical URL is known: `https://docs.strawpot.com/blog/...`
- [ ] Pre-launch baselines captured in `docs/content-launch-results.md`
- [ ] Reddit account has enough karma (check by trying to post in a test sub)
- [ ] Demo video from #410 is ready (for Twitter thread)

## Posting Order and Timing

Post channels in this order with gaps between them:

1. **Hacker News** -- weekday, 9-11am ET
2. **Reddit** -- 2-4 hours after HN post
3. **Twitter** -- after Reddit, or skip if < 500 followers

Do NOT post everything simultaneously. HN first, let it breathe.

---

## 1. Hacker News (Show HN)

### Title

```
Show HN: I tried to automate my entire company with 32 AI agents
```

### URL

Use the canonical blog URL (not GitHub directly).

### First Comment (post immediately after submitting)

Adapt the following template based on the final blog post:

```
Hey HN, founder here. I built StrawPot -- an open-source orchestrator
that coordinates multiple AI coding agents (Claude Code, Codex, etc.)
through a single system. 32 roles, from code reviewer to release
manager, all working together.

The key insight from running this for months: you can't automate your
way to an audience you don't have. The agents are great at execution
but they can't replace the human judgment needed to decide *what* to
build next.

Technical details:
- Orchestrator uses gRPC to coordinate agents
- Each role has a ROLE.md spec that defines its behavior
- Roles can delegate to other roles (bounded depth)
- Works with Claude Code, OpenHands, Codex CLI

GitHub: https://github.com/strawpot/strawpot
Happy to answer any questions about the architecture or lessons learned.
```

### Tips

- Respond to every genuine comment in the first 2-3 hours
- Be authentic -- HN rewards transparency about failures
- Don't be defensive about criticism
- If asked "why not just use X?", give an honest technical comparison

---

## 2. Reddit

Stagger posts across subreddits. Adapt tone for each community.

### r/programming

**Title**: "Building a 32-agent AI orchestrator: what worked, what didn't, and why the hardest part wasn't the code"

**Tone**: Technical, focus on architecture decisions.

**Body template**:
```
I've been building an open-source system that orchestrates multiple AI
coding agents through a single control plane. After months of running
32 specialized roles (code reviewer, release manager, PR reviewer,
etc.), I wrote up the technical lessons learned.

The architecture uses gRPC for inter-agent coordination, with each
role defined by a spec file that constrains its behavior. Roles can
delegate to other roles with bounded recursion depth.

Blog post: [canonical URL]

Some of the more interesting technical challenges:
- Preventing infinite delegation loops between agents
- Making role specs precise enough to be useful but flexible enough
  to handle edge cases
- Coordinating work across multiple Git repos simultaneously

Source: https://github.com/strawpot/strawpot

Would love feedback from anyone who's worked on multi-agent systems.
```

### r/artificial

**Title**: "Lessons from running 32 AI agents as a solo founder -- what automation can and can't replace"

**Tone**: AI/ML-focused, emphasize multi-agent coordination insights.

**Body template**:
```
I've been running a multi-agent AI system for my solo startup --
32 specialized roles coordinated by an orchestrator. Each agent has a
defined specialty (code review, implementation, release management,
marketing drafts, etc.).

The biggest lesson: multi-agent coordination is a fundamentally
different problem than single-agent capability. An agent that's great
in isolation can cause cascading failures when it's part of a larger
system.

Blog post: [canonical URL]

Some things that surprised me:
- Agent-to-agent delegation needs strict depth limits or you get
  infinite loops
- The orchestrator's job is mostly *preventing* agents from doing
  things, not enabling them
- Role specialization matters more than model capability

Happy to discuss the architecture or share specific failure modes.
```

### r/SideProject

**Title**: "I built an AI orchestrator that runs 32 agents for my solo startup -- here's what I learned"

**Tone**: Indie/founder perspective, personal story.

**Body template**:
```
Solo founder here. I built StrawPot, an open-source tool that lets
you orchestrate multiple AI coding agents through one system. I've
been using it to run my own company with 32 AI "roles" -- everything
from code review to marketing drafts.

The honest truth: the agents are incredible at execution, but they
can't replace the human judgment about what to build. I wrote up the
full story.

Blog post: [canonical URL]

If you're a solo founder thinking about AI automation, the short
version: start with code review and implementation, those have the
highest ROI. Marketing and strategy still need a human in the loop.

GitHub: https://github.com/strawpot/strawpot
```

### Reddit Tips

- Reddit detects and penalizes self-promotion. Lead with value.
- Answer every comment substantively
- Don't crosslink between your Reddit posts
- If a post gets removed by automod, message the mods politely

---

## 3. Twitter / X (Personal Account)

Skip if personal account has < 500 followers.

### Thread (5-7 tweets)

```
1/ I tried to automate my entire company with 32 AI agents.
   Here's what happened (and what I learned the hard way).

2/ I built an orchestrator that coordinates AI coding agents --
   code reviewers, implementers, release managers, marketers.
   Each agent has a defined role with strict boundaries.

3/ What works surprisingly well:
   - Automated code review catches real bugs
   - Implementation agents handle routine PRs
   - Release management is almost fully automated

4/ What doesn't work (yet):
   - Strategy and prioritization still need a human
   - Marketing agents can draft, but you need judgment on *what* to say
   - Agent-to-agent delegation can spiral without strict limits

5/ The biggest lesson: you can't automate your way to an audience
   you don't have. All the AI execution in the world doesn't matter
   if nobody knows your product exists.

6/ The whole system is open source.
   Blog post: [canonical URL]
   GitHub: github.com/strawpot/strawpot

7/ [Attach demo video from #410]
   Here's what it looks like in practice.
```

### Twitter Tips

- Post the thread all at once (use a thread tool or compose in advance)
- Pin the thread to your profile
- Engage with replies for the first hour

---

## After Posting

1. Fill in URLs and timestamps in `docs/content-launch-results.md`
2. Check metrics at +1h, +4h, +12h, +24h, +48h
3. Respond to all comments on HN and Reddit
4. Fill in "Notable Responses" and "Lessons Learned" after 48h
