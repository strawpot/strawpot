package runner

import (
	"fmt"
	"os"

	"github.com/steveyegge/loguetown/internal/config"
)

// New returns the Provider configured in cfg.
// Supported providers: "claude-code" (default), "anthropic-api".
func New(cfg config.RunnerConfig) (Provider, error) {
	provider := cfg.Provider
	if provider == "" {
		provider = "claude-code"
	}

	timeout := cfg.TimeoutMinutes
	if timeout <= 0 {
		timeout = 20
	}

	switch provider {
	case "claude-code", "claude":
		return &ClaudeCodeProvider{TimeoutMinutes: timeout}, nil

	case "anthropic-api", "anthropic":
		apiKey := cfg.APIKey
		if apiKey == "" {
			apiKey = os.Getenv("ANTHROPIC_API_KEY")
		}
		model := cfg.Model
		if model == "" {
			model = "claude-opus-4-6"
		}
		maxTurns := cfg.MaxTurns
		if maxTurns <= 0 {
			maxTurns = 50
		}
		return &AnthropicProvider{
			APIKey:         apiKey,
			Model:          model,
			TimeoutMinutes: timeout,
		}, nil

	default:
		return nil, fmt.Errorf("unknown runner provider %q (supported: claude-code, anthropic-api)", provider)
	}
}
