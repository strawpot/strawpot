package runner

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const anthropicAPIURL = "https://api.anthropic.com/v1/messages"
const anthropicVersion = "2023-06-01"

// AnthropicProvider calls the Anthropic Messages API directly with a
// tool-use agentic loop (read_file, write_file, run_bash, list_directory).
type AnthropicProvider struct {
	APIKey         string
	Model          string
	TimeoutMinutes int
}

func (p *AnthropicProvider) Name() string { return "anthropic-api" }

func (p *AnthropicProvider) Execute(ctx context.Context, req ExecuteRequest) (ExecuteResult, error) {
	apiKey := p.APIKey
	if apiKey == "" {
		apiKey = req.APIKey
	}
	if apiKey == "" {
		apiKey = os.Getenv("ANTHROPIC_API_KEY")
	}
	if apiKey == "" {
		return ExecuteResult{}, fmt.Errorf("ANTHROPIC_API_KEY is not set")
	}

	model := p.Model
	if model == "" {
		model = req.Model
	}
	if model == "" {
		model = "claude-opus-4-6"
	}

	timeout := time.Duration(p.TimeoutMinutes) * time.Minute
	if timeout <= 0 {
		timeout = 20 * time.Minute
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	maxTurns := req.MaxTurns
	if maxTurns <= 0 {
		maxTurns = 50
	}

	tools := agentTools()
	messages := []map[string]interface{}{
		{"role": "user", "content": req.Task},
	}

	client := &http.Client{}
	var lastText string

	for turn := 0; turn < maxTurns; turn++ {
		resp, err := callMessages(ctx, client, apiKey, model, req.SystemPrompt, messages, tools)
		if err != nil {
			return ExecuteResult{}, fmt.Errorf("messages API: %w", err)
		}

		// Collect text and tool_use blocks.
		var toolUses []map[string]interface{}
		for _, block := range resp.Content {
			switch block["type"] {
			case "text":
				if t, ok := block["text"].(string); ok {
					lastText = t
				}
			case "tool_use":
				toolUses = append(toolUses, block)
			}
		}

		// Append assistant message.
		messages = append(messages, map[string]interface{}{
			"role":    "assistant",
			"content": resp.Content,
		})

		if resp.StopReason == "end_turn" || len(toolUses) == 0 {
			break
		}

		// Execute tools and build tool_result message.
		var toolResults []map[string]interface{}
		for _, tu := range toolUses {
			id, _ := tu["id"].(string)
			name, _ := tu["name"].(string)
			inputRaw, _ := tu["input"].(map[string]interface{})

			output, toolErr := executeTool(name, inputRaw, req.WorkDir, req.BashAllowlist)
			result := map[string]interface{}{
				"type":        "tool_result",
				"tool_use_id": id,
				"content":     output,
			}
			if toolErr != nil {
				result["is_error"] = true
				result["content"] = toolErr.Error()
			}
			toolResults = append(toolResults, result)
		}

		messages = append(messages, map[string]interface{}{
			"role":    "user",
			"content": toolResults,
		})
	}

	return ExecuteResult{Output: lastText, Success: true}, nil
}

// ── Anthropic API types ───────────────────────────────────────────────────────

type messagesResponse struct {
	Content    []map[string]interface{} `json:"content"`
	StopReason string                   `json:"stop_reason"`
}

func callMessages(
	ctx context.Context,
	client *http.Client,
	apiKey, model, systemPrompt string,
	messages []map[string]interface{},
	tools []map[string]interface{},
) (*messagesResponse, error) {
	body := map[string]interface{}{
		"model":      model,
		"max_tokens": 4096,
		"messages":   messages,
		"tools":      tools,
	}
	if systemPrompt != "" {
		body["system"] = systemPrompt
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

// ── Tool definitions ──────────────────────────────────────────────────────────

func agentTools() []map[string]interface{} {
	return []map[string]interface{}{
		{
			"name":        "read_file",
			"description": "Read the contents of a file in the working directory.",
			"input_schema": map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"path": map[string]interface{}{"type": "string", "description": "File path relative to the working directory"},
				},
				"required": []string{"path"},
			},
		},
		{
			"name":        "write_file",
			"description": "Write content to a file in the working directory (creates or overwrites).",
			"input_schema": map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"path":    map[string]interface{}{"type": "string"},
					"content": map[string]interface{}{"type": "string"},
				},
				"required": []string{"path", "content"},
			},
		},
		{
			"name":        "run_bash",
			"description": "Run a bash command in the working directory.",
			"input_schema": map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"command": map[string]interface{}{"type": "string"},
				},
				"required": []string{"command"},
			},
		},
		{
			"name":        "list_directory",
			"description": "List files in a directory relative to the working directory.",
			"input_schema": map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"path": map[string]interface{}{"type": "string", "description": "Directory path (default: '.')"},
				},
				"required": []string{},
			},
		},
	}
}

