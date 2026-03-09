# TODO

## Architecture

- [ ] **Parallel sub-agent delegation**
  Currently delegation is sequential — an agent calls `stub.Send()` which
  blocks until the sub-agent finishes. The architecture already supports
  parallelism in the gRPC server thread pool, `handle_delegate()`, agent
  workspaces, role staging, and tracing spans. Incremental changes needed:
  thread-safe locks for `Session._agents`/`_agent_info`/`_agent_spans`,
  `Tracer` JSONL writes, and `_write_session_file()`; client-side agent
  wrapper must support concurrent gRPC calls. Shared worktree conflicts
  can be managed via task decomposition discipline initially.

- [ ] **Hooks**
  Pre/post spawn, pre/post cleanup extension points. Allow users to run
  custom scripts at key session lifecycle events.

## Security

- [ ] **Sanitize summary field in session API responses**
  The `summary` field in `delegate_end` trace events comes from agent output
  unfiltered and is exposed via `GET /api/projects/{id}/sessions`. Could
  inadvertently contain API keys or credentials in error messages. Mitigations:
  truncate to a reasonable length, add regex-based redaction for common secret
  patterns. Low priority while GUI is local-only.

- [ ] **Encrypt session artifacts on disk**
  Artifacts in `.strawpot/sessions/*/artifacts/` store raw task text and agent
  stdout/stderr in plaintext. Consider optional at-rest encryption with key
  management via OS keychain. Low priority for single-user local machines.

## Housekeeping

- [ ] **Archive retention policy**
  Configurable max age or count for archived sessions per project. Auto-prune
  old session directories in `.strawpot/sessions/` to reclaim disk space.
  Low priority — users can manually delete session directories for now.
