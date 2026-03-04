# TODO

Items to address once prerequisites are ready or designs are finalized.

## 1. Add end-to-end tests

Set up an E2E test suite that exercises the full strawpot workflow — from CLI invocation through agent delegation and output. Needs design for:
- Test framework and runner selection
- Fixture / mock strategy for external dependencies
- CI integration

## 2. Design Web GUI in detail

Full design for the web-based management interface is pending. Topics to cover:
- Overall layout and navigation
- Strawhub browsing / installing
- Agent configuration and role management
- Session monitoring and logs

## ~~3. Persistent user configuration for env, agent params, and default_agent~~

**Done.** Skill env values are now persisted to `[skills.<slug>.env]` in `strawpot.toml` and role `default_agent` can be overridden via `[roles.<slug>]`. See [configuration docs](docs/cli/configuration.mdx) for details.

Remaining future work:
- **Secret handling** — env values are stored as plain text; consider OS keychain integration or external secret managers
- **Validation** — validate saved values against frontmatter-declared types and `required` flags at load time
