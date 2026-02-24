package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"

	"github.com/steveyegge/loguetown/internal/checks"
	"github.com/steveyegge/loguetown/internal/config"
	"github.com/steveyegge/loguetown/internal/tui"
)

func newChecksCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "checks",
		Short: "Manage and run project check pipelines",
	}
	cmd.AddCommand(checksListCmd())
	cmd.AddCommand(checksRunCmd())
	return cmd
}

func checksListCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List configured check steps",
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()
			cfg, err := config.LoadProject(projectPath)
			if err != nil {
				return fmt.Errorf("load project config: %w", err)
			}
			if len(cfg.Checks) == 0 {
				tui.Info("No checks configured. Add a 'checks:' section to .loguetown/project.yaml.")
				return nil
			}

			var rows [][]string
			for _, step := range cfg.Checks {
				timeout := "60s (default)"
				if step.TimeoutSeconds > 0 {
					timeout = fmt.Sprintf("%ds", step.TimeoutSeconds)
				}
				onFail := step.OnFail
				if onFail == "" {
					onFail = "block"
				}
				rows = append(rows, []string{step.Name, step.Run, timeout, onFail})
			}
			tui.Table([]string{"Name", "Command", "Timeout", "OnFail"}, rows)
			return nil
		},
	}
}

func checksRunCmd() *cobra.Command {
	var baseSHA string

	cmd := &cobra.Command{
		Use:   "run [<check-name>...]",
		Short: "Execute check steps in the current working directory",
		Long: `Execute one or more check steps defined in .loguetown/project.yaml.
With no arguments, runs all configured checks in order.
Pass check names to run only those steps (e.g. lt checks run lint typecheck).`,
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()
			cfg, err := config.LoadProject(projectPath)
			if err != nil {
				return fmt.Errorf("load project config: %w", err)
			}
			if len(cfg.Checks) == 0 {
				tui.Info("No checks configured. Add a 'checks:' section to .loguetown/project.yaml.")
				return nil
			}

			// Filter to the requested step names, or run all.
			steps := cfg.Checks
			if len(args) > 0 {
				want := map[string]bool{}
				for _, name := range args {
					want[name] = true
				}
				var filtered []config.CheckStep
				for _, step := range cfg.Checks {
					if want[step.Name] {
						filtered = append(filtered, step)
					}
				}
				if len(filtered) == 0 {
					return fmt.Errorf("no matching checks found; available: %s",
						strings.Join(checkNames(cfg.Checks), ", "))
				}
				steps = filtered
			}

			// Artifact directory for this ad-hoc run.
			home, _ := os.UserHomeDir()
			artifactDir := filepath.Join(home, ".loguetown", "data", "checks-adhoc")

			// "manual" run — no real run ID; use a placeholder.
			const runID = "manual"
			const projectID = ""

			result := checks.RunPipeline(projectID, runID, steps, cfg.PathRouting, projectPath, artifactDir, baseSHA)

			// Print results.
			for _, r := range result.Results {
				switch {
				case r.Skipped:
					tui.Info(fmt.Sprintf("  SKIP  %s (path routing)", r.Name))
				case r.Passed:
					tui.Success(fmt.Sprintf("  PASS  %s (%.1fs)", r.Name, r.Duration.Seconds()))
				case !r.Blocking:
					tui.Warning(fmt.Sprintf("  WARN  %s (exit %d, %.1fs)", r.Name, r.ExitCode, r.Duration.Seconds()))
				default:
					tui.Error(fmt.Sprintf("  FAIL  %s (exit %d, %.1fs)", r.Name, r.ExitCode, r.Duration.Seconds()))
					if r.Stdout != "" {
						fmt.Println(r.Stdout)
					}
					if r.Stderr != "" {
						fmt.Println(r.Stderr)
					}
				}
				if r.ArtifactPath != "" && !r.Passed {
					tui.Info(fmt.Sprintf("         output saved: %s", r.ArtifactPath))
				}
			}

			if !result.Passed {
				return fmt.Errorf("check pipeline failed")
			}
			if len(result.Warnings) > 0 {
				tui.Warning(fmt.Sprintf("Completed with warnings: %s", strings.Join(result.Warnings, ", ")))
			} else {
				tui.Success("All checks passed.")
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&baseSHA, "base", "", "Base SHA for path routing (compare changed files since this commit)")
	return cmd
}

func checkNames(steps []config.CheckStep) []string {
	names := make([]string, len(steps))
	for i, s := range steps {
		names[i] = s.Name
	}
	return names
}
