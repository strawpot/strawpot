// Package merge provides git merge operations for completed agent runs.
// After runner.Run() succeeds, the worktree and branch are already deleted;
// only the HeadSHA/BaseSHA remain in the run record. MergeRun cherry-picks
// those commits onto the default branch (git objects persist until GC).
package merge

import (
	"bytes"
	"fmt"
	"os/exec"
	"strings"
)

// MergeRun cherry-picks the commits from baseSHA..headSHA onto defaultBranch
// in the given project directory.
//
// Returns nil if there is nothing to merge (headSHA == "" or headSHA == baseSHA)
// or if headSHA is already an ancestor of the current HEAD (already merged).
// Returns a non-nil error on conflict; the in-progress cherry-pick is aborted
// automatically before returning.
func MergeRun(projectPath, defaultBranch, baseSHA, headSHA string) error {
	if headSHA == "" || headSHA == baseSHA {
		return nil // nothing to merge
	}

	// Switch to the default branch.
	if out, err := runGit(projectPath, "checkout", defaultBranch); err != nil {
		return fmt.Errorf("checkout %s: %w\n%s", defaultBranch, err, out)
	}

	// Refuse to operate on a dirty working tree.
	if !isCleanTree(projectPath) {
		return fmt.Errorf("working tree is dirty; commit or stash changes before merging")
	}

	// If headSHA is already an ancestor of HEAD the commits are already present.
	if alreadyMerged(projectPath, headSHA) {
		return nil
	}

	// Cherry-pick all commits in the range (baseSHA, headSHA].
	out, err := runGit(projectPath, "cherry-pick", baseSHA+".."+headSHA)
	if err != nil {
		// Abort the in-progress cherry-pick so the tree is clean for the next attempt.
		_, _ = runGit(projectPath, "cherry-pick", "--abort")
		return fmt.Errorf("cherry-pick %s..%s: %w\n%s", baseSHA, headSHA, err, out)
	}
	return nil
}

// runGit executes a git command in dir and returns combined stdout+stderr output.
func runGit(dir string, args ...string) (string, error) {
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	var buf bytes.Buffer
	cmd.Stdout = &buf
	cmd.Stderr = &buf
	err := cmd.Run()
	return strings.TrimSpace(buf.String()), err
}

// isCleanTree returns true when the working tree has no staged or unstaged changes.
func isCleanTree(dir string) bool {
	out, err := runGit(dir, "status", "--porcelain")
	return err == nil && out == ""
}

// alreadyMerged reports whether headSHA is already an ancestor of HEAD
// (i.e., the commits are already present in the branch).
func alreadyMerged(dir, headSHA string) bool {
	_, err := runGit(dir, "merge-base", "--is-ancestor", headSHA, "HEAD")
	return err == nil
}
