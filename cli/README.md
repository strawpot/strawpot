# StrawPot CLI

Lightweight CLI for agent orchestration. StrawPot connects
[Denden](https://github.com/strawpot/denden) (gRPC agent-to-orchestrator transport)
and [StrawHub](https://strawhub.dev) (skill & role registry) to run multi-agent
sessions in isolated environments.

## Install

```
pip install strawpot
```

## Usage

```bash
# Start a session (foreground, interactive)
strawpot start
strawpot start --role team-lead --runtime strawpot-claude-code

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

Global: `$STRAWPOT_HOME/strawpot.toml` (default `~/.strawpot/strawpot.toml`)
Project: `strawpot.toml` (project root)

```toml
runtime = "strawpot-claude-code"       # strawpot-claude-code | codex | openhands
isolation = "worktree"        # worktree | docker

[denden]
addr = "127.0.0.1:9700"

[orchestrator]
role = "team-lead"

[policy]
max_depth = 3
```

## Links

- [Repository](https://github.com/strawpot/strawpot) — full project docs and architecture
- [StrawHub](https://strawhub.dev) — skill & role registry
- [Denden](https://github.com/strawpot/denden) — gRPC transport layer
