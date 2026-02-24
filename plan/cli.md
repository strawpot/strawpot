# Strawpot — CLI Reference

The CLI is the **primary interface**. Every operation is available here; the GUI is optional.

## Project Context Resolution

Every `lt` command that operates on a project resolves the working directory automatically:

1. Walk up from `$CWD` until a `.strawpot/` directory is found (same as how `git` finds `.git/`)
2. If `$LT_WORKDIR` is set, use that path instead
3. If neither is found, the command fails with a clear error: `not in a strawpot project (no .strawpot/ found)`

This means you never need to pass `--project` or a project name — just `cd` into the repo as usual.

```bash
# Override workdir explicitly (useful in scripts / CI):
LT_WORKDIR=/path/to/repo lt skills list
```

---

```bash
# ── Project setup ─────────────────────────────────────────────────────────────
lt init                               # scaffold .strawpot/ in the current repo
lt init --force                       # re-scaffold (adds missing files only)

# ── Orchestration (chat-first) ────────────────────────────────────────────────
lt chat                               # open (or resume) an orchestrator session
lt chat --new                         # force-start a fresh conversation
lt chat --history                     # print full conversation transcript to stdout
lt chat --history --json              # machine-readable JSON transcript

# Direct CLI shortcuts (also available within lt chat):
lt run "Add OAuth2 login with Google + GitHub"   # plan + confirm + execute in one shot
lt run --dry-run "..."                # print proposed task DAG without creating anything
lt run --auto-start "..."             # plan + immediately start without confirmation prompt
lt run --integration-branch "..."     # force-enable integration branch for this plan

lt plan show                          # print current plan as a text DAG tree
lt plan show --json                   # machine-readable JSON
lt plan start                         # begin executing a plan that is in draft status
lt plan stop                          # pause all active runners
lt plan cancel                        # cancel plan and clean up worktrees
lt plan land                          # land integration branch → base (runs checks first)

lt status                             # one-screen summary: agents, tasks, checks

# ── Role management ───────────────────────────────────────────────────────────
lt role list                          # list all roles in .strawpot/roles/
lt role show implementer              # print resolved role YAML with inherited defaults
lt role create documenter             # scaffold new role YAML + empty skill directory
lt role edit reviewer                 # open role YAML in $EDITOR
lt role delete security-auditor       # remove role file (warns if agents reference it)

# ── Agent management ──────────────────────────────────────────────────────────
lt agent list                         # name | role | status | current task
lt agent show charlie                 # full Charter + resolved role + skill pools
lt agent create --name diana --role reviewer
lt agent edit charlie                 # open Charter YAML in $EDITOR
lt agent spawn charlie --task <id>    # manually start a session for a specific task
lt agent kill charlie                 # terminate a running agent session

# ── Skills management ─────────────────────────────────────────────────────────
lt skills list                        # global + project modules (project view, default)
lt skills list --global               # only ~/.strawpot/skills/ (global pool only)
lt skills list --agent charlie        # global + project + agent modules (full agent view)

lt skills install react-patterns      # scaffold new skill module in project pool (default)
lt skills install --global personal-style          # install into global pool
lt skills install --agent charlie react-patterns   # install into agent pool

lt skills remove react-patterns       # remove skill module from project pool (default)
lt skills remove --global personal-style           # remove from global pool
lt skills remove --agent charlie react-patterns    # remove from agent pool

lt skills edit react-patterns         # open skill module in $EDITOR (project pool default)
lt skills edit --global personal-style             # open global skill module in $EDITOR
lt skills edit --agent charlie react-patterns      # open agent skill module in $EDITOR
lt skills show react-patterns         # print all .md file content in the module

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
lt chronicle --type CHECKS_FINISHED   # filter by event type
lt chronicle --since "2025-01-15"     # events after a date
lt chronicle --json                   # raw JSONL output (pipe-friendly)

# ── Chat (primary orchestration interface) ────────────────────────────────────
lt chat                               # open (or resume) orchestrator session
lt chat --new                         # force-start a fresh orchestrator conversation
lt chat --agent charlie               # open a direct chat session with agent "charlie"
lt chat --agent charlie --history     # print full conversation transcript to stdout
lt chat --history --json              # machine-readable JSON transcript of orchestrator session

# ── GUI ───────────────────────────────────────────────────────────────────────
lt gui                                # start GUI at http://localhost:4242
lt gui --port 8080
lt gui --open                         # start and open in default browser
```
