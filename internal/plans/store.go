// Package plans provides CRUD access to the plans, tasks, and runs SQLite tables.
package plans

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/juhgiyo/loguetown/internal/storage"
)

// ── Plan ──────────────────────────────────────────────────────────────────────

// Plan is a high-level objective with one or more tasks.
type Plan struct {
	ID        string `json:"id"`
	ProjectID string `json:"project_id"`
	Objective string `json:"objective"`
	Status    string `json:"status"` // draft | running | done | failed | canceled
	CreatedAt string `json:"created_at"`
}

// CreatePlan inserts a new plan record.
func CreatePlan(projectID, objective string) (*Plan, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	p := &Plan{
		ID:        uuid.New().String(),
		ProjectID: projectID,
		Objective: objective,
		Status:    "running",
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	}
	_, err = db.Exec(
		`INSERT INTO plans (id, project_id, objective, status, created_at)
		 VALUES (?, ?, ?, ?, ?)`,
		p.ID, p.ProjectID, p.Objective, p.Status, p.CreatedAt,
	)
	return p, err
}

// GetPlan returns a plan by ID.
func GetPlan(id string) (*Plan, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	var p Plan
	err = db.QueryRow(
		`SELECT id, project_id, objective, status, created_at FROM plans WHERE id = ?`, id,
	).Scan(&p.ID, &p.ProjectID, &p.Objective, &p.Status, &p.CreatedAt)
	if err != nil {
		return nil, fmt.Errorf("get plan %s: %w", id, err)
	}
	return &p, nil
}

// ListPlans returns all plans for a project, newest first.
func ListPlans(projectID string) ([]Plan, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(
		`SELECT id, project_id, objective, status, created_at
		 FROM plans WHERE project_id = ? ORDER BY created_at DESC`, projectID,
	)
	if err != nil {
		return nil, fmt.Errorf("list plans: %w", err)
	}
	defer rows.Close()

	var plans []Plan
	for rows.Next() {
		var p Plan
		if err := rows.Scan(&p.ID, &p.ProjectID, &p.Objective, &p.Status, &p.CreatedAt); err != nil {
			return nil, err
		}
		plans = append(plans, p)
	}
	return plans, rows.Err()
}

