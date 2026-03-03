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
