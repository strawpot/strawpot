package embeddings

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"time"
)

// OpenAIProvider calls any OpenAI-compatible /v1/embeddings endpoint.
type OpenAIProvider struct {
	baseURL    string
	model      string
	apiKey     string
	dimensions int
	client     *http.Client
}

func newOpenAIProvider(baseURL, model, apiKey string, dimensions int) *OpenAIProvider {
	if baseURL == "" {
		baseURL = "https://api.openai.com"
	}
	if apiKey == "" {
		apiKey = os.Getenv("OPENAI_API_KEY")
	}
	return &OpenAIProvider{
		baseURL:    baseURL,
		model:      model,
		apiKey:     apiKey,
		dimensions: dimensions,
		client:     &http.Client{Timeout: 30 * time.Second},
	}
}

func (p *OpenAIProvider) Dimensions() int { return p.dimensions }

func (p *OpenAIProvider) Embed(text string) ([]float32, error) {
	reqBody, _ := json.Marshal(map[string]interface{}{
		"model": p.model,
		"input": text,
	})

	req, err := http.NewRequest("POST", p.baseURL+"/v1/embeddings", bytes.NewReader(reqBody))
	if err != nil {
		return nil, fmt.Errorf("openai embed request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if p.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+p.apiKey)
	}

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("openai embed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("openai embed: status %d", resp.StatusCode)
	}

	var result struct {
		Data []struct {
			Embedding []float32 `json:"embedding"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("openai embed decode: %w", err)
	}
	if len(result.Data) == 0 || len(result.Data[0].Embedding) == 0 {
		return nil, fmt.Errorf("openai returned empty embedding")
	}
	return result.Data[0].Embedding, nil
}
