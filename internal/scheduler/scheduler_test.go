package scheduler

import (
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/juhgiyo/loguetown/internal/config"
	"github.com/juhgiyo/loguetown/internal/plans"
	"github.com/juhgiyo/loguetown/internal/runner"
	"github.com/juhgiyo/loguetown/internal/storage"
)

// TestMain isolates the storage singleton in a temp home dir.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "scheduler-test-*")
	if err != nil {
		os.Exit(1)
	}
	defer os.RemoveAll(dir)
	os.Setenv("HOME", dir)
	os.Exit(m.Run())
}

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
		t.Fatalf("ensureProject: %v", err)
	}
}

// makeParent creates a project → plan → task chain for testing scheduler state.
func makeParent(t *testing.T, projectID string) (planID, taskID string) {
	t.Helper()
	ensureProject(t, projectID)
	plan, err := plans.CreatePlan(projectID, "test objective")
	if err != nil {
		t.Fatalf("CreatePlan: %v", err)
	}
	task, err := plans.CreateTaskWithDeps(plan.ID, "test task", "", "", "")
	if err != nil {
		t.Fatalf("CreateTaskWithDeps: %v", err)
	}
	return plan.ID, task.ID
}

// ── New / config defaults ─────────────────────────────────────────────────────

func TestNewDefaultConfig(t *testing.T) {
	s := New(nil, config.OrchestratorConfig{})
	if s.MaxParallel != 3 {
		t.Errorf("MaxParallel: want 3, got %d", s.MaxParallel)
	}
	if s.MaxFixAttempts != 2 {
		t.Errorf("MaxFixAttempts: want 2, got %d", s.MaxFixAttempts)
	}
	if s.PollInterval != 10*time.Second {
		t.Errorf("PollInterval: want 10s, got %v", s.PollInterval)
	}
}

func TestNewCustomConfig(t *testing.T) {
	s := New(nil, config.OrchestratorConfig{
		MaxParallel:     5,
		MaxFixAttempts:  4,
		PollIntervalSec: 30,
	})
	if s.MaxParallel != 5 {
		t.Errorf("MaxParallel: want 5, got %d", s.MaxParallel)
	}
	if s.MaxFixAttempts != 4 {
		t.Errorf("MaxFixAttempts: want 4, got %d", s.MaxFixAttempts)
	}
	if s.PollInterval != 30*time.Second {
		t.Errorf("PollInterval: want 30s, got %v", s.PollInterval)
	}
}

// ── Enqueue ───────────────────────────────────────────────────────────────────

func TestEnqueueAddsPlanID(t *testing.T) {
	s := New(nil, config.OrchestratorConfig{})
	s.Enqueue("plan-abc")
	s.mu.Lock()
	ids := s.planIDs
	s.mu.Unlock()
	if len(ids) != 1 || ids[0] != "plan-abc" {
		t.Errorf("planIDs: want ['plan-abc'], got %v", ids)
	}
}

func TestEnqueueIdempotent(t *testing.T) {
	s := New(nil, config.OrchestratorConfig{})
	s.Enqueue("plan-xyz")
	s.Enqueue("plan-xyz")
	s.mu.Lock()
	n := len(s.planIDs)
	s.mu.Unlock()
	if n != 1 {
		t.Errorf("Enqueue should be idempotent: want 1 entry, got %d", n)
	}
}

func TestEnqueueMultiplePlans(t *testing.T) {
	s := New(nil, config.OrchestratorConfig{})
	s.Enqueue("p1")
	s.Enqueue("p2")
	s.Enqueue("p3")
	s.mu.Lock()
	n := len(s.planIDs)
	s.mu.Unlock()
	if n != 3 {
		t.Errorf("want 3 plan IDs, got %d", n)
	}
}

// ── planDone ──────────────────────────────────────────────────────────────────

func TestPlanDoneAllDone(t *testing.T) {
	planID, taskID := makeParent(t, "proj-done")
	_ = plans.SetTaskStatus(taskID, "done")

	s := New(nil, config.OrchestratorConfig{})
	if !s.planDone(planID) {
		t.Error("planDone should return true when all tasks are 'done'")
	}
}

