# Release Process: Branch-Cut Strategy

**Issue:** #396
**Status:** Design
**Date:** 2026-03-31
**Author:** Imu (implementer)

---

## 1. Problem Statement

Every merge to `main` triggers release workflows (`release.yml` for CLI, `release-gui.yml` for GUI), publishing to PyPI and creating GitHub Releases automatically. This was appropriate during rapid development but now causes:

- **No stable versions** — every commit is a release, including WIP features
- **No release gating** — no opportunity to batch changes, run extended QA, or hold a release
- **Version noise** — patch versions increment on every merge (CLI at v0.1.112, GUI at v0.1.157)
- **No hotfix path** — no mechanism to patch a released version without including all of `main`

## 2. Current State

### Workflow Triggers
| Workflow | Trigger | Tag Pattern | Current Version |
|----------|---------|-------------|-----------------|
| `release.yml` | Push to `main` (paths: `cli/**`) | `v*` | v0.1.112 |
| `release-gui.yml` | Push to `main` (paths: `gui/**`, `!gui/tests/**`) | `gui-v*` | gui-v0.1.157 |

### Version Management
- **setuptools_scm** reads version from git tags at build time
- Patch version auto-incremented: latest tag → +1 patch
- CLI tag regex: `^v(?P<version>[\d.]+)$`
- GUI tag regex: `^gui-v(?P<version>[\d.]+)$`

### Artifacts
- **PyPI packages:** `strawpot` (CLI), `strawpot-gui` (GUI)
- **GitHub Release binaries:** `strawpot-linux-amd64`, `strawpot-linux-arm64`, `strawpot-darwin-arm64`

## 3. Proposed Design

### 3.1 Branch Model

```
main (development) ──────────────────────────────────────────►
     │                          │
     ├── release/v0.2 ──►       ├── release/v0.3 ──►
     │   v0.2.0  v0.2.1        │   v0.3.0
     │   (tag)   (hotfix)      │   (tag)
```

- **`main`**: Development branch. CI runs. No releases triggered.
- **`release/vX.Y`**: Branch cut from `main` when ready to release. Release workflows trigger here.
- **Tags**: Created on release branches. Format unchanged: `vX.Y.Z` (CLI), `gui-vX.Y.Z` (GUI).

### 3.2 Version Scheme

Adopt **calendar-aware minor versions** starting from current state:

| Component | Next Release | Pattern |
|-----------|-------------|---------|
| CLI | v0.2.0 | `v0.2.Z` on `release/v0.2` |
| GUI | gui-v0.2.0 | `gui-v0.2.Z` on `release/v0.2` |

**Rationale:** Both CLI and GUI live in the same monorepo. Use a shared release branch (`release/vX.Y`) with independent tags per component. This avoids version drift confusion while allowing independent patch releases.

**Version bump rules:**
- **Minor bump** (`X.Y+1.0`): New release branch cut from `main`
- **Patch bump** (`X.Y.Z+1`): Hotfix on an existing release branch

### 3.3 Workflow Changes

#### A. Remove `main` → release trigger

Both `release.yml` and `release-gui.yml` will no longer trigger on push to `main`.

**Before:**
```yaml
on:
  push:
    branches: [main]
    paths: ["cli/**"]
```

**After:**
```yaml
on:
  push:
    branches: ["release/v*"]
    paths: ["cli/**"]
  workflow_dispatch:
```

Same change for `release-gui.yml` with its `gui/**` path filter.

#### B. Add release branch creation workflow

New workflow: `.github/workflows/create-release-branch.yml`

```yaml
name: Create Release Branch

on:
  workflow_dispatch:
    inputs:
      version:
        description: "Release version (e.g., 0.2)"
        required: true
        type: string

jobs:
  create-branch:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0

      - name: Validate version format
        run: |
          if ! echo "${{ inputs.version }}" | grep -qE '^[0-9]+\.[0-9]+$'; then
            echo "::error::Version must be in X.Y format (e.g., 0.2)"
            exit 1
          fi

      - name: Create release branch
        run: |
          BRANCH="release/v${{ inputs.version }}"
          if git ls-remote --heads origin "$BRANCH" | grep -q "$BRANCH"; then
            echo "::error::Branch $BRANCH already exists"
            exit 1
          fi
          git checkout -b "$BRANCH"
          git push origin "$BRANCH"
          echo "Created branch: $BRANCH"
```

#### C. Keep `workflow_dispatch` on all release workflows

Manual dispatch remains available for emergency releases from any branch.

#### D. CI unchanged

`ci.yml` continues to run on push to `main` and PRs. No changes needed.

### 3.4 Release Lifecycle

#### Creating a Release

1. **Decide to release**: When `main` is stable and ready.
2. **Create release branch**: Run `Create Release Branch` workflow with version (e.g., `0.2`).
   - This creates `release/v0.2` from `main`.
