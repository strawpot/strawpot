# Spike: Can StrawHub Roles Work in Vanilla Claude Code?

Date: 2026-03-23
Parent issue: #406 (Strategic Execution Plan)
Sub-issue: #409 (4/9)

## Objective

Determine whether StrawHub roles provide value in vanilla Claude Code
(without StrawPot runtime). This gates the Platform Track: if roles
only work inside StrawPot, platform expansion to Claude Code users is
not feasible.

## Method

1. Read each role's ROLE.md and its skill dependencies
2. Identify every StrawPot-specific dependency (denden, strawpot-memory,
   role delegation, StrawPot-only skills)
3. Classify what breaks, degrades, or works unchanged when the role
   content is pasted into a CLAUDE.md file
4. Estimate percentage of value retained

## Roles Tested

### 1. code-reviewer

**Source:** `roles/roles/code-reviewer/ROLE.md`

**Dependencies:**
- Skill: `code-review` (Markdown instructions + `gh` CLI)
- No role dependencies

**StrawPot-specific elements:**
- YAML frontmatter `metadata.strawpot` block (ignored by CLAUDE.md)
- `default_agent: strawpot-claude-code` (frontmatter only)

**What works in vanilla Claude Code:**
- Full review workflow (PR mode and local mode)
- Confidence scoring and filtering (pure instructions)
- All 5 parallel review agents from the code-review skill (Claude Code's
  native subagent/Agent tool handles this)
- `gh` CLI interactions (standard tool, not StrawPot-specific)
- CLAUDE.md compliance checking (self-referential: reads the project's
  own CLAUDE.md)
- Output format and `NO_FURTHER_IMPROVEMENTS` signal

**What breaks:**
- Nothing substantive. YAML frontmatter is packaging metadata with no
  effect on behavior.

**Value retained: ~95%**

The 5% loss is packaging convenience (version tracking, dependency
resolution, `strawhub` CLI). Review behavior is 100% functional.

### 2. implementation-planner

**Source:** `roles/roles/implementation-planner/ROLE.md`

**Dependencies:**
- Skills: `implementation-planning`, `github-issues`, `engineering-principles`
- Role: `implementation-executor` (delegation target in step 7)

**StrawPot-specific elements:**
- YAML frontmatter `metadata.strawpot` block
- Step 7: "delegate to `implementation-executor`" requires denden for
  cross-role delegation
- References to `implementation-executor` as downstream consumer

**What works in vanilla Claude Code:**
- Steps 1-6: full planning workflow (read issue, analyze codebase,
  decompose work, create sub-issues, post summary, label transitions)
- All 3 skill dependencies are pure Markdown; work identically as
  CLAUDE.md content
- `gh` CLI interactions for issue management
- Engineering principles for architecture decisions
- Sub-issue template and complexity estimation

**What breaks:**
- Step 7 (hand-off to implementation-executor): requires denden for
  cross-role delegation. Users must manually start a new session with
  the executor role instructions.

**What degrades:**
- References to `implementation-executor` become a dead name without
  the role registry. Users need to set up the executor role separately.

**Value retained: ~85%**

Core value (planning and decomposition) works fully. Only the automated
hand-off breaks; users can work around this by manually switching roles.

### 3. github-triager (additional test)

**Source:** `roles/roles/github-triager/ROLE.md`

**Dependencies:**
- Skills: `github-issues`, `github-prs`
- No role dependencies

**StrawPot-specific elements:**
- YAML frontmatter only
- Mentions `implementer` and `pr-reviewer` as downstream roles (but
  does not delegate to them)

**What works in vanilla Claude Code:**
- Complete triage workflow (read, validate, categorize, prioritize,
  assign/route, close)
- PR triage and bulk triage
- All `gh` CLI operations

**What breaks:**
- Nothing substantive.

**Value retained: ~95%**

### 4. pr-reviewer (negative test)

**Source:** `roles/roles/pr-reviewer/ROLE.md`

**Dependencies:**
- Skills: `review-pr`, `github-prs`
- Roles: `code-reviewer`, `code-simplifier`, `comment-analyzer`,
  `pr-test-analyzer`, `silent-failure-hunter`, `type-design-analyzer`

**StrawPot-specific elements:**
- Entire value proposition is orchestrating 6 sub-roles via delegation;
  routing, delegation, and aggregation all require multi-agent runtime

**What works in vanilla Claude Code:**
- The routing logic (deciding which aspects to review) is useful as a
  mental model
- The review-pr skill's output format works