// ListRunningPlans returns plans with status='running' for a project, oldest first.
// Used by the patrol loop to re-enqueue in-flight plans after a restart.
func ListRunningPlans(projectID string) ([]Plan, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(
		`SELECT id, project_id, objective, status, created_at
		 FROM plans WHERE project_id = ? AND status = 'running' ORDER BY created_at ASC`, projectID,
	)
	if err != nil {
		return nil, fmt.Errorf("list running plans: %w", err)
	}
	defer rows.Close()

	var out []Plan
	for rows.Next() {
		var p Plan
		if err := rows.Scan(&p.ID, &p.ProjectID, &p.Objective, &p.Status, &p.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

// ResetOrphanedTasks resets tasks stuck in "running" state back to "todo".
// A task can be orphaned when the scheduler process is killed while a runner
// goroutine is active. Call this at startup before re-enqueuing plans.
func ResetOrphanedTasks(projectID string) error {
	db, err := storage.Get()
	if err != nil {
		return err
	}
	_, err = db.Exec(
		`UPDATE tasks SET status = 'todo'
		 WHERE status = 'running'
		   AND plan_id IN (SELECT id FROM plans WHERE project_id = ?)`, projectID,
	)
	return err
}

// SetPlanStatus updates a plan's status.
func SetPlanStatus(id, status string) error {
	db, err := storage.Get()
	if err != nil {
		return err
	}
	_, err = db.Exec("UPDATE plans SET status = ? WHERE id = ?", status, id)
	return err
}

// ── Task ──────────────────────────────────────────────────────────────────────

// Task is a single unit of work within a plan.
type Task struct {
	ID          string `json:"id"`
	PlanID      string `json:"plan_id"`
	Title       string `json:"title"`
	Description string `json:"description,omitempty"`
	DepsJSON    string `json:"deps_json,omitempty"` // JSON array of task IDs this task depends on
	AgentName   string `json:"agent_name,omitempty"`
	Status      string `json:"status"` // todo | running | done | failed | needs-human
	CreatedAt   string `json:"created_at"`
}

// CreateTask inserts a new task.
func CreateTask(planID, title, description string) (*Task, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	t := &Task{
		ID:          uuid.New().String(),
		PlanID:      planID,
		Title:       title,
		Description: description,
		Status:      "running",
		CreatedAt:   time.Now().UTC().Format(time.RFC3339),
	}
	_, err = db.Exec(
		`INSERT INTO tasks (id, plan_id, title, description, status, created_at)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		t.ID, t.PlanID, t.Title, nullStr(t.Description), t.Status, t.CreatedAt,
	)
	return t, err
}

// GetTask returns a task by ID.
func GetTask(id string) (*Task, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	var t Task
	err = db.QueryRow(
		`SELECT id, plan_id, title, COALESCE(description,''), COALESCE(deps_json,''),
		        COALESCE(agent_name,''), status, created_at
		 FROM tasks WHERE id = ?`, id,
	).Scan(&t.ID, &t.PlanID, &t.Title, &t.Description, &t.DepsJSON, &t.AgentName, &t.Status, &t.CreatedAt)
	if err != nil {
		return nil, fmt.Errorf("get task %s: %w", id, err)
	}
	return &t, nil
}

// ListTasks returns all tasks for a plan.
func ListTasks(planID string) ([]Task, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(
		`SELECT id, plan_id, title, COALESCE(description,''), COALESCE(deps_json,''),
		        COALESCE(agent_name,''), status, created_at
		 FROM tasks WHERE plan_id = ? ORDER BY created_at ASC`, planID,
	)
	if err != nil {
		return nil, fmt.Errorf("list tasks: %w", err)
	}
	defer rows.Close()

	var tasks []Task
	for rows.Next() {
		var t Task
		if err := rows.Scan(&t.ID, &t.PlanID, &t.Title, &t.Description, &t.DepsJSON, &t.AgentName, &t.Status, &t.CreatedAt); err != nil {
			return nil, err
		}
		tasks = append(tasks, t)
	}
	return tasks, rows.Err()
}

// CreateTaskWithDeps inserts a new task with status=todo and optional dependency list.
// depsJSON is a JSON array of task IDs (e.g. `["id1","id2"]`); empty string means no deps.
// agentName may be empty; the scheduler will pick the first available agent with the right role.
func CreateTaskWithDeps(planID, title, description, depsJSON, agentName string) (*Task, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	t := &Task{
		ID:          uuid.New().String(),
		PlanID:      planID,
		Title:       title,
		Description: description,
		DepsJSON:    depsJSON,
		AgentName:   agentName,
		Status:      "todo",
		CreatedAt:   time.Now().UTC().Format(time.RFC3339),
	}
	_, err = db.Exec(
		`INSERT INTO tasks (id, plan_id, title, description, deps_json, agent_name, status, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		t.ID, t.PlanID, t.Title, nullStr(t.Description), nullStr(t.DepsJSON), nullStr(t.AgentName),
		t.Status, t.CreatedAt,
	)
	return t, err
}

// ListReadyTasks returns tasks for a plan with status=todo whose dependencies are all done.
func ListReadyTasks(planID string) ([]Task, error) {
	all, err := ListTasks(planID)
	if err != nil {
		return nil, err
	}

	// Build a map of taskID → status for dep resolution.
	statusByID := make(map[string]string, len(all))
	for _, t := range all {
		statusByID[t.ID] = t.Status
	}

	var ready []Task
	for _, t := range all {
		if t.Status != "todo" {
			continue
		}
		if t.DepsJSON == "" || t.DepsJSON == "[]" || t.DepsJSON == "null" {
			ready = append(ready, t)
			continue
		}
		// Parse deps_json as []string.
		var deps []string
		if err := json.Unmarshal([]byte(t.DepsJSON), &deps); err != nil {
			continue // malformed deps — skip
		}
		allDone := true
		for _, dep := range deps {
			s := statusByID[dep]
			if s != "done" && s != "merged" {
				allDone = false
				break
			}
		}
		if allDone {
			ready = append(ready, t)
		}
	}
	return ready, nil
}

// SetTaskStatus updates a task's status.
func SetTaskStatus(id, status string) error {
	db, err := storage.Get()
	if err != nil {
		return err
	}
	_, err = db.Exec("UPDATE tasks SET status = ? WHERE id = ?", status, id)
	return err
}

// SetTaskDeps updates the deps_json field of a task.
func SetTaskDeps(id, depsJSON string) error {
	db, err := storage.Get()
	if err != nil {
		return err
	}
	_, err = db.Exec("UPDATE tasks SET deps_json = ? WHERE id = ?", nullStr(depsJSON), id)
	return err
}

// SetTaskAgentName sets the preferred agent for a task.
func SetTaskAgentName(id, agentName string) error {
	db, err := storage.Get()
	if err != nil {
		return err
	}
	_, err = db.Exec("UPDATE tasks SET agent_name = ? WHERE id = ?", nullStr(agentName), id)
	return err
}

// ── Run ───────────────────────────────────────────────────────────────────────

// Run is one agent execution attempt for a task.
type Run struct {
	ID           string  `json:"id"`
	TaskID       string  `json:"task_id"`
	Role         string  `json:"role"`
	Status       string  `json:"status"` // queued | running | succeeded | failed
	Attempt      int     `json:"attempt"`
	AgentName    string  `json:"agent_name,omitempty"`
	WorktreePath string  `json:"worktree_path,omitempty"`
	Branch       string  `json:"branch,omitempty"`
	BaseSHA      string  `json:"base_sha,omitempty"`
	HeadSHA      string  `json:"head_sha,omitempty"`
	StartedAt    *string `json:"started_at,omitempty"`
	EndedAt      *string `json:"ended_at,omitempty"`
}

// CreateRun inserts a new run record with status=queued.
func CreateRun(taskID, role, agentName string, attempt int) (*Run, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	r := &Run{
		ID:        uuid.New().String(),
		TaskID:    taskID,
		Role:      role,
		Status:    "queued",
		Attempt:   attempt,
		AgentName: agentName,
	}
	_, err = db.Exec(
		`INSERT INTO runs (id, task_id, role, status, attempt, agent_name)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		r.ID, r.TaskID, r.Role, r.Status, r.Attempt, nullStr(r.AgentName),
	)
	return r, err
}

// RunUpdates holds optional fields to update on a run.
type RunUpdates struct {
	Status       string
	WorktreePath string
	Branch       string
	BaseSHA      string
	HeadSHA      string
	StartedAt    string
	EndedAt      string
}

// UpdateRun applies RunUpdates to a run record.
func UpdateRun(id string, u RunUpdates) error {
	db, err := storage.Get()
	if err != nil {
		return err
	}
	_, err = db.Exec(`
		UPDATE runs SET
			status        = COALESCE(NULLIF(?, ''), status),
			worktree_path = COALESCE(NULLIF(?, ''), worktree_path),
			branch        = COALESCE(NULLIF(?, ''), branch),
			base_sha      = COALESCE(NULLIF(?, ''), base_sha),
			head_sha      = COALESCE(NULLIF(?, ''), head_sha),
			started_at    = COALESCE(NULLIF(?, ''), started_at),
			ended_at      = COALESCE(NULLIF(?, ''), ended_at)
		WHERE id = ?`,
		u.Status, u.WorktreePath, u.Branch, u.BaseSHA, u.HeadSHA,
		u.StartedAt, u.EndedAt, id,
	)
	return err
}

// GetRun returns a run by ID.
func GetRun(id string) (*Run, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	return scanRun(db.QueryRow(
		`SELECT id, task_id, role, status, attempt,
		        COALESCE(agent_name,''), COALESCE(worktree_path,''),
		        COALESCE(branch,''), COALESCE(base_sha,''), COALESCE(head_sha,''),
		        started_at, ended_at
		 FROM runs WHERE id = ?`, id,
	))
}

// ListRuns returns all runs for a task, newest first.
func ListRuns(taskID string) ([]Run, error) {
	db, err := storage.Get()
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(
		`SELECT id, task_id, role, status, attempt,
		        COALESCE(agent_name,''), COALESCE(worktree_path,''),
		        COALESCE(branch,''), COALESCE(base_sha,''), COALESCE(head_sha,''),
		        started_at, ended_at
		 FROM runs WHERE task_id = ? ORDER BY attempt ASC`, taskID,
	)
	if err != nil {
		return nil, fmt.Errorf("list runs: %w", err)
	}
	defer rows.Close()

	var runs []Run
	for rows.Next() {
		r, err := scanRun(rows)
		if err != nil {
			return nil, err
		}
		runs = append(runs, *r)
	}
	return runs, rows.Err()
}

// ── helpers ───────────────────────────────────────────────────────────────────

type scanner interface {
	Scan(dest ...any) error
}

func scanRun(row scanner) (*Run, error) {
	var r Run
	var startedAt, endedAt sql.NullString
	err := row.Scan(
		&r.ID, &r.TaskID, &r.Role, &r.Status, &r.Attempt,
		&r.AgentName, &r.WorktreePath, &r.Branch, &r.BaseSHA, &r.HeadSHA,
		&startedAt, &endedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("scan run: %w", err)
	}
	if startedAt.Valid {
		r.StartedAt = &startedAt.String
	}
	if endedAt.Valid {
		r.EndedAt = &endedAt.String
	}
	return &r, nil
}

func nullStr(s string) interface{} {
	if s == "" {
		return nil
	}
	return s
}
