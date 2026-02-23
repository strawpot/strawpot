package runner

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/steveyegge/loguetown/internal/agents"
	"github.com/steveyegge/loguetown/internal/chronicle"
	"github.com/steveyegge/loguetown/internal/config"
	"github.com/steveyegge/loguetown/internal/embeddings"
	"github.com/steveyegge/loguetown/internal/memory"
	"github.com/steveyegge/loguetown/internal/plans"
	"github.com/steveyegge/loguetown/internal/session"
	"github.com/steveyegge/loguetown/internal/worktree"
)

// Runner orchestrates a single agent run: session building, worktree lifecycle,
// provider execution, episodic memory proposal, and chronicle events.
type Runner struct {
	ProjectPath   string
	ProjectID     string
	ProjectName   string
	DefaultBranch string
	EmbProvider   embeddings.Provider // may be nil
	Provider      Provider
	Cfg           config.RunnerConfig
}

// RunRequest is the input to Runner.Run.
type RunRequest struct {
	PlanID      string
	TaskID      string
	AgentName   string
	Task        string // natural language task description
	BaseSHA     string // empty = use current HEAD
	NoWorktree  bool   // skip git worktree (run in repo root)
	Attempt     int
}

// RunResult is returned by Runner.Run.
type RunResult struct {
	RunID   string
	Success bool
	Output  string
	Error   string
}

// Run executes a full agent run lifecycle.
func (r *Runner) Run(ctx context.Context, req RunRequest) (RunResult, error) {
	if req.Attempt <= 0 {
		req.Attempt = 1
	}

	// Load the agent charter.
	charter, err := agents.Load(req.AgentName, r.ProjectPath)
	if err != nil {
		return RunResult{}, fmt.Errorf("load agent %q: %w", req.AgentName, err)
	}

	// Create the run record.
	run, err := plans.CreateRun(req.TaskID, charter.Role, req.AgentName, req.Attempt)
	if err != nil {
		return RunResult{}, fmt.Errorf("create run record: %w", err)
	}

	// Emit RUN_QUEUED.
	chronicle.Emit(r.ProjectID, "system", "RUN_QUEUED", map[string]interface{}{
		"run_id":     run.ID,
		"task_id":    req.TaskID,
		"plan_id":    req.PlanID,
		"agent_name": req.AgentName,
		"role":       charter.Role,
		"attempt":    req.Attempt,
	})

	// Determine branch name.
	branch := fmt.Sprintf("lt/%s/%s/a%d", shortID(req.PlanID), shortID(req.TaskID), req.Attempt)

	// Get base SHA.
	baseSHA := req.BaseSHA
	if baseSHA == "" {
		baseSHA, _ = worktree.CurrentSHA(r.ProjectPath)
	}

	// Build session (system prompt).
	sesCfg := session.Config{
		SkillTopK:     5,
		SkillMinSim:   0.2,
		MemoryTopK:    5,
		MemoryMinSim:  0.3,
		WorkDir:       r.ProjectPath,
		ProjectName:   r.ProjectName,
		DefaultBranch: r.DefaultBranch,
		Branch:        branch,
	}
	sess, err := session.Build(charter, req.Task, sesCfg, r.EmbProvider)
	if err != nil {
		return RunResult{}, fmt.Errorf("build session: %w", err)
	}

	// Create worktree (unless skipped).
	workDir := r.ProjectPath
	if !req.NoWorktree {
		home, _ := os.UserHomeDir()
		wtPath := filepath.Join(home, ".loguetown", "data", "projects", r.ProjectID, "worktrees", run.ID)
		sesCfg.WorkDir = wtPath
		sess.SystemPrompt = rebuildWithWorkDir(sess.SystemPrompt, wtPath)

		if _, err := worktree.Create(r.ProjectPath, wtPath, branch, baseSHA); err != nil {
			return RunResult{}, fmt.Errorf("create worktree: %w", err)
		}
		workDir = wtPath

		chronicle.Emit(r.ProjectID, "system", "WORKTREE_CREATED", map[string]interface{}{
			"run_id":        run.ID,
			"worktree_path": wtPath,
			"branch":        branch,
			"base_sha":      baseSHA,
		})
	}

	// Update run record: running.
	now := time.Now().UTC().Format(time.RFC3339)
	plans.UpdateRun(run.ID, plans.RunUpdates{
		Status:       "running",
		WorktreePath: workDir,
		Branch:       branch,
		BaseSHA:      baseSHA,
		StartedAt:    now,
	})

	// Emit RUN_STARTED.
	chronicle.Emit(r.ProjectID, fmt.Sprintf("agent:%s/%s", charter.Role, req.AgentName), "RUN_STARTED", map[string]interface{}{
		"run_id":      run.ID,
		"task_id":     req.TaskID,
		"work_dir":    workDir,
		"skills_used": sess.SkillsUsed,
		"memory_used": sess.MemoryUsed,
	})

	// Build allowlist from resolved tools.
	var allowlist []string
	if charter.ResolvedTools != nil {
		allowlist = charter.ResolvedTools.BashAllowlist
	}

	// Execute via provider.
	execReq := ExecuteRequest{
		SystemPrompt:  sess.SystemPrompt,
		Task:          req.Task,
		WorkDir:       workDir,
		MaxTurns:      r.Cfg.MaxTurns,
		BashAllowlist: allowlist,
		APIKey:        r.Cfg.APIKey,
		Model:         r.Cfg.Model,
	}
	execResult, execErr := r.Provider.Execute(ctx, execReq)

	// Get HEAD SHA after execution.
	headSHA, _ := worktree.HeadSHA(workDir)

	// Cleanup worktree.
	if !req.NoWorktree {
		worktree.Remove(r.ProjectPath, workDir, branch)
	}

	// Update run record with final state.
	ended := time.Now().UTC().Format(time.RFC3339)
	status := "succeeded"
	if execErr != nil || !execResult.Success {
		status = "failed"
	}
	plans.UpdateRun(run.ID, plans.RunUpdates{
		Status:  status,
		HeadSHA: headSHA,
		EndedAt: ended,
	})

	actor := fmt.Sprintf("agent:%s/%s", charter.Role, req.AgentName)
	if execErr != nil {
		chronicle.Emit(r.ProjectID, actor, "RUN_FAILED", map[string]interface{}{
			"run_id":  run.ID,
			"task_id": req.TaskID,
			"error":   execErr.Error(),
		})
		return RunResult{RunID: run.ID, Success: false, Error: execErr.Error()}, nil
	}
	if !execResult.Success {
		chronicle.Emit(r.ProjectID, actor, "RUN_FAILED", map[string]interface{}{
			"run_id":  run.ID,
			"task_id": req.TaskID,
			"error":   execResult.Error,
		})
		return RunResult{RunID: run.ID, Success: false, Output: execResult.Output, Error: execResult.Error}, nil
	}

	// Propose episodic memory.
	go r.proposeEpisodic(charter, req, run.ID, execResult.Output)

	chronicle.Emit(r.ProjectID, actor, "RUN_SUCCEEDED", map[string]interface{}{
		"run_id":   run.ID,
		"task_id":  req.TaskID,
		"head_sha": headSHA,
	})

	return RunResult{RunID: run.ID, Success: true, Output: execResult.Output}, nil
}

