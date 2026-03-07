# TODO

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
