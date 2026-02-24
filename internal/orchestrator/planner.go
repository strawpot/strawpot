package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
)

// TaskSpec is a single task returned by the Planner.
type TaskSpec struct {
	LocalID     string   // short local ID used within the DAG (e.g. "T1")
	Title       string
	Description string
	Deps        []string // LocalIDs of tasks this task depends on
	AgentName   string   // optional — scheduler picks first matching agent if empty
}

const plannerSystemPrompt = `You are a software project planner.
Given an objective, decompose it into a concrete task DAG for AI coding agents.
Each task should be a focused, self-contained unit of work.
Use the create_task_dag tool to return the structured plan.`

// Plan calls the Anthropic API with a forced tool_use to produce a task DAG.
// It does NOT write to the database — the caller is responsible for persistence.
func Plan(ctx context.Context, objective, apiKey, model string) ([]TaskSpec, error) {
	if apiKey == "" {
		apiKey = os.Getenv("ANTHROPIC_API_KEY")
	}
	if apiKey == "" {
		return nil, fmt.Errorf("ANTHROPIC_API_KEY is not set")
	}
	if model == "" {
		model = "claude-opus-4-6"
	}

	dagTool := map[string]interface{}{
		"name":        "create_task_dag",
		"description": "Create a task dependency graph for the given objective.",
		"input_schema": map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"tasks": map[string]interface{}{
					"type":        "array",
					"description": "Ordered list of tasks. Earlier tasks may be deps of later ones.",
					"items": map[string]interface{}{
						"type": "object",
						"properties": map[string]interface{}{
							"id": map[string]interface{}{
								"type":        "string",
								"description": "Short local identifier, e.g. T1, T2",
							},
							"title": map[string]interface{}{
								"type":        "string",
								"description": "Concise task title (max 80 chars)",
							},
							"description": map[string]interface{}{
								"type":        "string",
								"description": "Detailed description of what the agent should do",
							},
							"deps": map[string]interface{}{
								"type":        "array",
								"items":       map[string]interface{}{"type": "string"},
								"description": "Local IDs of tasks that must complete before this one starts",
							},
							"agent_name": map[string]interface{}{
								"type":        "string",
								"description": "Specific agent to use (leave empty for auto-selection)",
							},
						},
						"required": []string{"id", "title"},
					},
				},
			},
			"required": []string{"tasks"},
		},
	}

	messages := []map[string]interface{}{
		{"role": "user", "content": fmt.Sprintf("Objective: %s", objective)},
	}

	client := &http.Client{}
	resp, err := callAPI(ctx, client, apiKey, model, plannerSystemPrompt, messages,
		[]map[string]interface{}{dagTool},
		map[string]interface{}{"type": "tool", "name": "create_task_dag"},
	)
	if err != nil {
		return nil, fmt.Errorf("planner API call: %w", err)
	}

	// Extract the tool_use block.
	for _, block := range resp.Content {
		if block["type"] != "tool_use" {
			continue
		}
		inputRaw, ok := block["input"]
		if !ok {
			continue
		}
		// Re-marshal so we can unmarshal into a typed struct.
		b, err := json.Marshal(inputRaw)
		if err != nil {
			return nil, fmt.Errorf("marshal tool input: %w", err)
		}

		var input struct {
			Tasks []struct {
				ID          string   `json:"id"`
				Title       string   `json:"title"`
				Description string   `json:"description"`
				Deps        []string `json:"deps"`
				AgentName   string   `json:"agent_name"`
			} `json:"tasks"`
		}
		if err := json.Unmarshal(b, &input); err != nil {
			return nil, fmt.Errorf("unmarshal planner output: %w", err)
		}

		specs := make([]TaskSpec, 0, len(input.Tasks))
		for _, t := range input.Tasks {
			specs = append(specs, TaskSpec{
				LocalID:     t.ID,
				Title:       t.Title,
				Description: t.Description,
				Deps:        t.Deps,
				AgentName:   t.AgentName,
			})
		}
		return specs, nil
	}

	return nil, fmt.Errorf("planner did not return a create_task_dag tool call")
}