**What breaks:**
- Delegation to 6 specialized roles: this IS the role's purpose
- Without delegation, it becomes a checklist of "things to review"
  rather than an orchestrator

**Value retained: ~10%**

An orchestrator, not an instruction set. Without multi-agent delegation,
users are better served by `code-reviewer` directly.

## Dependency Classification

### Works natively in Claude Code (no changes needed)

| Dependency | Type | Notes |
|-----------|------|-------|
| `gh` CLI | Tool | Standard GitHub CLI, not StrawPot-specific |
| `code-review` skill | Skill | Pure Markdown instructions |
| `implementation-planning` skill | Skill | Pure Markdown instructions |
| `engineering-principles` skill | Skill | Pure Markdown principles |
| `github-issues` skill | Skill | `gh` CLI knowledge |
| `github-prs` skill | Skill | `gh` CLI knowledge |
| Claude Code Agent tool | Feature | Native subagent support |

### Requires StrawPot runtime

| Dependency | Type | Impact |
|-----------|------|--------|
| `denden` | Orchestration | Cross-role delegation breaks |
| `strawpot-memory` | State | Cross-session context lost |
| Role registry | Package mgmt | No `strawhub install` equivalent |
| Pipeline labels | Workflow | Label state machine needs manual management |

## Role Categorization

StrawHub roles fall into two categories:

### Category A: Instruction-set roles (work standalone)

These roles are primarily behavioral instructions. Their value comes
from the knowledge and workflow encoded in the Markdown, not from
multi-agent orchestration.

- **code-reviewer** (~95% value retained)
- **github-triager** (~95% value retained)
- **implementation-planner** (~85% value retained)
- **implementation-executor** (~80% value retained, estimated)
- **code-simplifier** (~90% value retained, estimated)
- **docs-writer** (~90% value retained, estimated)
- **implementer** (~85% value retained, estimated)

### Category B: Orchestrator roles (need StrawPot)

These roles exist to coordinate other roles. Without delegation, they
lose their primary value.

- **pr-reviewer** (~10% value retained)
- **pipeline-orchestrator** (~5% value retained)
- **ai-ceo/strawpot-ceo** (~5% value retained)

## What Would Need to Change

To make Category A roles work seamlessly in vanilla Claude Code:

1. **Strip YAML frontmatter**: CLAUDE.md does not parse YAML
   frontmatter. The role content (everything below `---`) works as-is.

2. **Inline skill dependencies**: Append referenced skills to the
   CLAUDE.md or place them in a separate file. Simple concatenation:
   ```
   # CLAUDE.md
   [role content]
   [skill 1 content]
   [skill 2 content]
   ```

3. **Remove delegation references**: Lines like "delegate to
   implementation-executor" should be replaced with "the next step is
   for the user to..." or removed entirely.

4. **No changes needed for**: confidence scoring, output formats,
   `gh` CLI usage, review workflows, planning methodology.

## Effort Estimate

Creating a "vanilla Claude Code" export for Category A roles:
- Automated frontmatter stripping: trivial (size/S)
- Skill inlining/bundling: small script (size/S)
- Delegation reference cleanup: manual per role, but mechanical (size/S)
- Documentation and install instructions: size/M

Total: size/M for the tooling, then each role export is near-zero
marginal effort.

## Feasibility Verdict

**PARTIAL** -- proceed with the Platform Track, scoped to Category A roles.

### Evidence

1. Instruction-set roles (code-reviewer, implementation-planner,
   github-triager) retain 85-95% of their value. Core workflows,
   knowledge, and output formats work unchanged.

2. The main losses are packaging convenience (no `strawhub install`) and
   automated orchestration (no cross-role delegation). These are real
   but do not block standalone usage.

3. Orchestrator roles (pr-reviewer, pipeline-orchestrator) do NOT work
   standalone. These should be excluded from the Platform Track or
   marketed as "StrawPot-only" features.

### Recommendations

1. **Proceed with Platform Track for Category A roles.** Value
   proposition: curated, tested Claude Code instructions that improve
   specific workflows.

2. **Build a simple export/bundle tool** that strips frontmatter, inlines
   skill dependencies, and removes StrawPot-specific references. This
   produces a single Markdown file users can drop into their CLAUDE.md.

3. **Use Category B roles as StrawPot differentiators.** Multi-agent
   orchestration justifies the full runtime. Market as "upgrade to
   StrawPot for orchestrated workflows."

4. **Start with code-reviewer for launch.** It has the broadest appeal,
   zero StrawPot dependencies, and a clear value proposition ("better
   code reviews in Claude Code").