// proposeEpisodic asks the model to reflect on the run and saves a proposed
// episodic memory chunk. Runs asynchronously (best-effort).
func (r *Runner) proposeEpisodic(charter *agents.Charter, req RunRequest, runID, output string) {
	reflectionPrompt := fmt.Sprintf(
		"You just completed this task:\n\n%s\n\nOutput summary:\n%s\n\n"+
			"In 2-4 sentences, what did you learn that would help a future agent with similar tasks? "+
			"Focus on mistakes made, patterns discovered, or important decisions. Be specific and actionable.",
		req.Task, truncate(output, 500),
	)

	execReq := ExecuteRequest{
		Task:    reflectionPrompt,
		WorkDir: r.ProjectPath,
		APIKey:  r.Cfg.APIKey,
		Model:   r.Cfg.Model,
	}
	result, err := r.Provider.Execute(context.Background(), execReq)
	if err != nil || !result.Success || result.Output == "" {
		return
	}

	chunk := &memory.Chunk{
		AgentName: charter.Name,
		Layer:     "episodic",
		ProjectID: r.ProjectID,
		FilePath:  fmt.Sprintf("memory/%s/episodic/run-%s.md", charter.Name, shortID(runID)),
		Title:     truncate(req.Task, 60),
		Content:   result.Output,
		Status:    "proposed",
	}
	memory.Save(chunk)

	chronicle.Emit(r.ProjectID, fmt.Sprintf("agent:%s/%s", charter.Role, charter.Name),
		"MEMORY_PROPOSED", map[string]interface{}{
			"chunk_id": chunk.ID,
			"layer":    "episodic",
			"run_id":   runID,
		})
}

// shortID returns the first 8 characters of an ID.
func shortID(id string) string {
	if len(id) > 8 {
		return id[:8]
	}
	return id
}

// truncate caps a string at n characters.
func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}

// rebuildWithWorkDir replaces the WorkDir placeholder in an already-built prompt.
func rebuildWithWorkDir(prompt, newDir string) string {
	return strings.ReplaceAll(prompt, "Working directory: `"+"`", "Working directory: `"+newDir+"`")
}
