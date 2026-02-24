package plans

import (
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/steveyegge/loguetown/internal/storage"
)

// TestMain isolates the storage singleton in a temp home dir.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "plans-test-*")
	if err != nil {
		os.Exit(1)
	}
	defer os.RemoveAll(dir)
	os.Setenv("HOME", dir)
	os.Exit(m.Run())
}

// ensureProject inserts a project row so foreign-key constraints on plans are satisfied.
// It is idempotent — a second call with the same ID is a no-op.
func ensureProject(t *testing.T, id string) {
	t.Helper()
	db, err := storage.Get()
	if err != nil {
		t.Fatalf("storage.Get: %v", err)
	}
	_, err = db.Exec(
		`INSERT OR IGNORE INTO projects (id, name, repo_path, default_branch, created_at)
		 VALUES (?, ?, ?, ?, ?)`,
		id, fmt.Sprintf("project-%s", id), "/tmp/test-repo", "main",
		time.Now().UTC().Format(time.RFC3339),
	)
	if err != nil {
		t.Fatalf("ensureProject %q: %v", id, err)
	}
}

// ── Plan ──────────────────────────────────────────────────────────────────────

func TestCreateAndGetPlan(t *testing.T) {
	ensureProject(t, "proj1")
	p, err := CreatePlan("proj1", "Add login")
	if err != nil {
		t.Fatalf("CreatePlan: %v", err)
	}
	if p.ID == "" {
		t.Error("ID should be set after CreatePlan")
	}
	if p.Status != "running" {
		t.Errorf("default status: want 'running', got %q", p.Status)
	}
	if p.ProjectID != "proj1" {
		t.Errorf("ProjectID: want 'proj1', got %q", p.ProjectID)
	}

	got, err := GetPlan(p.ID)
	if err != nil {
		t.Fatalf("GetPlan: %v", err)
	}
	if got.ID != p.ID {
		t.Errorf("ID mismatch: want %q, got %q", p.ID, got.ID)
	}
	if got.Objective != "Add login" {
		t.Errorf("Objective: want %q, got %q", "Add login", got.Objective)
	}
}

func TestListPlans(t *testing.T) {
	pid := "proj-list"
	ensureProject(t, pid)
	if _, err := CreatePlan(pid, "Plan Alpha"); err != nil {
		t.Fatalf("CreatePlan Alpha: %v", err)
	}
	if _, err := CreatePlan(pid, "Plan Beta"); err != nil {
		t.Fatalf("CreatePlan Beta: %v", err)
	}

	plans, err := ListPlans(pid)
	if err != nil {
		t.Fatalf("ListPlans: %v", err)
	}
	if len(plans) < 2 {
		t.Errorf("want >= 2 plans for %q, got %d", pid, len(plans))
	}
	for _, pl := range plans {
		if pl.ProjectID != pid {
			t.Errorf("ListPlans returned wrong project_id %q", pl.ProjectID)
		}
	}
}

func TestSetPlanStatus(t *testing.T) {
	ensureProject(t, "proj-status")
	p, err := CreatePlan("proj-status", "Status test plan")
	if err != nil {
		t.Fatalf("CreatePlan: %v", err)
	}
	if err := SetPlanStatus(p.ID, "done"); err != nil {
		t.Fatalf("SetPlanStatus: %v", err)
	}
	got, err := GetPlan(p.ID)
	if err != nil {
		t.Fatalf("GetPlan: %v", err)
	}
	if got.Status != "done" {
		t.Errorf("want status 'done', got %q", got.Status)
	}
}

func TestGetPlanNotFound(t *testing.T) {
	_, err := GetPlan("nonexistent-plan-id")
	if err == nil {
		t.Error("GetPlan nonexistent: expected error, got nil")
	}
}

// ── Task ──────────────────────────────────────────────────────────────────────

