package cmd

import (
	"github.com/spf13/cobra"
)

var rootCmd = &cobra.Command{
	Use:   "lt",
	Short: "Loguetown — local-first multi-agent coding assistant",
	Long: `Loguetown helps solo developers plan, execute, and review code changes
using specialized AI agents working in isolated git worktrees.

The CLI is the primary interface. Every operation is available here.
Open the GUI at any time with: lt gui`,
	SilenceUsage:  true,
	SilenceErrors: true,
}

func Execute() {
	cobra.CheckErr(rootCmd.Execute())
}

func init() {
	rootCmd.AddCommand(newInitCmd())
	rootCmd.AddCommand(newRoleCmd())
	rootCmd.AddCommand(newAgentCmd())
	rootCmd.AddCommand(newGuiCmd())
	rootCmd.AddCommand(newSkillsCmd())
	rootCmd.AddCommand(newMemoryCmd())
	rootCmd.AddCommand(newTasksCmd())
	rootCmd.AddCommand(newPlanCmd())
}