// ── Tool execution ────────────────────────────────────────────────────────────

func executeTool(name string, input map[string]interface{}, workDir string, allowlist []string) (string, error) {
	switch name {
	case "read_file":
		path, _ := input["path"].(string)
		abs := safeJoin(workDir, path)
		data, err := os.ReadFile(abs)
		if err != nil {
			return "", fmt.Errorf("read_file %q: %w", path, err)
		}
		return string(data), nil

	case "write_file":
		path, _ := input["path"].(string)
		content, _ := input["content"].(string)
		abs := safeJoin(workDir, path)
		if err := os.MkdirAll(filepath.Dir(abs), 0o755); err != nil {
			return "", err
		}
		if err := os.WriteFile(abs, []byte(content), 0o644); err != nil {
			return "", fmt.Errorf("write_file %q: %w", path, err)
		}
		return "written", nil

	case "run_bash":
		command, _ := input["command"].(string)
		if !bashAllowed(command, allowlist) {
			return "", fmt.Errorf("command not in allowlist: %q", command)
		}
		var out bytes.Buffer
		cmd := exec.Command("bash", "-c", command)
		cmd.Dir = workDir
		cmd.Stdout = &out
		cmd.Stderr = &out
		if err := cmd.Run(); err != nil {
			return out.String(), fmt.Errorf("bash exited: %w", err)
		}
		return out.String(), nil

	case "list_directory":
		path, _ := input["path"].(string)
		if path == "" {
			path = "."
		}
		abs := safeJoin(workDir, path)
		entries, err := os.ReadDir(abs)
		if err != nil {
			return "", fmt.Errorf("list_directory %q: %w", path, err)
		}
		var lines []string
		for _, e := range entries {
			if e.IsDir() {
				lines = append(lines, e.Name()+"/")
			} else {
				lines = append(lines, e.Name())
			}
		}
		return strings.Join(lines, "\n"), nil

	default:
		return "", fmt.Errorf("unknown tool %q", name)
	}
}

// safeJoin joins workDir and path, refusing to escape workDir.
func safeJoin(workDir, rel string) string {
	clean := filepath.Join(workDir, filepath.Clean("/"+rel))
	if !strings.HasPrefix(clean, workDir) {
		return workDir // silently clamp
	}
	return clean
}

// bashAllowed checks whether command matches any allowlist glob pattern.
// If allowlist is empty, all commands are permitted.
func bashAllowed(command string, allowlist []string) bool {
	if len(allowlist) == 0 {
		return true
	}
	for _, pattern := range allowlist {
		if matched, _ := filepath.Match(pattern, command); matched {
			return true
		}
		// Also allow prefix match (e.g. "git *" matches "git commit -m 'msg'").
		parts := strings.SplitN(pattern, " ", 2)
		if parts[0] != "" && strings.HasPrefix(command, parts[0]+" ") {
			return true
		}
		if command == parts[0] {
			return true
		}
	}
	return false
}
