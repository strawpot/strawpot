package cmd

import (
	"fmt"
	"os"
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
	var globalOnly bool
	var projectOnly bool
	var agentName string

	cmd := &cobra.Command{
		Use:   "reindex",
		Short: "Embed skill files and upsert into the DB (all scopes by default)",
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

			var total skills.IndexResult

			// Agent scope: .loguetown/skills/agents/<name>/
			// Indexed when --agent is set (unless --global is also set).
			if agentName != "" && !globalOnly && !projectOnly {
				agentDir := filepath.Join(projectPath, ".loguetown", "skills", "agents", agentName)
				if _, statErr := os.Stat(agentDir); statErr == nil {
					r, err := skills.Reindex(agentDir, "agent", agentName, provider)
					if err != nil {
						return fmt.Errorf("reindex agent skills: %w", err)
					}
					total.Files += r.Files
					total.Chunks += r.Chunks
					total.Skipped += r.Skipped
				} else {
					tui.Info(fmt.Sprintf("Agent skills directory not found: %s", agentDir))
				}
				tui.Success(fmt.Sprintf(
					"Indexed %d chunks from %d files (%d skipped — content unchanged)",
					total.Chunks, total.Files, total.Skipped,
				))
				return nil
			}

			// Global scope: ~/.loguetown/skills/global/
			if !projectOnly {
				home, _ := os.UserHomeDir()
				globalDir := filepath.Join(home, ".loguetown", "skills", "global")
				if _, statErr := os.Stat(globalDir); statErr == nil {
					r, err := skills.Reindex(globalDir, "global", "", provider)
					if err != nil {
						return fmt.Errorf("reindex global skills: %w", err)
					}
					total.Files += r.Files
					total.Chunks += r.Chunks
					total.Skipped += r.Skipped
				} else if globalOnly {
					tui.Info(fmt.Sprintf("Global skills directory not found: %s", globalDir))
					return nil
				}
			}

			// Project scope: .loguetown/skills/ (excludes agents/ subdirectory)
			if !globalOnly {
				skillsDir := filepath.Join(projectPath, ".loguetown", "skills")
				r, err := skills.Reindex(skillsDir, "project", "", provider)
				if err != nil {
					return fmt.Errorf("reindex project skills: %w", err)
				}
				total.Files += r.Files
				total.Chunks += r.Chunks
				total.Skipped += r.Skipped
			}

			tui.Success(fmt.Sprintf(
				"Indexed %d chunks from %d files (%d skipped — content unchanged)",
				total.Chunks, total.Files, total.Skipped,
			))
			return nil
		},
	}

	cmd.Flags().BoolVar(&globalOnly, "global", false, "Only reindex ~/.loguetown/skills/global/")
	cmd.Flags().BoolVar(&projectOnly, "project", false, "Only reindex .loguetown/skills/ (project scope)")
	cmd.Flags().StringVar(&agentName, "agent", "", "Only reindex .loguetown/skills/agents/<name>/ (agent scope)")
	return cmd
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
					r.Scope,
					r.Role,
					r.Title,
					r.FilePath,
				})
			}
			tui.Table([]string{"Score", "Scope", "Role", "Title", "File"}, rows)
			return nil
		},
	}

	cmd.Flags().IntVarP(&topK, "top", "k", 5, "Maximum number of results to return")
	cmd.Flags().Float64VarP(&minSim, "min-sim", "s", 0.3, "Minimum cosine similarity score (0-1)")
	return cmd
}
