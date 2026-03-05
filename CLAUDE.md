# Claude Code Instructions

## Git workflow

- **Never push directly to `main`.** Always create a new branch and open a PR.
- Use the branch naming convention `claude/<branch-name>`.
- Do not bypass branch protection rules or skip required checks.

## After completing any code change

1. Show me the full `git diff` for review
2. Wait for my explicit approval before proceeding
3. Once approved:
   - Rebase from `main` before committing (`git fetch origin && git rebase origin/main`)
   - **If the current branch has an open PR**, push to that branch to update the existing PR.
   - **If the current branch's PR is already merged** (or there is no PR), pull the latest `main` (`git checkout main && git pull origin main`), then create a fresh branch from `main` and open a new PR.
   - Never reuse a branch whose PR has been merged. Each merged PR keeps its own branch.
