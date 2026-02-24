// Package orchestrator implements the conversational orchestrator that accepts
// natural-language objectives, delegates planning to the Planner, and drives
// execution via the Scheduler.
package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"

	"github.com/juhgiyo/loguetown/internal/conversation"
	"github.com/juhgiyo/loguetown/internal/embeddings"
)

const orchestratorSystemPrompt = `You are the Loguetown orchestrator — a conversational assistant that helps users plan and execute coding tasks using AI agents.

You have the following tools:
- create_plan: decompose an objective into a task DAG and store it
- start_plan: begin executing a plan (spawns agents via the scheduler)
- get_status: show current plan/task status
- get_chronicle: view recent system events
- queue_run: re-queue a specific task
- get_memory: search memory for relevant knowledge

Workflow:
1. When the user gives you an objective, call create_plan to decompose it into tasks.
2. Show the plan to the user and ask for confirmation before starting.
3. On confirmation, call start_plan.
4. Use get_status to report progress when asked.

Always be concise and actionable. Confirm before executing anything irreversible.`

// Config holds the orchestrator configuration.
type Config struct {
	APIKey      string
	Model       string
	ProjectID   string
	ProjectPath string
	EmbProvider embeddings.Provider
	Enqueue     func(planID string) // callback to enqueue a plan in the scheduler
}

// Chat sends a user message in an ongoing (or new) conversation and returns
// the assistant's reply. It persists turns to the DB.
//
// convID: existing conversation ID, or "" to create a new one.
// Returns (conversationID, assistantReply, error).
func Chat(ctx context.Context, convID, userMessage string, cfg Config) (string, string, error) {
	apiKey := cfg.APIKey
	if apiKey == "" {
		apiKey = os.Getenv("ANTHROPIC_API_KEY")
	}
	if apiKey == "" {
		return convID, "", fmt.Errorf("ANTHROPIC_API_KEY is not set")
	}
	model := cfg.Model
	if model == "" {
		model = "claude-opus-4-6"
	}

	// Create conversation if new.
	if convID == "" {
		conv, err := conversation.CreateConversation(cfg.ProjectID, "orchestrator", truncateTitle(userMessage, 60))
		if err != nil {
			return "", "", fmt.Errorf("create conversation: %w", err)
		}
		convID = conv.ID
	}

	// Persist user turn.
	if _, err := conversation.AddTurn(convID, "user", userMessage, "", "", ""); err != nil {
		return convID, "", fmt.Errorf("add user turn: %w", err)
	}

	// Load conversation history to build messages array.
	turns, err := conversation.ListTurns(convID)
	if err != nil {
		return convID, "", fmt.Errorf("list turns: %w", err)
	}

	messages := make([]map[string]interface{}, 0, len(turns))
	for _, t := range turns {
		messages = append(messages, map[string]interface{}{
			"role":    t.Role,
			"content": t.Content,
		})
	}

	tools := orchestratorTools()
	client := &http.Client{}
	var assistantReply string

	// Agentic tool-use loop.
	for turn := 0; turn < 10; turn++ {
		resp, err := callAPI(ctx, client, apiKey, model, orchestratorSystemPrompt, messages, tools, nil)
		if err != nil {
			return convID, "", fmt.Errorf("API call: %w", err)
		}

		// Collect text and tool_use blocks.
		var toolUses []map[string]interface{}
		var textParts []string
		for _, block := range resp.Content {
			switch block["type"] {
			case "text":
				if t, ok := block["text"].(string); ok && t != "" {
					textParts = append(textParts, t)
					assistantReply = strings.Join(textParts, "\n")
				}
			case "tool_use":
				toolUses = append(toolUses, block)
			}
		}

		if resp.StopReason == "end_turn" || len(toolUses) == 0 {
			break
		}

		// Append assistant message with full content (including tool_use blocks).
		messages = append(messages, map[string]interface{}{
			"role":    "assistant",
			"content": resp.Content,
		})

		// Execute tools and collect results.
		var toolResults []map[string]interface{}
		for _, tu := range toolUses {
			id, _ := tu["id"].(string)
			name, _ := tu["name"].(string)
			inputRaw := tu["input"]

			result, toolErr := dispatchTool(ctx, name, inputRaw, cfg)
			content := result
			if toolErr != nil {
				content = fmt.Sprintf("Error: %v", toolErr)
			}
			toolResults = append(toolResults, map[string]interface{}{
				"type":        "tool_result",
				"tool_use_id": id,
				"content":     content,
			})
		}

		messages = append(messages, map[string]interface{}{
			"role":    "user",
			"content": toolResults,
		})
	}

	// Persist assistant reply.
	if assistantReply != "" {
		if _, err := conversation.AddTurn(convID, "assistant", assistantReply, "", "", ""); err != nil {
			return convID, assistantReply, fmt.Errorf("persist assistant turn: %w", err)
		}
	}

	return convID, assistantReply, nil
}

