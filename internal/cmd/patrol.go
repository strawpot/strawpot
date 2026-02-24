package cmd

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/juhgiyo/loguetown/internal/config"
	"github.com/juhgiyo/loguetown/internal/embeddings"
	"github.com/juhgiyo/loguetown/internal/plans"
	"github.com/juhgiyo/loguetown/internal/runner"
	"github.com/juhgiyo/loguetown/internal/scheduler"
	"github.com/juhgiyo/loguetown/internal/tui"
	"github.com/spf13/cobra"
)

func newPatrolCmd() *cobra.Command {
	var once bool

	cmd := &cobra.Command{
		Use:   "patrol",
		Short: "Resume in-flight plans and watch for new work",
		Long: `lt patrol recovers from a crashed scheduler and keeps plans running.

On startup it:
  1. Resets tasks stuck in "running" state back to "todo" (orphaned by a prior crash).
  2. Re-enqueues all plans that were in "running" state.
  3. Starts the scheduler to process work.

Without --once, it runs indefinitely until Ctrl+C, picking up any new plans
enqueued via 'lt chat' or 'lt run' in other sessions (the scheduler reads
directly from SQLite).

Use --once to perform a single scheduling pass and then exit — useful for
recovering a stalled plan in scripts or CI.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()

			cfg, err := config.LoadProject(projectPath)
			if err != nil {
				return fmt.Errorf("load project config: %w", err)
			}

			// Build embedding provider (best-effort).
			var embProvider embeddings.Provider
			if ep, e := embeddings.New(cfg.Embeddings); e == nil {
				embProvider = ep
			}

			// Build runner + scheduler.
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

			// 1. Reset orphaned tasks.
			if err := plans.ResetOrphanedTasks(cfg.Project.ID); err != nil {
				tui.Warning(fmt.Sprintf("Could not reset orphaned tasks: %v", err))
			} else {
				tui.Info("Reset orphaned running tasks to 'todo'.")
			}

			// 2. Re-enqueue plans that were active when the previous process died.
			running, err := plans.ListRunningPlans(cfg.Project.ID)
			if err != nil {
				tui.Warning(fmt.Sprintf("Could not list running plans: %v", err))
			}
			for _, p := range running {
				sched.Enqueue(p.ID)
			}
			if len(running) > 0 {
				tui.Info(fmt.Sprintf("Re-enqueued %d running plan(s).", len(running)))
			} else {
				tui.Info("No running plans found.")
			}

			// 3. Set up graceful shutdown.
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()

			sigCh := make(chan os.Signal, 1)
			signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
			go func() {
				<-sigCh
				fmt.Println("\nStopping patrol…")
				cancel()
			}()

			// 4. Run.
			sched.Start(ctx)

			if once {
				// Wait one full poll interval so the scheduler can fire at least once,
				// then give active runners a moment to finish.
				time.Sleep(sched.PollInterval + 500*time.Millisecond)
				sched.Stop()
				tui.Info("Patrol --once complete.")
			} else {
				tui.Info("Patrol loop running. Ctrl+C to stop.")
				<-ctx.Done()
				sched.Stop()
			}
			return nil
		},
	}

	cmd.Flags().BoolVar(&once, "once", false, "Perform a single scheduling pass then exit")
	return cmd
}
