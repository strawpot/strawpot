// Package runner executes agent tasks via pluggable model providers.
package runner

import "context"

// Provider executes an agent task in a working directory.
type Provider interface {
	// Execute runs the agent with the given system prompt and task.
	// workDir is the absolute path the agent should treat as its root.
	// Returns the final text output produced by the agent.
	Execute(ctx context.Context, req ExecuteRequest) (ExecuteResult, error)

	// Name returns a human-readable name for the provider.
	Name() string
}

// ExecuteRequest is the input to Provider.Execute.
type ExecuteRequest struct {
	SystemPrompt   string
	Task           string
	WorkDir        string
	MaxTurns       int    // used by anthropic-api; ignored by claude-code
	BashAllowlist  []string
	APIKey         string // for providers that need it
	Model          string // for providers that need it
}

// ExecuteResult is the output from Provider.Execute.
type ExecuteResult struct {
	Output  string // final text output / summary
	Success bool
	Error   string
}
