package orchestrator

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
)

const anthropicAPIURL = "https://api.anthropic.com/v1/messages"
const anthropicVersion = "2023-06-01"

type messagesResponse struct {
	Content    []map[string]interface{} `json:"content"`
	StopReason string                   `json:"stop_reason"`
}

// callAPI posts a request to the Anthropic Messages API and returns the response.
func callAPI(
	ctx context.Context,
	client *http.Client,
	apiKey, model, systemPrompt string,
	messages []map[string]interface{},
	tools []map[string]interface{},
	toolChoice map[string]interface{},
) (*messagesResponse, error) {
	body := map[string]interface{}{
		"model":      model,
		"max_tokens": 4096,
		"messages":   messages,
	}
	if systemPrompt != "" {
		body["system"] = systemPrompt
	}
	if len(tools) > 0 {
		body["tools"] = tools
	}
	if toolChoice != nil {
		body["tool_choice"] = toolChoice
	}

	data, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequestWithContext(ctx, "POST", anthropicAPIURL, bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-api-key", apiKey)
	req.Header.Set("anthropic-version", anthropicVersion)

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		var errBody map[string]interface{}
		json.NewDecoder(resp.Body).Decode(&errBody)
		return nil, fmt.Errorf("anthropic API status %d: %v", resp.StatusCode, errBody)
	}

	var result messagesResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	return &result, nil
}