func TestPlanDoneAllFailed(t *testing.T) {
	planID, taskID := makeParent(t, "proj-fail")
	_ = plans.SetTaskStatus(taskID, "failed")

	s := New(nil, config.OrchestratorConfig{})
	if !s.planDone(planID) {
		t.Error("planDone should return true when all tasks are 'failed'")
	}
}

func TestPlanDoneStillRunning(t *testing.T) {
	planID, _ := makeParent(t, "proj-running")
	// task status is "todo" (default for CreateTaskWithDeps)

	s := New(nil, config.OrchestratorConfig{})
	if s.planDone(planID) {
		t.Error("planDone should return false when a task is still 'todo'")
	}
}

func TestPlanDoneMixedTerminal(t *testing.T) {
	ensureProject(t, "proj-mixed")
	plan, _ := plans.CreatePlan("proj-mixed", "mixed tasks")
	t1, _ := plans.CreateTaskWithDeps(plan.ID, "task 1", "", "", "")
	t2, _ := plans.CreateTaskWithDeps(plan.ID, "task 2", "", "", "")
	_ = plans.SetTaskStatus(t1.ID, "done")
	_ = plans.SetTaskStatus(t2.ID, "failed")

	s := New(nil, config.OrchestratorConfig{})
	if !s.planDone(plan.ID) {
		t.Error("planDone should return true when all tasks are in terminal states (done or failed)")
	}
}

func TestPlanDoneOneStillTodo(t *testing.T) {
	ensureProject(t, "proj-partial")
	plan, _ := plans.CreatePlan("proj-partial", "partial plan")
	t1, _ := plans.CreateTaskWithDeps(plan.ID, "done task", "", "", "")
	_, _ = plans.CreateTaskWithDeps(plan.ID, "pending task", "", "", "")
	_ = plans.SetTaskStatus(t1.ID, "done")
	// second task remains "todo"

	s := New(nil, config.OrchestratorConfig{})
	if s.planDone(plan.ID) {
		t.Error("planDone should return false when one task is still 'todo'")
	}
}

// ── finalizePlan ──────────────────────────────────────────────────────────────

func TestFinalizePlanSetsDone(t *testing.T) {
	planID, taskID := makeParent(t, "proj-finalize-done")
	_ = plans.SetTaskStatus(taskID, "done")

	s := New(nil, config.OrchestratorConfig{})
	s.Enqueue(planID)
	s.finalizePlan(planID)

	plan, err := plans.GetPlan(planID)
	if err != nil {
		t.Fatalf("GetPlan: %v", err)
	}
	if plan.Status != "done" {
		t.Errorf("plan.Status: want 'done', got %q", plan.Status)
	}

	// Plan should be removed from polling set.
	s.mu.Lock()
	ids := s.planIDs
	s.mu.Unlock()
	for _, id := range ids {
		if id == planID {
			t.Error("planID should be removed from planIDs after finalization")
		}
	}
}

func TestFinalizePlanSetsFailed(t *testing.T) {
	planID, taskID := makeParent(t, "proj-finalize-fail")
	_ = plans.SetTaskStatus(taskID, "failed")

	s := New(nil, config.OrchestratorConfig{})
	s.finalizePlan(planID)

	plan, _ := plans.GetPlan(planID)
	if plan.Status != "failed" {
		t.Errorf("plan.Status: want 'failed', got %q", plan.Status)
	}
}

// ── Start / Stop ──────────────────────────────────────────────────────────────

func TestStartStop(t *testing.T) {
	// Scheduler with a very long poll interval so it never actually ticks during the test.
	s := &Scheduler{
		Runner:         &runner.Runner{},
		MaxParallel:    1,
		MaxFixAttempts: 1,
		PollInterval:   24 * time.Hour,
		stopCh:         make(chan struct{}),
	}

	ctx := t.Context()
	s.Start(ctx)

	// Give the goroutine a moment to start.
	time.Sleep(10 * time.Millisecond)

	// Stop should return promptly (no active runners).
	done := make(chan struct{})
	go func() {
		s.Stop()
		close(done)
	}()
	select {
	case <-done:
		// OK
	case <-time.After(2 * time.Second):
		t.Error("Stop() took too long — possible goroutine leak")
	}
}
