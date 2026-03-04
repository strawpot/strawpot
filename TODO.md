# TODO

Items to address once prerequisites are ready or designs are finalized.

## ~~1. Add end-to-end tests~~

**Done.** E2E test suite added in `cli/tests/e2e/` — 12 tests covering session lifecycle, delegation flow, worktree isolation, and error handling. Uses stub agents (Python scripts) to replace only external boundaries; all internal components (denden gRPC, config, merge strategies) run real.

## ~~2. Design Web GUI in detail~~

**Done.** Covered in [DESIGN.md — Web GUI (Planned)](DESIGN.md#web-gui-planned) section: architecture, features (project management, session monitoring, session history, EM replay), data sources, and CLI integration.

## ~~3. Persistent user configuration for env, agent params, and default_agent~~

**Done.** See [configuration docs](docs/cli/configuration.mdx) for details.

## 4. Secret handling for persisted env values

Skill env values are stored as plain text in `strawpot.toml`. Consider OS keychain integration or external secret managers for sensitive values.

## 5. Config validation against frontmatter declarations

Validate saved env/config values against frontmatter-declared types and `required` flags at load time.
