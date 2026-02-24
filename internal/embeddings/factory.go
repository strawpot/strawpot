package embeddings

import (
	"fmt"

	"github.com/juhgiyo/loguetown/internal/config"
)

// New returns the Provider configured in the project embeddings config.
// Supported providers: "ollama", "openai".
func New(cfg config.EmbeddingsConfig) (Provider, error) {
	dims := cfg.Dimensions
	if dims <= 0 {
		dims = 384 // safe default
	}

	switch cfg.Provider {
	case "ollama", "":
		model := cfg.Model
		if model == "" {
			model = "nomic-embed-text"
		}
		return newOllamaProvider(cfg.BaseURL, model, dims), nil

	case "openai":
		model := cfg.Model
		if model == "" {
			model = "text-embedding-3-small"
		}
		return newOpenAIProvider(cfg.BaseURL, model, cfg.APIKey, dims), nil

	default:
		return nil, fmt.Errorf("unknown embedding provider %q (supported: ollama, openai)", cfg.Provider)
	}
}
