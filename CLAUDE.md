# Claude Code Instructions

## Git workflow

- **Never push directly to `main`.** Always create a new branch and open a PR.
- Use the branch naming convention `claude/<branch-name>`.
- Do not bypass branch protection rules or skip required checks.

## After completing any code change

1. Show me the full `git diff` for review
2. Wait for my explicit approval before proceeding
3. Once approved, create a new branch, commit, push, and open a PR with a descriptive title and summary
