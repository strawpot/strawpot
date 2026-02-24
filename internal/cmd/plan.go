package cmd

import (
	"fmt"

	"github.com/juhgiyo/loguetown/internal/config"
	"github.com/juhgiyo/loguetown/internal/plans"
	"github.com/juhgiyo/loguetown/internal/tui"
	"github.com/spf13/cobra"
)

func newPlanCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "plan",
		Short: "View plans",
	}
	cmd.AddCommand(planListCmd())
	cmd.AddCommand(planShowCmd())
	return cmd
}

func planListCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List all plans for the current project",
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()
			cfg, err := config.LoadProject(projectPath)
			if err != nil {
				return fmt.Errorf("load project config: %w", err)
			}

			allPlans, err := plans.ListPlans(cfg.Project.ID)
			if err != nil {
				return err
			}
			if len(allPlans) == 0 {
				tui.Info("No plans found. Run 'lt agent spawn <name> \"task\"' to create one.")
				return nil
			}

			var rows [][]string
			for _, p := range allPlans {
				rows = append(rows, []string{
					p.ID[:8],
					p.Status,
					p.Objective,
					p.CreatedAt[:16],
				})
			}
			tui.Table([]string{"ID", "Status", "Objective", "Created"}, rows)
			return nil
		},
	}
}

func planShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show <id>",
		Short: "Show plan details with task breakdown",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			p, err := plans.GetPlan(args[0])
			if err != nil {
				return err
			}

			tui.Header(fmt.Sprintf("Plan: %s", p.ID[:8]))
			tui.KeyValue([][2]string{
				{"ID", p.ID},
				{"Status", p.Status},
				{"Objective", p.Objective},
				{"Created", p.CreatedAt},
			})

			tasks, err := plans.ListTasks(p.ID)
			if err != nil || len(tasks) == 0 {
				return nil
			}

			fmt.Println()
			var rows [][]string
			for _, t := range tasks {
				rows = append(rows, []string{
					t.ID[:8],
					t.Status,
					t.Title,
				})
			}
			tui.Table([]string{"Task ID", "Status", "Title"}, rows)
			return nil
		},
	}
}