// dispatchTool executes an orchestrator tool call and returns its string result.
func dispatchTool(ctx context.Context, name string, inputRaw interface{}, cfg Config) (string, error) {
	// Re-marshal input to typed map.
	b, _ := json.Marshal(inputRaw)
	var input map[string]interface{}
	_ = json.Unmarshal(b, &input)

	strVal := func(key string) string {
		if v, ok := input[key].(string); ok {
			return v
		}
		return ""
	}
	intVal := func(key string) int {
		switch v := input[key].(type) {
		case float64:
			return int(v)
		case int:
			return v
		}
		return 0
	}

	switch name {
	case "create_plan":
		objective := strVal("objective")
		planID, summary, err := toolCreatePlan(ctx, cfg.ProjectID, objective, cfg.APIKey, cfg.Model)
		if err != nil {
			return "", err
		}
		_ = planID
		return summary, nil

	case "start_plan":
		planID := strVal("plan_id")
		return toolStartPlan(planID, cfg.Enqueue)

	case "get_status":
		planID := strVal("plan_id")
		return toolGetStatus(cfg.ProjectID, planID)

	case "get_chronicle":
		limit := intVal("limit")
		return toolGetChronicle(cfg.ProjectID, limit)

	case "queue_run":
		taskID := strVal("task_id")
		agentName := strVal("agent_name")
		return toolQueueRun(taskID, agentName)

	case "get_memory":
		query := strVal("query")
		return toolGetMemory(query, cfg.ProjectID, "", cfg.EmbProvider)

	default:
		return "", fmt.Errorf("unknown tool %q", name)
	}
}

// orchestratorTools returns the tool definitions for the orchestrator's API calls.
func orchestratorTools() []map[string]interface{} {
	return []map[string]interface{}{
		{
			"name":        "create_plan",
			"description": "Decompose an objective into a task DAG and store it in the database. Returns the plan ID and a summary of tasks.",
			"input_schema": map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"objective": map[string]interface{}{
						"type":        "string",
						"description": "The high-level objective to decompose into tasks",
					},
				},
				"required": []string{"objective"},
			},
		},
		{
			"name":        "start_plan",
			"description": "Start executing a plan by enqueuing it in the scheduler. Agents will begin working on tasks automatically.",
			"input_schema": map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"plan_id": map[string]interface{}{
						"type":        "string",
						"description": "The full plan ID to start",
					},
				},
				"required": []string{"plan_id"},
			},
		},
		{
			"name":        "get_status",
			"description": "Get the current status of plans and tasks. Optionally filter by plan ID.",
			"input_schema": map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"plan_id": map[string]interface{}{
						"type":        "string",
						"description": "Optional plan ID to filter status",
					},
				},
			},
		},
		{
			"name":        "get_chronicle",
			"description": "View recent system events from the chronicle.",
			"input_schema": map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"limit": map[string]interface{}{
						"type":        "integer",
						"description": "Number of recent events to return (default: 20)",
					},
				},
			},
		},
		{
			"name":        "queue_run",
			"description": "Re-queue a specific task for execution, optionally overriding the agent.",
			"input_schema": map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"task_id": map[string]interface{}{
						"type":        "string",
						"description": "Task ID to re-queue",
					},
					"agent_name": map[string]interface{}{
						"type":        "string",
						"description": "Optional: specific agent to use",
					},
				},
				"required": []string{"task_id"},
			},
		},
		{
			"name":        "get_memory",
			"description": "Search memory chunks for relevant knowledge about a topic.",
			"input_schema": map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"query": map[string]interface{}{
						"type":        "string",
						"description": "Search query",
					},
				},
				"required": []string{"query"},
			},
		},
	}
}

func truncateTitle(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
