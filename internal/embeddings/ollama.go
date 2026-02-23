package embeddings

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// OllamaProvider calls a local Ollama server to generate embeddings.
// API: POST /api/embeddings { "model": "...", "prompt": "..." }
type OllamaProvider struct {
	baseURL    string
	model      string
	dimensions int
	client     *http.Client
}

func newOllamaProvider(baseURL, model string, dimensions int) *OllamaProvider {
	if baseURL == "" {
		baseURL = "http://localhost:11434"
	}
	return &OllamaProvider{
		baseURL:    baseURL,
		model:      model,
		dimensions: dimensions,
		client:     &http.Client{Timeout: 30 * time.Second},
	}
}

func (p *OllamaProvider) Dimensions() int { return p.dimensions }

func (p *OllamaProvider) Embed(text string) ([]float32, error) {
	reqBody, _ := json.Marshal(map[string]string{
		"model":  p.model,
		"prompt": text,
	})

	resp, err := p.client.Post(p.baseURL+"/api/embeddings", "application/json", bytes.NewReader(reqBody))
	if err != nil {
		return nil, fmt.Errorf("ollama embed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("ollama embed: status %d", resp.StatusCode)
	}

	var result struct {
		Embedding []float32 `json:"embedding"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("ollama embed decode: %w", err)
	}
	if len(result.Embedding) == 0 {
		return nil, fmt.Errorf("ollama returned empty embedding")
	}
	return result.Embedding, nil
}
