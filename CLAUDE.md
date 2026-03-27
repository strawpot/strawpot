# Claude Code Instructions

## Git workflow

- **Never push directly to `main`.** Always create a new branch and open a PR.
- Use the branch naming convention `claude/<branch-name>`.
- Do not bypass branch protection rules or skip required checks.

## After completing any code change

1. Rebase from `main` before committing (`git fetch origin && git rebase origin/main`)
2. **If the current branch has an open PR**, push to that branch to update the existing PR.
3. **If the current branch's PR is already merged** (or there is no PR), pull the latest `main` (`git checkout main && git pull origin main`), then create a fresh branch from `main` and open a new PR.
4. Never reuse a branch whose PR has been merged. Each merged PR keeps its own branch.
