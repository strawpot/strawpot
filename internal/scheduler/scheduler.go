// Package scheduler provides a background goroutine that polls SQLite for
// unblocked tasks and dispatches them to runner.Runner. It implements a simple
// Implementer → retry pipeline with a bounded fix-attempt cap.
package scheduler

import (
	"context"
	"sync"
	"time"

	"github.com/juhgiyo/loguetown/internal/agents"
	"github.com/juhgiyo/loguetown/internal/chronicle"
	"github.com/juhgiyo/loguetown/internal/config"
	"github.com/juhgiyo/loguetown/internal/dispatch"
	"github.com/juhgiyo/loguetown/internal/plans"
	"github.com/juhgiyo/loguetown/internal/runner"
)

// Scheduler polls SQLite for ready tasks and spawns runner.Runner goroutines.
type Scheduler struct {
	Runner         *runner.Runner
	MaxParallel    int
	MaxFixAttempts int
	PollInterval   time.Duration

	mu      sync.Mutex
	planIDs []string
	active  int
	stopCh  chan struct{}
	wg      sync.WaitGroup
}

// New creates a Scheduler from a Runner and orchestrator config.
func New(r *runner.Runner, cfg config.OrchestratorConfig) *Scheduler {
	maxParallel := cfg.MaxParallel
	if maxParallel <= 0 {
		maxParallel = 3
	}
	maxFix := cfg.MaxFixAttempts
	if maxFix <= 0 {
		maxFix = 2
	}
	pollSec := cfg.PollIntervalSec
	if pollSec <= 0 {
		pollSec = 10
	}
	return &Scheduler{
		Runner:         r,
		MaxParallel:    maxParallel,
		MaxFixAttempts: maxFix,
		PollInterval:   time.Duration(pollSec) * time.Second,
		stopCh:         make(chan struct{}),
	}
}

// Enqueue adds a plan to the set of plans the scheduler will poll.
func (s *Scheduler) Enqueue(planID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, id := range s.planIDs {
		if id == planID {
			return // already queued
		}
	}
	s.planIDs = append(s.planIDs, planID)
}

// Start launches the background polling goroutine. Non-blocking.
func (s *Scheduler) Start(ctx context.Context) {
	go s.loop(ctx)
}

// Stop signals the polling goroutine to stop and waits for all active runners.
func (s *Scheduler) Stop() {
	close(s.stopCh)
	s.wg.Wait()
}

// RunAll enqueues planID and blocks until every task in that plan reaches a
// terminal state (done or failed). Suitable for non-interactive `lt run`.
func (s *Scheduler) RunAll(ctx context.Context, planID string) error {
	s.Enqueue(planID)

	ticker := time.NewTicker(s.PollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			s.tick(ctx)
			if s.planDone(planID) {
				return nil
			}
		}
	}
}

// loop is the background polling goroutine.
func (s *Scheduler) loop(ctx context.Context) {
	ticker := time.NewTicker(s.PollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-s.stopCh:
			return
		case <-ctx.Done():
			return
		case <-ticker.C:
			s.tick(ctx)
		}
	}
}

// tick performs one scheduling cycle: find ready tasks and spawn runners.
func (s *Scheduler) tick(ctx context.Context) {
	s.mu.Lock()
	planIDs := make([]string, len(s.planIDs))
	copy(planIDs, s.planIDs)
	s.mu.Unlock()

	for _, planID := range planIDs {
		if s.planDone(planID) {
			s.finalizePlan(planID)
			continue
		}

		ready, err := plans.ListReadyTasks(planID)
		if err != nil {
			continue
		}

		for _, task := range ready {
			s.mu.Lock()
			canSpawn := s.active < s.MaxParallel
			if canSpawn {
				s.active++
			}
			s.mu.Unlock()

			if !canSpawn {
				break
			}

			// Mark task as running before spawning so ListReadyTasks won't
			// return it again on the next tick.
			_ = plans.SetTaskStatus(task.ID, "running")

			s.wg.Add(1)
			go func(t plans.Task) {
				defer s.wg.Done()
				defer func() {
					s.mu.Lock()
					s.active--
					s.mu.Unlock()
				}()
				s.runTask(ctx, planID, t, 1)
			}(task)
		}
	}
}

// runTask executes one task attempt and handles retries up to MaxFixAttempts.
func (s *Scheduler) runTask(ctx context.Context, planID string, task plans.Task, attempt int) {
	agentName := task.AgentName
	if agentName == "" {
		// Pick the first available agent in the project.
		names, _ := agents.List(s.Runner.ProjectPath)
		if len(names) > 0 {
			agentName = names[0]
		}
	}
	if agentName == "" {
		_ = plans.SetTaskStatus(task.ID, "failed")
		chronicle.Emit(s.Runner.ProjectID, "scheduler", "TASK_NO_AGENT", map[string]interface{}{
			"task_id": task.ID,
			"title":   task.Title,
		})
		return
	}

	result, err := s.Runner.Run(ctx, runner.RunRequest{
		PlanID:    planID,
		TaskID:    task.ID,
		AgentName: agentName,
		Task:      task.Title + "\n\n" + task.Description,
		Attempt:   attempt,
	})

	if err == nil && result.Success {
		_ = plans.SetTaskStatus(task.ID, "done")
		_ = dispatch.Send("scheduler", "orchestrator", dispatch.TypeTaskUnblocked,
			planID, task.ID, result.RunID, map[string]string{"title": task.Title})
		return
	}

	// Failure — retry if under the cap.
	if attempt < s.MaxFixAttempts {
		_ = plans.SetTaskStatus(task.ID, "todo")
		s.mu.Lock()
		s.active++
		s.mu.Unlock()
		s.wg.Add(1)
		go func() {
			defer s.wg.Done()
			defer func() {
				s.mu.Lock()
				s.active--
				s.mu.Unlock()
			}()
			s.runTask(ctx, planID, task, attempt+1)
		}()
		return
	}

	// Exhausted retries.
	_ = plans.SetTaskStatus(task.ID, "failed")
	chronicle.Emit(s.Runner.ProjectID, "scheduler", "TASK_FAILED", map[string]interface{}{
		"task_id":  task.ID,
		"title":    task.Title,
		"attempts": attempt,
	})
}

// planDone returns true when all tasks in the plan are in a terminal state.
func (s *Scheduler) planDone(planID string) bool {
	tasks, err := plans.ListTasks(planID)
	if err != nil || len(tasks) == 0 {
		return false
	}
	for _, t := range tasks {
		if t.Status != "done" && t.Status != "failed" {
			return false
		}
	}
	return true
}

// finalizePlan sets the plan's terminal status based on its tasks.
func (s *Scheduler) finalizePlan(planID string) {
	tasks, err := plans.ListTasks(planID)
	if err != nil {
		return
	}
	status := "done"
	for _, t := range tasks {
		if t.Status == "failed" {
			status = "failed"
			break
		}
	}
	_ = plans.SetPlanStatus(planID, status)

	// Remove from polling set.
	s.mu.Lock()
	filtered := s.planIDs[:0]
	for _, id := range s.planIDs {
		if id != planID {
			filtered = append(filtered, id)
		}
	}
	s.planIDs = filtered
	s.mu.Unlock()
}
