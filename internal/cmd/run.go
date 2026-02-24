package cmd

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/juhgiyo/loguetown/internal/config"
	"github.com/juhgiyo/loguetown/internal/embeddings"
	"github.com/juhgiyo/loguetown/internal/orchestrator"
	"github.com/juhgiyo/loguetown/internal/plans"
	"github.com/juhgiyo/loguetown/internal/runner"
	"github.com/juhgiyo/loguetown/internal/scheduler"
	"github.com/juhgiyo/loguetown/internal/tui"
	"github.com/spf13/cobra"
)

func newRunCmd() *cobra.Command {
	var dryRun bool

	cmd := &cobra.Command{
		Use:   "run <objective>",
		Short: "Non-interactive: plan an objective and execute all tasks automatically",
		Long: `lt run calls the Planner to decompose the objective into a task DAG,
shows the plan, then runs all tasks via the Scheduler.

Use --dry-run to see the plan without executing it.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			objective := args[0]
			projectPath := requireProject()

			cfg, err := config.LoadProject(projectPath)
			if err != nil {
				return fmt.Errorf("load project config: %w", err)
			}

			apiKey := cfg.Runner.APIKey
			model := cfg.Runner.Model
			if model == "" {
				model = "claude-opus-4-6"
			}

			tui.Info("Planning: " + objective)

			// Call planner to get task specs.
			specs, err := orchestrator.Plan(context.Background(), objective, apiKey, model)
			if err != nil {
				return fmt.Errorf("planner: %w", err)
			}

			// Print the plan.
			fmt.Println()
			tui.Header(fmt.Sprintf("Plan: %s", objective))
			rows := make([][]string, 0, len(specs))
			for i, s := range specs {
				deps := strings.Join(s.Deps, ", ")
				if deps == "" {
					deps = "—"
				}
				rows = append(rows, []string{
					s.LocalID,
					s.Title,
					deps,
					s.AgentName,
				})
				_ = i
			}
			tui.Table([]string{"ID", "Title", "Deps", "Agent"}, rows)
			fmt.Println()

			if dryRun {
				tui.Info("--dry-run: not executing.")
				return nil
			}

			// Persist plan and tasks.
			plan, err := plans.CreatePlan(cfg.Project.ID, objective)
			if err != nil {
				return fmt.Errorf("create plan: %w", err)
			}
			tui.Info(fmt.Sprintf("Plan ID: %s", plan.ID[:8]))

			// Map local IDs → DB task IDs for dep resolution.
			localToDBID := make(map[string]string, len(specs))
			taskIDs := make([]string, len(specs))
			for i, spec := range specs {
				t, err := plans.CreateTaskWithDeps(plan.ID, spec.Title, spec.Description, "", spec.AgentName)
				if err != nil {
					return fmt.Errorf("create task %q: %w", spec.Title, err)
				}
				localToDBID[spec.LocalID] = t.ID
				taskIDs[i] = t.ID
			}
			// Second pass: wire deps.
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
					_ = plans.SetTaskDeps(taskIDs[i], string(depsJSON))
				}
			}

			// Build runner + scheduler.
			var embProvider embeddings.Provider
			if ep, e := embeddings.New(cfg.Embeddings); e == nil {
				embProvider = ep
			}
			prov, err := runner.New(cfg.Runner)
			if err != nil {
				return fmt.Errorf("runner provider: %w", err)
			}
			r := &runner.Runner{
				ProjectPath:   projectPath,
				ProjectID:     cfg.Project.ID,
				ProjectName:   cfg.Project.Name,
				DefaultBranch: cfg.Project.DefaultBranch,
				EmbProvider:   embProvider,
				Provider:      prov,
				Cfg:           cfg.Runner,
				Checks:        cfg.Checks,
				PathRouting:   cfg.PathRouting,
			}
			sched := scheduler.New(r, cfg.Orchestrator)

			tui.Info(fmt.Sprintf("Executing %d tasks…", len(specs)))
			ctx := context.Background()
			if err := sched.RunAll(ctx, plan.ID); err != nil {
				return fmt.Errorf("run all: %w", err)
			}

			// Print final status.
			tasks, _ := plans.ListTasks(plan.ID)
			var statusRows [][]string
			for _, t := range tasks {
				statusRows = append(statusRows, []string{t.ID[:8], t.Title, t.Status})
			}
			fmt.Println()
			tui.Table([]string{"Task", "Title", "Status"}, statusRows)

			p, _ := plans.GetPlan(plan.ID)
			if p != nil && p.Status == "done" {
				tui.Success("All tasks completed successfully.")
			} else {
				tui.Warning("Some tasks failed. Use 'lt tasks list' for details.")
			}
			return nil
		},
	}

	cmd.Flags().BoolVar(&dryRun, "dry-run", false, "Show the plan without executing tasks")
	return cmd
}
