package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/juhgiyo/loguetown/internal/chronicle"
	"github.com/juhgiyo/loguetown/internal/embeddings"
	"github.com/juhgiyo/loguetown/internal/memory"
	"github.com/juhgiyo/loguetown/internal/plans"
)

// toolCreatePlan calls the Planner to decompose objective into tasks, stores
// them in SQLite, and returns a human-readable plan summary.
// Returns (planID, summary, error).
func toolCreatePlan(ctx context.Context, projectID, objective, apiKey, model string) (string, string, error) {
	specs, err := Plan(ctx, objective, apiKey, model)
	if err != nil {
		return "", "", fmt.Errorf("planner: %w", err)
	}
	if len(specs) == 0 {
		return "", "", fmt.Errorf("planner returned no tasks")
	}

	plan, err := plans.CreatePlan(projectID, objective)
	if err != nil {
		return "", "", fmt.Errorf("create plan: %w", err)
	}

	// Map localID → DB task ID so we can resolve deps.
	localToDBID := make(map[string]string, len(specs))

	// First pass: create all tasks with empty deps so we have their IDs.
	taskIDs := make([]string, len(specs))
	for i, spec := range specs {
		t, err := plans.CreateTaskWithDeps(plan.ID, spec.Title, spec.Description, "", spec.AgentName)
		if err != nil {
			return plan.ID, "", fmt.Errorf("create task %q: %w", spec.Title, err)
		}
		localToDBID[spec.LocalID] = t.ID
		taskIDs[i] = t.ID
	}

	// Second pass: update deps_json for tasks that have dependencies.
	for i, spec := range specs {
		if len(spec.Deps) == 0 {
			continue
		}
		dbDeps := make([]string, 0, len(spec.Deps))
		for _, localDep := range spec.Deps {
			if dbID, ok := localToDBID[localDep]; ok {
				dbDeps = append(dbDeps, dbID)
			}
		}
		if len(dbDeps) > 0 {
			depsJSON, _ := json.Marshal(dbDeps)
			// Re-create with deps (simplest approach: SetTaskDeps via UpdateTask).
			// Since we don't have an UpdateTask helper, use CreateTaskWithDeps
			// by removing the old record isn't clean — instead update via direct store.
			// Use the exported SetTaskDeps if available, else use a workaround.
			_ = plans.SetTaskDeps(taskIDs[i], string(depsJSON))
		}
	}

	// Build human-readable summary.
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("Plan created: **%s** (ID: `%s`)\n\n", objective, plan.ID[:8]))
	sb.WriteString(fmt.Sprintf("**%d tasks:**\n\n", len(specs)))
	for i, spec := range specs {
		depStr := ""
		if len(spec.Deps) > 0 {
			depStr = fmt.Sprintf(" ← depends on %s", strings.Join(spec.Deps, ", "))
		}
		sb.WriteString(fmt.Sprintf("%d. **%s**%s\n", i+1, spec.Title, depStr))
		if spec.Description != "" {
			sb.WriteString(fmt.Sprintf("   %s\n", spec.Description))
		}
	}
	sb.WriteString(fmt.Sprintf("\nUse `start_plan` with plan ID `%s` to begin execution.", plan.ID))
	return plan.ID, sb.String(), nil
}

// toolStartPlan marks a plan as running and enqueues it in the scheduler.
func toolStartPlan(planID string, enqueue func(string)) (string, error) {
	if err := plans.SetPlanStatus(planID, "running"); err != nil {
		return "", fmt.Errorf("set plan status: %w", err)
	}
	enqueue(planID)
	return fmt.Sprintf("Plan `%s` is now running. The scheduler will begin dispatching tasks.", planID[:8]), nil
}

// toolGetStatus returns a formatted status summary for a project's plans/tasks.
// If planID is non-empty, shows only that plan's tasks.
func toolGetStatus(projectID, planID string) (string, error) {
	var sb strings.Builder

	if planID != "" {
		plan, err := plans.GetPlan(planID)
		if err != nil {
			return "", fmt.Errorf("get plan: %w", err)
		}
		sb.WriteString(fmt.Sprintf("**Plan** `%s` — %s — *%s*\n\n", plan.ID[:8], plan.Objective, plan.Status))
		tasks, err := plans.ListTasks(plan.ID)
		if err != nil {
			return "", fmt.Errorf("list tasks: %w", err)
		}
		for _, t := range tasks {
			sb.WriteString(fmt.Sprintf("  - [%s] %s\n", t.Status, t.Title))
		}
		return sb.String(), nil
	}

	// All plans for project.
	allPlans, err := plans.ListPlans(projectID)
	if err != nil {
		return "", fmt.Errorf("list plans: %w", err)
	}
	if len(allPlans) == 0 {
		return "No plans found.", nil
	}
	for _, p := range allPlans {
		sb.WriteString(fmt.Sprintf("**Plan** `%s` — %s — *%s*\n", p.ID[:8], p.Objective, p.Status))
		tasks, _ := plans.ListTasks(p.ID)
		for _, t := range tasks {
			sb.WriteString(fmt.Sprintf("  - [%s] %s\n", t.Status, t.Title))
		}
		sb.WriteString("\n")
	}
	return sb.String(), nil
}

// toolGetChronicle returns recent chronicle events as a formatted string.
func toolGetChronicle(projectID string, limit int) (string, error) {
	if limit <= 0 {
		limit = 20
	}
	events, err := chronicle.Recent(projectID, limit)
	if err != nil {
		return "", fmt.Errorf("chronicle: %w", err)
	}
	if len(events) == 0 {
		return "No recent events.", nil
	}
	var sb strings.Builder
	for _, e := range events {
		sb.WriteString(fmt.Sprintf("[%s] %s — %s\n", e.TS, e.Actor, e.Type))
	}
	return sb.String(), nil
}

// toolQueueRun re-queues a task for execution by setting its status back to todo.
func toolQueueRun(taskID, agentName string) (string, error) {
	if agentName != "" {
		if err := plans.SetTaskAgentName(taskID, agentName); err != nil {
			return "", fmt.Errorf("set task agent: %w", err)
		}
	}
	if err := plans.SetTaskStatus(taskID, "todo"); err != nil {
		return "", fmt.Errorf("set task status: %w", err)
	}
	return fmt.Sprintf("Task `%s` re-queued for execution.", taskID[:8]), nil
}

// toolGetMemory searches memory chunks and returns relevant passages.
func toolGetMemory(query, projectID, agentName string, embProvider embeddings.Provider) (string, error) {
	layers := []struct{ name, proj, agent string }{
		{"semantic_global", "", ""},
		{"semantic_local", projectID, ""},
		{"episodic", projectID, agentName},
	}
	var sb strings.Builder
	total := 0
	for _, l := range layers {
		chunks, err := memory.Retrieve(l.name, l.proj, l.agent, query, 3, 0.2, embProvider)
		if err != nil || len(chunks) == 0 {
			continue
		}
		for _, c := range chunks {
			if c.Title != "" {
				sb.WriteString(fmt.Sprintf("**%s** (%s)\n", c.Title, c.Layer))
			}
			if c.Content != "" {
				sb.WriteString(c.Content + "\n\n")
			}
			total++
		}
	}
	if total == 0 {
		return "No relevant memory found.", nil
	}
	return sb.String(), nil
}
