package runner

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

// ClaudeCodeProvider spawns the `claude` CLI subprocess (Claude Code) to
// execute the task non-interactively via `claude -p`.
type ClaudeCodeProvider struct {
	TimeoutMinutes int
}

func (p *ClaudeCodeProvider) Name() string { return "claude-code" }

func (p *ClaudeCodeProvider) Execute(ctx context.Context, req ExecuteRequest) (ExecuteResult, error) {
	timeout := time.Duration(p.TimeoutMinutes) * time.Minute
	if timeout <= 0 {
		timeout = 20 * time.Minute
	}

	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	// Combine system prompt and task into a single prompt for -p.
	var full strings.Builder
	if req.SystemPrompt != "" {
		full.WriteString(req.SystemPrompt)
		full.WriteString("\n\n---\n\n")
	}
	full.WriteString("## Your Task\n\n")
	full.WriteString(req.Task)

	args := []string{"-p", full.String(), "--output-format", "text"}

	cmd := exec.CommandContext(ctx, "claude", args...)
	cmd.Dir = req.WorkDir

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	if err != nil {
		return ExecuteResult{
			Output:  stdout.String(),
			Success: false,
			Error:   fmt.Sprintf("claude exited with error: %v\nstderr: %s", err, stderr.String()),
		}, nil // Return nil error — run failure is captured in result.
	}

	return ExecuteResult{
		Output:  strings.TrimSpace(stdout.String()),
		Success: true,
	}, nil
}
