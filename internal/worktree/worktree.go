// Package worktree manages isolated git worktrees for agent runs.
package worktree

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// Create adds a git worktree at path, creating branch from baseSHA.
// If baseSHA is empty, the current HEAD is used as the base.
// Returns the absolute path of the created worktree.
func Create(repoPath, worktreePath, branch, baseSHA string) (string, error) {
	if err := os.MkdirAll(filepath.Dir(worktreePath), 0o755); err != nil {
		return "", fmt.Errorf("create worktree parent: %w", err)
	}

	args := []string{"worktree", "add", worktreePath, "-b", branch}
	if baseSHA != "" {
		args = append(args, baseSHA)
	}

	if out, err := git(repoPath, args...); err != nil {
		return "", fmt.Errorf("git worktree add: %w\n%s", err, out)
	}
	return worktreePath, nil
}

// Remove detaches and removes a worktree and deletes its branch.
func Remove(repoPath, worktreePath, branch string) error {
	if _, err := git(repoPath, "worktree", "remove", "--force", worktreePath); err != nil {
		// Non-fatal: worktree may already be gone.
		_ = err
	}
	if branch != "" {
		if _, err := git(repoPath, "branch", "-D", branch); err != nil {
			_ = err // Non-fatal: branch may already be deleted.
		}
	}
	return nil
}

// CurrentSHA returns the HEAD commit SHA in the given repo (or worktree).
func CurrentSHA(repoPath string) (string, error) {
	out, err := git(repoPath, "rev-parse", "HEAD")
	if err != nil {
		return "", fmt.Errorf("git rev-parse HEAD: %w", err)
	}
	return strings.TrimSpace(string(out)), nil
}

// HeadSHA returns the HEAD SHA of the worktree after the agent run.
func HeadSHA(worktreePath string) (string, error) {
	return CurrentSHA(worktreePath)
}

// git runs a git command in dir and returns combined output.
func git(dir string, args ...string) ([]byte, error) {
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	var buf bytes.Buffer
	cmd.Stdout = &buf
	cmd.Stderr = &buf
	err := cmd.Run()
	return buf.Bytes(), err
}