3. **Auto-release triggers**: Push to `release/v0.2` triggers `release.yml` and `release-gui.yml`.
   - First push (branch creation) publishes `v0.2.0` / `gui-v0.2.0`.
4. **Verify**: Confirm PyPI packages and GitHub Release are correct.

#### Hotfixing a Release

1. **Cherry-pick** the fix from `main` to `release/vX.Y`:
   ```bash
   git checkout release/v0.2
   git cherry-pick <commit-sha>
   git push origin release/v0.2
   ```
2. **Auto-release triggers**: Push increments patch → `v0.2.1` / `gui-v0.2.1`.

#### Release Branch Lifecycle

- Release branches are **long-lived** for as long as the version is supported.
- Old release branches are not deleted but stop receiving patches.
- Only the latest 1-2 release branches receive hotfixes (no formal LTS).

### 3.5 Version Detection Changes

Current version detection logic in workflows already handles this correctly:

```bash
LATEST=$(git tag --list 'v*' --sort=-v:refname | head -n1)
```

This finds the latest tag across all branches. On a new release branch, it will find the previous release's tag and increment. However, we need a small adjustment to scope tags to the release branch:

**Scoped version detection for release branches:**
```bash
# Extract X.Y from branch name (e.g., release/v0.2 → 0.2)
BRANCH_VERSION=$(echo "${GITHUB_REF#refs/heads/release/v}" )
LATEST=$(git tag --list "v${BRANCH_VERSION}.*" --sort=-v:refname | head -n1)
if [ -z "$LATEST" ]; then
  echo "version=${BRANCH_VERSION}.0" >> "$GITHUB_OUTPUT"
  echo "tag=v${BRANCH_VERSION}.0" >> "$GITHUB_OUTPUT"
else
  PATCH=$(echo "$LATEST" | sed "s/v${BRANCH_VERSION}\.//" )
  NEW_PATCH=$((PATCH + 1))
  echo "version=${BRANCH_VERSION}.${NEW_PATCH}" >> "$GITHUB_OUTPUT"
  echo "tag=v${BRANCH_VERSION}.${NEW_PATCH}" >> "$GITHUB_OUTPUT"
fi
```

Same pattern for GUI with `gui-v` prefix.

### 3.6 setuptools_scm Compatibility

No changes needed to `pyproject.toml`. The `SETUPTOOLS_SCM_PRETEND_VERSION` env var overrides the version at build time, which the workflows already use.

## 4. Migration Plan

### Phase 1: Workflow Changes (No Breaking Changes)
1. Update `release.yml`: Change trigger from `main` to `release/v*`
2. Update `release-gui.yml`: Same trigger change
3. Update version detection logic in both workflows (scoped to branch)
4. Add `create-release-branch.yml` workflow
5. **Test**: Run `workflow_dispatch` manually to verify nothing breaks

### Phase 2: First Branch-Cut Release
1. Create `release/v0.2` from `main`
2. Verify CLI v0.2.0 and GUI gui-v0.2.0 publish correctly
3. Verify GitHub Release and binaries are created
4. Verify `pip install strawpot==0.2.0` works

### Phase 3: Documentation & Cleanup
1. Update CLAUDE.md with release instructions
2. Update CONTRIBUTING.md with release section
3. Add release checklist template (`.github/ISSUE_TEMPLATE/release.md`)

## 5. Files to Change

| File | Change |
|------|--------|
| `.github/workflows/release.yml` | Trigger: `main` → `release/v*`. Update version detection. |
| `.github/workflows/release-gui.yml` | Trigger: `main` → `release/v*`. Update version detection. |
| `.github/workflows/create-release-branch.yml` | **New file.** Manual workflow to create release branches. |
| `CLAUDE.md` | Add release workflow instructions. |
| `CONTRIBUTING.md` | Add release section for contributors. |

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Forgetting to create release branch | No releases ship | Add reminder in PR template; scheduled pipeline check |
| Cherry-pick conflicts on release branch | Hotfix blocked | Keep release branches short-lived; cherry-pick early |
| `workflow_dispatch` used to release from `main` accidentally | Unintended release | Add branch validation step in release workflows |
| Stale release branches | Confusion about supported versions | Document "latest 2 branches supported" policy |

## 7. Out of Scope

- **CHANGELOG automation**: Can be added later (e.g., `git-cliff` or `conventional-changelog`)
- **Release candidate (RC) tags**: Not needed at current scale. Can add `vX.Y.Z-rc.N` pattern later.
- **Separate GUI release branch**: Both CLI and GUI share `release/vX.Y`. Split if versioning diverges significantly.
- **Branch protection rules for release branches**: Can add later if needed.
