package cmd

import (
	"fmt"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/steveyegge/loguetown/internal/config"
	"github.com/steveyegge/loguetown/internal/embeddings"
	"github.com/steveyegge/loguetown/internal/skills"
	"github.com/steveyegge/loguetown/internal/tui"
)

func newSkillsCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "skills",
		Short: "Manage indexed skill files",
	}
	cmd.AddCommand(skillsReindexCmd())
	cmd.AddCommand(skillsSearchCmd())
	return cmd
}

func skillsReindexCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "reindex",
		Short: "Embed all skill files in .loguetown/skills/ and upsert into the DB",
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()
			cfg, err := config.LoadProject(projectPath)
			if err != nil {
				return fmt.Errorf("load project config: %w", err)
			}
			provider, err := embeddings.New(cfg.Embeddings)
			if err != nil {
				return err
			}
			skillsDir := filepath.Join(projectPath, ".loguetown", "skills")
			result, err := skills.Reindex(skillsDir, provider)
			if err != nil {
				return err
			}
			tui.Success(fmt.Sprintf(
				"Indexed %d chunks from %d files (%d skipped — content unchanged)",
				result.Chunks, result.Files, result.Skipped,
			))
			return nil
		},
	}
}

func skillsSearchCmd() *cobra.Command {
	var topK int
	var minSim float64

	cmd := &cobra.Command{
		Use:   "search <query>",
		Short: "Search indexed skill files by semantic similarity",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			query := joinStrings(args)
			projectPath := requireProject()
			cfg, err := config.LoadProject(projectPath)
			if err != nil {
				return fmt.Errorf("load project config: %w", err)
			}
			provider, err := embeddings.New(cfg.Embeddings)
			if err != nil {
				return err
			}
			results, err := skills.Search(query, provider, topK, float32(minSim))
			if err != nil {
				return err
			}
			if len(results) == 0 {
				tui.Info("No matching skill chunks found.")
				return nil
			}

			var rows [][]string
			for _, r := range results {
				rows = append(rows, []string{
					fmt.Sprintf("%.3f", r.Score),
					r.Role,
					r.Title,
					r.FilePath,
				})
			}
			tui.Table([]string{"Score", "Role", "Title", "File"}, rows)
			return nil
		},
	}

	cmd.Flags().IntVarP(&topK, "top", "k", 5, "Maximum number of results to return")
	cmd.Flags().Float64VarP(&minSim, "min-sim", "s", 0.3, "Minimum cosine similarity score (0-1)")
	return cmd
}