func TestCreateAndGetTask(t *testing.T) {
	ensureProject(t, "proj-task")
	p, err := CreatePlan("proj-task", "Task parent plan")
	if err != nil {
		t.Fatalf("CreatePlan: %v", err)
	}

	task, err := CreateTask(p.ID, "Implement feature", "some description")
	if err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	if task.ID == "" {
		t.Error("task ID should be set after CreateTask")
	}
	if task.Status != "running" {
		t.Errorf("default status: want 'running', got %q", task.Status)
	}
	if task.PlanID != p.ID {
		t.Errorf("PlanID: want %q, got %q", p.ID, task.PlanID)
	}

	got, err := GetTask(task.ID)
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.Title != "Implement feature" {
		t.Errorf("Title: want %q, got %q", "Implement feature", got.Title)
	}
	if got.Description != "some description" {
		t.Errorf("Description: want %q, got %q", "some description", got.Description)
	}
}

func TestCreateTaskEmptyDescription(t *testing.T) {
	ensureProject(t, "proj-nodesc")
	p, err := CreatePlan("proj-nodesc", "No-desc plan")
	if err != nil {
		t.Fatalf("CreatePlan: %v", err)
	}
	task, err := CreateTask(p.ID, "Task without description", "")
	if err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	got, err := GetTask(task.ID)
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.Description != "" {
		t.Errorf("Description: want empty, got %q", got.Description)
	}
}

func TestListTasks(t *testing.T) {
	ensureProject(t, "proj-tasklist")
	p, err := CreatePlan("proj-tasklist", "Task list plan")
	if err != nil {
		t.Fatalf("CreatePlan: %v", err)
	}
	for _, title := range []string{"Task X", "Task Y", "Task Z"} {
		if _, err := CreateTask(p.ID, title, ""); err != nil {
			t.Fatalf("CreateTask %q: %v", title, err)
		}
	}

	tasks, err := ListTasks(p.ID)
	if err != nil {
		t.Fatalf("ListTasks: %v", err)
	}
	if len(tasks) != 3 {
		t.Errorf("want 3 tasks, got %d", len(tasks))
	}
	for _, tsk := range tasks {
		if tsk.PlanID != p.ID {
			t.Errorf("ListTasks returned wrong plan_id %q", tsk.PlanID)
		}
	}
}

func TestSetTaskStatus(t *testing.T) {
	ensureProject(t, "proj-taskstatus")
	p, err := CreatePlan("proj-taskstatus", "Task status plan")
	if err != nil {
		t.Fatalf("CreatePlan: %v", err)
	}
	task, err := CreateTask(p.ID, "Status task", "")
	if err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	if err := SetTaskStatus(task.ID, "done"); err != nil {
		t.Fatalf("SetTaskStatus: %v", err)
	}
	got, err := GetTask(task.ID)
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.Status != "done" {
		t.Errorf("want status 'done', got %q", got.Status)
	}
}

func TestGetTaskNotFound(t *testing.T) {
	_, err := GetTask("nonexistent-task-id")
	if err == nil {
		t.Error("GetTask nonexistent: expected error, got nil")
	}
}

// ── Run ───────────────────────────────────────────────────────────────────────

func makeRunParent(t *testing.T, projectID string) (planID, taskID string) {
	t.Helper()
	ensureProject(t, projectID)
	p, err := CreatePlan(projectID, "Run parent plan")
	if err != nil {
		t.Fatalf("CreatePlan: %v", err)
	}
	task, err := CreateTask(p.ID, "Run parent task", "")
	if err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	return p.ID, task.ID
}

func TestCreateAndGetRun(t *testing.T) {
	_, taskID := makeRunParent(t, "proj-run")

	run, err := CreateRun(taskID, "implementer", "alice", 1)
	if err != nil {
		t.Fatalf("CreateRun: %v", err)
	}
	if run.ID == "" {
		t.Error("run ID should be set after CreateRun")
	}
	if run.Status != "queued" {
		t.Errorf("default status: want 'queued', got %q", run.Status)
	}
	if run.AgentName != "alice" {
		t.Errorf("AgentName: want 'alice', got %q", run.AgentName)
	}
	if run.Attempt != 1 {
		t.Errorf("Attempt: want 1, got %d", run.Attempt)
	}

	got, err := GetRun(run.ID)
	if err != nil {
		t.Fatalf("GetRun: %v", err)
	}
	if got.TaskID != taskID {
		t.Errorf("TaskID: want %q, got %q", taskID, got.TaskID)
	}
	if got.Role != "implementer" {
		t.Errorf("Role: want 'implementer', got %q", got.Role)
	}
	if got.StartedAt != nil {
		t.Error("StartedAt should be nil for a freshly created run")
	}
}

