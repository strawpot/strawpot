// Package checks executes project-defined check commands (lint, test, typecheck, etc.),
// saves their output as artifacts, and emits Chronicle events.
package checks

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/google/uuid"
	"github.com/steveyegge/loguetown/internal/chronicle"
	"github.com/steveyegge/loguetown/internal/config"
	"github.com/steveyegge/loguetown/internal/storage"
)

const defaultTimeoutSeconds = 60

// Result is the outcome of a single check step execution.
type Result struct {
	Name         string
	Passed       bool   // true if exit code 0
	Blocking     bool   // true if failed AND OnFail=block (or default)
	Skipped      bool
	ExitCode     int
	Stdout       string
	Stderr       string
	Duration     time.Duration
	ArtifactPath string // path to the saved output file on disk
	Retries      int    // extra attempts needed (for retry_on_flake)
}

// Run executes a single check step in workDir.
// Saves combined stdout+stderr to artifactDir/<name>.txt and records the
// artifact path in the artifacts table. Emits COMMAND_STARTED /
// COMMAND_FINISHED chronicle events.
func Run(projectID, runID string, step config.CheckStep, workDir, artifactDir string) Result {
	res := Result{Name: step.Name}

	timeout := time.Duration(defaultTimeoutSeconds) * time.Second
	if step.TimeoutSeconds > 0 {
		timeout = time.Duration(step.TimeoutSeconds) * time.Second
	}
	onFail := step.OnFail
	if onFail == "" {
		onFail = "block"
	}

	chronicle.Emit(projectID, "system", "COMMAND_STARTED", map[string]interface{}{
		"run_id":     runID,
		"check_name": step.Name,
		"command":    step.Run,
		"work_dir":   workDir,
	})

	start := time.Now()
	exitCode, stdout, stderr := runWithRetry(step.Run, workDir, timeout, step.RetryOnFlake, &res.Retries)
	res.Duration = time.Since(start)
	res.ExitCode = exitCode
	res.Stdout = stdout
	res.Stderr = stderr
	res.Passed = exitCode == 0
	res.Blocking = !res.Passed && onFail == "block"

	// Save stdout+stderr to disk.
	res.ArtifactPath = saveOutputArtifact(artifactDir, step.Name, stdout, stderr)

	// Record in the artifacts DB table.
	if res.ArtifactPath != "" {
		_ = insertArtifact(runID, "check_output", res.ArtifactPath, map[string]interface{}{
			"check":     step.Name,
			"exit_code": exitCode,
			"passed":    res.Passed,
		})
	}

	chronicle.Emit(projectID, "system", "COMMAND_FINISHED", map[string]interface{}{
		"run_id":        runID,
		"check_name":    step.Name,
		"exit_code":     exitCode,
		"duration_ms":   res.Duration.Milliseconds(),
		"passed":        res.Passed,
		"retries":       res.Retries,
		"artifact_path": res.ArtifactPath,
	})

	return res
}

// runWithRetry runs command, retrying up to maxRetries extra times on failure.
func runWithRetry(command, workDir string, timeout time.Duration, maxRetries int, retriesOut *int) (exitCode int, stdout, stderr string) {
	for attempt := 0; attempt <= maxRetries; attempt++ {
		if attempt > 0 {
			*retriesOut++
		}
		code, out, err := runOnce(command, workDir, timeout)
		if code == 0 || attempt == maxRetries {
			return code, out, err
		}
		// Non-zero exit and retries remain — try again.
	}
	return 1, "", ""
}

// runOnce runs command via /bin/sh -c in workDir with a timeout.
func runOnce(command, workDir string, timeout time.Duration) (exitCode int, stdout, stderr string) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	var outBuf, errBuf bytes.Buffer
	cmd := exec.CommandContext(ctx, "/bin/sh", "-c", command)
	cmd.Dir = workDir
	cmd.Stdout = &outBuf
	cmd.Stderr = &errBuf

	err := cmd.Run()
	code := 0
	if err != nil {
		if exit, ok := err.(*exec.ExitError); ok {
			code = exit.ExitCode()
		} else if ctx.Err() == context.DeadlineExceeded {
			code = -1 // timeout
		} else {
			code = 1
		}
	}
	return code, outBuf.String(), errBuf.String()
}

// saveOutputArtifact writes combined stdout+stderr to artifactDir/<name>.txt.
// Returns the path, or "" on error.
func saveOutputArtifact(artifactDir, name, stdout, stderr string) string {
	if err := os.MkdirAll(artifactDir, 0o755); err != nil {
		return ""
	}
	path := filepath.Join(artifactDir, name+".txt")
	content := fmt.Sprintf("=== STDOUT ===\n%s\n=== STDERR ===\n%s", stdout, stderr)
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		return ""
	}
	return path
}

// insertArtifact records an artifact path in the artifacts SQLite table.
func insertArtifact(runID, kind, path string, meta map[string]interface{}) error {
	db, err := storage.Get()
	if err != nil {
		return err
	}
	metaJSON, _ := json.Marshal(meta)
	_, err = db.Exec(
		`INSERT INTO artifacts (id, run_id, kind, path, meta_json, created_at)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		uuid.New().String(), runID, kind, path, string(metaJSON),
		time.Now().UTC().Format(time.RFC3339),
	)
	return err
}
