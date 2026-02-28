# StrawPot

Lightweight CLI for agent orchestration. StrawPot connects
[Denden](https://github.com/strawpot/denden) (gRPC agent-to-orchestrator transport)
and [StrawHub](https://strawhub.dev) (skill & role registry) to run multi-agent
sessions (e.g. coding, research, ops) in isolated environments.

```
strawpot start --role team-lead
```

1. Creates a git worktree for the session
2. Starts a Denden gRPC server
3. Spawns an orchestrator agent (Claude Code, Codex, or OpenHands)
4. Agents delegate sub-tasks via Denden — StrawPot resolves the role + skills
   from StrawHub and spawns sub-agents in the same worktree
5. On exit, cleans up everything automatically

## Repository Structure

```
cli/          Python CLI package (strawpot)
web/          Web GUI (planned)
DESIGN.md     Architecture & design document
```

## Install

```
pip install strawpot
```

Or from source:

```
cd cli
pip install -e ".[dev]"
```

## Usage

```bash
# Start a session (foreground, interactive)
strawpot start
strawpot start --role team-lead --runtime claude_code

# Install skills and roles from StrawHub
strawpot install skill git-workflow
strawpot install role implementer

# Search and list
strawpot search "code review"
strawpot list

# Show merged config
strawpot config
```

## Configuration

Global: `$STRAWPOT_HOME/config.toml` (default `~/.strawpot/config.toml`)
Project: `.strawpot/config.toml`

```toml
runtime = "claude_code"       # claude_code | codex | openhands
isolation = "worktree"        # worktree | docker

[denden]
addr = "127.0.0.1:9700"

[orchestrator]
role = "team-lead"

[policy]
allowed_roles = ["implementer", "reviewer", "fixer"]
max_depth = 3
```

See [DESIGN.md](DESIGN.md) for architecture details.
