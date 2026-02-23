# Loguetown — CLI Reference

The CLI is the **primary interface**. Every operation is available here; the GUI is optional.

```bash
# ── Project setup ─────────────────────────────────────────────────────────────
lt init                               # scaffold .loguetown/ in the current repo
lt init --force                       # re-scaffold (adds missing files only)

# ── Orchestration ─────────────────────────────────────────────────────────────
lt run "Add OAuth2 login with Google + GitHub"
lt run --dry-run "..."                # print planned task DAG without creating anything
lt run --auto-start "..."             # plan + immediately start execution
lt run --integration-branch "..."     # force-enable integration branch for this plan

lt plan show                          # print current plan as a text DAG tree
lt plan show --json                   # machine-readable JSON
lt plan start                         # begin executing a plan that is in draft status
lt plan stop                          # pause all active runners
lt plan cancel                        # cancel plan and clean up worktrees
lt plan land                          # land integration branch → base (runs checks first)

lt status                             # one-screen summary: agents, tasks, checks

# ── Role management ───────────────────────────────────────────────────────────
lt role list                          # list all roles in .loguetown/roles/
lt role show implementer              # print resolved role YAML with inherited defaults
lt role create documenter             # scaffold new role YAML + empty skill directory
lt role edit reviewer                 # open role YAML in $EDITOR
lt role delete security-auditor       # remove role file (warns if agents reference it)

# ── Agent management ──────────────────────────────────────────────────────────
lt agent list                         # name | role | status | current task
lt agent show charlie                 # full Charter + resolved role + memory summary
lt agent create --name diana --role reviewer
lt agent edit charlie                 # open Charter YAML in $EDITOR
lt agent spawn charlie --task <id>    # manually start a session for a specific task
lt agent kill charlie                 # terminate a running agent session

# ── Skills management ─────────────────────────────────────────────────────────
lt skills list                        # all *.md files under .loguetown/skills/
lt skills list --role implementer     # filtered by role directory
lt skills add implementer react-patterns.md    # scaffold a new blank skill file
lt skills edit implementer/typescript-patterns.md   # open in $EDITOR
lt skills show implementer/git-workflow.md     # print file content
lt skills query "OAuth callback handler" --role implementer
                                      # run vector search and show top-K results + scores
lt skills reindex                     # re-embed all skill files into sqlite-vec

# ── Memory management ─────────────────────────────────────────────────────────
lt memory list                        # all chunks across all agents and layers
lt memory list --agent charlie        # filter by agent
lt memory list --layer episodic       # filter by layer
lt memory list --status proposed      # filter by promotion status
lt memory show <id>                   # print full Markdown content + frontmatter
lt memory query "state parameter validation" --agent charlie
                                      # run vector search over charlie's memory
lt memory promote <id>                # human-override: promote to active
lt memory reject <id> --reason "..."  # human-override: reject with reason
lt memory deprecate <id>              # mark as stale/invalidated
lt memory split <file>                # interactively split a large .md into chunks
lt memory reindex                     # re-embed all memory chunks into sqlite-vec

# ── Task management ───────────────────────────────────────────────────────────
lt tasks list                         # all tasks in current plan with status
lt tasks list --status needs-human    # filter to tasks requiring human attention
lt tasks show <task-id>               # acceptance criteria, runs, artifacts, merge gate state
lt tasks approve <task-id>            # approve merge gate (runs all pre-merge checks first)
lt tasks reject <task-id> --comment "..."
lt tasks unblock <task-id>            # force-mark deps as satisfied (use with care)

# ── Escalations ────────────────────────────────────────────────────────────────
lt escalate list                      # all open escalations (severity, reason, task)
lt escalate list --all                # include acknowledged and resolved
lt escalate show <id>                 # full detail: reason, task, run, bump history
lt escalate ack <id>                  # acknowledge (stops auto-bump timer)
lt escalate resolve <id>              # close escalation

# ── Diff & review (human inspection) ─────────────────────────────────────────
lt diff <task-id>                     # print unified diff to stdout (pipe to less/delta)
lt diff <task-id> --stat              # files-changed summary only
lt review show <task-id>              # print reviewer findings (blockers + non-blockers)
lt review show <task-id> --blocking   # only blocking findings

# ── Chronicle (trace) ─────────────────────────────────────────────────────────
lt chronicle                          # stream all live events (tail -f style)
lt chronicle --tail 100               # last N events
lt chronicle --task <task-id>         # full event trace for one task
lt chronicle --run <run-id>           # trace for one agent run
lt chronicle --agent charlie          # all activity attributed to charlie
lt chronicle --type MEMORY_PROPOSED   # filter by event type
lt chronicle --since "2025-01-15"     # events after a date
lt chronicle --json                   # raw JSONL output (pipe-friendly)

# ── Chat (conversation with orchestrator or agents) ───────────────────────────
lt chat                               # chat with the orchestrator (Planner / daemon)
lt chat --agent charlie               # open a chat session with agent "charlie"
lt chat --agent charlie --history     # print full conversation transcript to stdout
lt chat --history --json              # machine-readable JSON transcript

# ── GUI ───────────────────────────────────────────────────────────────────────
lt gui                                # start GUI at http://localhost:4242
lt gui --port 8080
lt gui --open                         # start and open in default browser
```
