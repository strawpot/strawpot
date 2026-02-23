package cmd

import (
	"fmt"

	"github.com/spf13/cobra"
	"github.com/steveyegge/loguetown/internal/config"
	"github.com/steveyegge/loguetown/internal/plans"
	"github.com/steveyegge/loguetown/internal/tui"
)

func newTasksCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "tasks",
		Short: "Manage tasks",
	}
	cmd.AddCommand(tasksListCmd())
	cmd.AddCommand(tasksShowCmd())
	return cmd
}

func tasksListCmd() *cobra.Command {
	var planID string

	cmd := &cobra.Command{
		Use:   "list",
		Short: "List tasks (most recent plan by default)",
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()

			if planID == "" {
				cfg, err := config.LoadProject(projectPath)
				if err != nil {
					return fmt.Errorf("load project config: %w", err)
				}
				allPlans, err := plans.ListPlans(cfg.Project.ID)
				if err != nil {
					return err
				}
				if len(allPlans) == 0 {
					tui.Info("No plans found. Run 'lt agent spawn' to create one.")
					return nil
				}
				planID = allPlans[0].ID
			}

			tasks, err := plans.ListTasks(planID)
			if err != nil {
				return err
			}
			if len(tasks) == 0 {
				tui.Info("No tasks in this plan.")
				return nil
			}

			var rows [][]string
			for _, t := range tasks {
				rows = append(rows, []string{
					t.ID[:8],
					t.Status,
					t.Title,
					t.CreatedAt[:16],
				})
			}
			tui.Table([]string{"ID", "Status", "Title", "Created"}, rows)
			return nil
		},
	}

	cmd.Flags().StringVar(&planID, "plan", "", "Plan ID (default: most recent plan)")
	return cmd
}

func tasksShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show <id>",
		Short: "Show full task details including runs",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := plans.GetTask(args[0])
			if err != nil {
				return err
			}

			tui.Header(fmt.Sprintf("Task: %s", t.ID[:8]))
			tui.KeyValue([][2]string{
				{"ID", t.ID},
				{"Plan", t.PlanID},
				{"Status", t.Status},
				{"Title", t.Title},
				{"Created", t.CreatedAt},
			})

			if t.Description != "" {
				fmt.Println()
				fmt.Println(t.Description)
			}

			runs, err := plans.ListRuns(t.ID)
			if err != nil || len(runs) == 0 {
				return nil
			}

			fmt.Println()
			var rows [][]string
			for _, r := range runs {
				started := "—"
				if r.StartedAt != nil {
					started = (*r.StartedAt)[:16]
				}
				rows = append(rows, []string{
					r.ID[:8],
					fmt.Sprintf("%d", r.Attempt),
					r.Role,
					r.AgentName,
					r.Status,
					started,
				})
			}
			tui.Table([]string{"Run ID", "Attempt", "Role", "Agent", "Status", "Started"}, rows)
			return nil
		},
	}
}
