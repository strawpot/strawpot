package cmd

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/steveyegge/loguetown/internal/chronicle"
	"github.com/steveyegge/loguetown/internal/config"
	"github.com/steveyegge/loguetown/internal/memory"
	"github.com/steveyegge/loguetown/internal/tui"
)

func newMemoryCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "memory",
		Short: "Manage memory chunks",
	}
	cmd.AddCommand(memoryListCmd())
	cmd.AddCommand(memoryShowCmd())
	cmd.AddCommand(memoryPromoteCmd())
	cmd.AddCommand(memoryRejectCmd())
	return cmd
}

func memoryListCmd() *cobra.Command {
	var layer, agent, status string

	cmd := &cobra.Command{
		Use:   "list",
		Short: "List memory chunks",
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()
			cfg, err := config.LoadProject(projectPath)
			if err != nil {
				return fmt.Errorf("load project config: %w", err)
			}
			chunks, err := memory.List(layer, agent, cfg.Project.ID, status)
			if err != nil {
				return err
			}
			if len(chunks) == 0 {
				tui.Info("No memory chunks found.")
				return nil
			}

			var rows [][]string
			for _, c := range chunks {
				rows = append(rows, []string{
					c.ID[:8],
					c.AgentName,
					c.Layer,
					c.Status,
					c.Title,
					c.CreatedAt[:10],
				})
			}
			tui.Table([]string{"ID", "Agent", "Layer", "Status", "Title", "Date"}, rows)
			return nil
		},
	}

	cmd.Flags().StringVar(&layer, "layer", "", "Filter by layer (episodic|semantic_local|semantic_global|working)")
	cmd.Flags().StringVar(&agent, "agent", "", "Filter by agent name")
	cmd.Flags().StringVar(&status, "status", "", "Filter by status (proposed|approved|rejected)")
	return cmd
}

func memoryShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show <id>",
		Short: "Print full content of a memory chunk",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := memory.Get(args[0])
			if err != nil {
				return err
			}
			tui.Header(fmt.Sprintf("Memory: %s", c.ID[:8]))
			tui.KeyValue([][2]string{
				{"ID", c.ID},
				{"Agent", c.AgentName},
				{"Layer", c.Layer},
				{"Status", c.Status},
				{"Title", c.Title},
				{"File", c.FilePath},
				{"Created", c.CreatedAt},
			})
			if c.Content != "" {
				fmt.Println()
				fmt.Println(c.Content)
			}
			if c.RejectionReason != "" {
				fmt.Println()
				tui.Warning("Rejection reason: " + c.RejectionReason)
			}
			return nil
		},
	}
}

func memoryPromoteCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "promote <id>",
		Short: "Approve a proposed memory chunk",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id := args[0]
			if err := memory.SetStatus(id, "approved", ""); err != nil {
				return err
			}
			projectPath := requireProject()
			cfg, _ := config.LoadProject(projectPath)
			_, _ = chronicle.Emit(cfg.Project.ID, "operator", "MEMORY_PROMOTED",
				map[string]interface{}{"chunk_id": id})
			tui.Success(fmt.Sprintf("Memory chunk %s promoted.", id[:8]))
			return nil
		},
	}
}

func memoryRejectCmd() *cobra.Command {
	var reason string

	cmd := &cobra.Command{
		Use:   "reject <id>",
		Short: "Reject a proposed memory chunk",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id := args[0]
			if err := memory.SetStatus(id, "rejected", reason); err != nil {
				return err
			}
			projectPath := requireProject()
			cfg, _ := config.LoadProject(projectPath)
			_, _ = chronicle.Emit(cfg.Project.ID, "operator", "MEMORY_REJECTED",
				map[string]interface{}{"chunk_id": id, "reason": reason})
			tui.Success(fmt.Sprintf("Memory chunk %s rejected.", id[:8]))
			return nil
		},
	}

	cmd.Flags().StringVar(&reason, "reason", "", "Reason for rejection")
	return cmd
}