func TestUpdateRun(t *testing.T) {
	_, taskID := makeRunParent(t, "proj-update-run")

	run, err := CreateRun(taskID, "implementer", "bob", 1)
	if err != nil {
		t.Fatalf("CreateRun: %v", err)
	}

	err = UpdateRun(run.ID, RunUpdates{
		Status:    "running",
		Branch:    "lt/plan1/task1/a1",
		StartedAt: "2024-01-01T00:00:00Z",
	})
	if err != nil {
		t.Fatalf("UpdateRun: %v", err)
	}

	got, err := GetRun(run.ID)
	if err != nil {
		t.Fatalf("GetRun after update: %v", err)
	}
	if got.Status != "running" {
		t.Errorf("Status: want 'running', got %q", got.Status)
	}
	if got.Branch != "lt/plan1/task1/a1" {
		t.Errorf("Branch: want 'lt/plan1/task1/a1', got %q", got.Branch)
	}
	if got.StartedAt == nil || *got.StartedAt != "2024-01-01T00:00:00Z" {
		t.Errorf("StartedAt not set correctly; got %v", got.StartedAt)
	}
}

func TestUpdateRunPartial(t *testing.T) {
	_, taskID := makeRunParent(t, "proj-partial-run")

	run, err := CreateRun(taskID, "reviewer", "carol", 2)
	if err != nil {
		t.Fatalf("CreateRun: %v", err)
	}

	// First update: set branch and started_at
	if err := UpdateRun(run.ID, RunUpdates{Branch: "lt/p/t/a2", StartedAt: "2024-06-01T10:00:00Z"}); err != nil {
		t.Fatalf("first UpdateRun: %v", err)
	}
	// Second update: set status and ended_at only (branch should be preserved)
	if err := UpdateRun(run.ID, RunUpdates{Status: "succeeded", EndedAt: "2024-06-01T10:05:00Z"}); err != nil {
		t.Fatalf("second UpdateRun: %v", err)
	}

	got, err := GetRun(run.ID)
	if err != nil {
		t.Fatalf("GetRun: %v", err)
	}
	if got.Status != "succeeded" {
		t.Errorf("Status: want 'succeeded', got %q", got.Status)
	}
	if got.Branch != "lt/p/t/a2" {
		t.Errorf("Branch preserved: want 'lt/p/t/a2', got %q", got.Branch)
	}
	if got.EndedAt == nil || *got.EndedAt != "2024-06-01T10:05:00Z" {
		t.Errorf("EndedAt not set; got %v", got.EndedAt)
	}
}

func TestListRuns(t *testing.T) {
	_, taskID := makeRunParent(t, "proj-list-runs")

	for i := 1; i <= 3; i++ {
		if _, err := CreateRun(taskID, "implementer", "dave", i); err != nil {
			t.Fatalf("CreateRun #%d: %v", i, err)
		}
	}

	runs, err := ListRuns(taskID)
	if err != nil {
		t.Fatalf("ListRuns: %v", err)
	}
	if len(runs) != 3 {
		t.Errorf("want 3 runs, got %d", len(runs))
	}
	// Verify ordered by attempt ASC
	for i, r := range runs {
		if r.Attempt != i+1 {
			t.Errorf("runs[%d] Attempt: want %d, got %d", i, i+1, r.Attempt)
		}
	}
}

func TestGetRunNotFound(t *testing.T) {
	_, err := GetRun("nonexistent-run-id")
	if err == nil {
		t.Error("GetRun nonexistent: expected error, got nil")
	}
}
