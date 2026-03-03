# TODO

Items to address once prerequisites are ready or designs are finalized.

## 1. Remove `builtin_agent` once `strawpot_claude_code` repo is ready in strawhub

The built-in agent is a temporary shim. Once the `strawpot_claude_code` strawhub repo is published, remove the inline definition and rely on the external package instead.

## 2. Auto-install default dependencies (`denden`, `strawpot_claude_code`) on first run

When strawpot starts for the first time and these dependencies are not installed globally, it should automatically install them. Needs design for:
- Detection of missing dependencies
- Install mechanism and user confirmation flow
- Error handling / retry

## 3. Add end-to-end tests

Set up an E2E test suite that exercises the full strawpot workflow — from CLI invocation through agent delegation and output. Needs design for:
- Test framework and runner selection
- Fixture / mock strategy for external dependencies
- CI integration

## 4. Design Web GUI in detail

Full design for the web-based management interface is pending. Topics to cover:
- Overall layout and navigation
- Strawhub browsing / installing
- Agent configuration and role management
- Session monitoring and logs

## 5. Support `"*"` wildcard in role dependencies

Add support for `"*"` as a special value in role `dependencies`, meaning "depend on all roles available globally and locally." This wildcard should be ignored by install commands (both `strawhub` CLI and `strawpot` CLI proxy) since it doesn't refer to a specific installable package.

## 6. Persistent user configuration for env, agent params, and default_agent

Currently, SKILL.md `env` values are prompted every session and never saved, AGENT.md `params` are persisted only via `[agents.<name>]` in `strawpot.toml`, and ROLE.md `default_agent` has no user-override mechanism beyond the global `runtime` setting.

Design a unified persistent configuration layer so users can set and reuse these values across sessions, and the Web GUI can read/write them.

### Recommended approach: extend `strawpot.toml`

Reuse the existing `strawpot.toml` (global `~/.strawpot/strawpot.toml` and project-level `strawpot.toml` at project root) with new sections:

```toml
# Persist env values for skills (avoids re-prompting each session)
[skills.github_pr.env]
GITHUB_TOKEN = "ghp_..."

# Override a role's default_agent
[roles.implementer]
default_agent = "claude_code"

# Agent params already supported — no changes needed
[agents.claude_code]
model = "claude-sonnet-4-6"
```

### Design considerations
- **Global vs local layering** — project-local overrides global, matching the existing `strawpot.toml` merge behavior
- **Env resolution order** — saved value → environment variable → interactive prompt (only prompt if still missing)
- **Secret handling** — env values may contain secrets; consider whether to store them in plain text, use OS keychain integration, or reference external secret managers
- **Web GUI integration** — the GUI should be able to list configurable fields (from frontmatter schemas) and read/write the corresponding `strawpot.toml` sections
- **Validation** — validate saved values against frontmatter-declared types and `required` flags at load time
