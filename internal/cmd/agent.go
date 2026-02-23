package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
	"github.com/steveyegge/loguetown/internal/agents"
	"github.com/steveyegge/loguetown/internal/roles"
	"github.com/steveyegge/loguetown/internal/tui"
)

func newAgentCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "agent",
		Short: "Manage agents",
	}

	cmd.AddCommand(agentListCmd())
	cmd.AddCommand(agentShowCmd())
	cmd.AddCommand(agentCreateCmd())
	cmd.AddCommand(agentEditCmd())
	return cmd
}

func agentListCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List all agents with role and model info",
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()
			names, err := agents.List(projectPath)
			if err != nil {
				return err
			}
			if len(names) == 0 {
				tui.Info("No agents found.")
				tui.Info("Create one: lt agent create --name charlie --role implementer")
				return nil
			}

			var rows [][]string
			for _, name := range names {
				c, err := agents.Load(name, projectPath)
				if err != nil {
					rows = append(rows, []string{name, "(invalid charter)", "", ""})
					continue
				}
				model := ""
				if c.ResolvedModel != nil {
					model = fmt.Sprintf("%s/%s", c.ResolvedModel.Provider, c.ResolvedModel.ID)
				}
				rows = append(rows, []string{
					name,
					c.Role,
					model,
					fmt.Sprintf("%d", len(c.ResolvedSkills)),
				})
			}

			tui.Table([]string{"Name", "Role", "Model", "Skills"}, rows)
			return nil
		},
	}
}

func agentShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show <name>",
		Short: "Print full resolved Charter with inherited role defaults",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			name := args[0]
			projectPath := requireProject()

			if !agents.Exists(name, projectPath) {
				return fmt.Errorf("agent %q not found", name)
			}

			c, err := agents.Load(name, projectPath)
			if err != nil {
				return err
			}

			tui.Header(fmt.Sprintf("Agent: %s", name))

			tools := ""
			if c.ResolvedTools != nil {
				tools = joinStrings(c.ResolvedTools.Allowed)
			}
			model := ""
			if c.ResolvedModel != nil {
				model = fmt.Sprintf("%s/%s", c.ResolvedModel.Provider, c.ResolvedModel.ID)
			}

			tui.KeyValue([][2]string{
				{"Name", c.Name},
				{"Role", c.Role},
				{"Model", model},
				{"Tools", tools},
			})

			if len(c.ResolvedSkills) > 0 {
				fmt.Println()
				fmt.Println("  \033[1mResolved skills:\033[0m")
				for _, s := range c.ResolvedSkills {
					fmt.Printf("    - %s\n", s)
				}
			}

			if len(c.ExtraSkills) > 0 {
				fmt.Println()
				fmt.Println("  \033[1mExtra skills (Charter-level):\033[0m")
				for _, s := range c.ExtraSkills {
					fmt.Printf("    - %s\n", s)
				}
			}

			if c.ResolvedTools != nil && len(c.ResolvedTools.BashAllowlist) > 0 {
				fmt.Println()
				fmt.Println("  \033[1mBash allowlist:\033[0m")
				for _, p := range c.ResolvedTools.BashAllowlist {
					fmt.Printf("    - %s\n", p)
				}
			}

			if c.ResolvedMemory != nil {
				fmt.Println()
				fmt.Printf("  \033[1mMemory:\033[0m provider=%s, max_tokens=%d, layers=[%s]\n",
					c.ResolvedMemory.Provider,
					c.ResolvedMemory.MaxTokensInjected,
					joinStrings(c.ResolvedMemory.Layers),
				)
			}

			return nil
		},
	}
}

func agentCreateCmd() *cobra.Command {
	var name, role, modelID string

	cmd := &cobra.Command{
		Use:   "create",
		Short: "Scaffold a new agent Charter YAML",
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()

			if agents.Exists(name, projectPath) {
				tui.Warning(fmt.Sprintf("Agent %q already exists. Use 'lt agent edit %s' to modify it.", name, name))
				return nil
			}

			if !roles.Exists(role, projectPath) {
				return fmt.Errorf("role %q not found; available roles: lt role list", role)
			}

			path := agents.FilePath(name, projectPath)
			if err := os.WriteFile(path, []byte(agents.Template(name, role, modelID)), 0o644); err != nil {
				return err
			}

			tui.Success(fmt.Sprintf("Created .loguetown/agents/%s.yaml (role: %s)", name, role))

			// Show resolved summary
			if c, err := agents.Load(name, projectPath); err == nil {
				m := ""
				if c.ResolvedModel != nil {
					m = fmt.Sprintf("%s/%s", c.ResolvedModel.Provider, c.ResolvedModel.ID)
				}
				tui.Info(fmt.Sprintf("Model: %s | Skills: %d", m, len(c.ResolvedSkills)))
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&name, "name", "", "Agent name (required)")
	cmd.Flags().StringVar(&role, "role", "", "Role to base this agent on (required)")
	cmd.Flags().StringVar(&modelID, "model", "", "Override model ID (e.g. claude-sonnet-4-6)")
	_ = cmd.MarkFlagRequired("name")
	_ = cmd.MarkFlagRequired("role")
	return cmd
}

func agentEditCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "edit <name>",
		Short: "Open agent Charter in $EDITOR",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			name := args[0]
			projectPath := requireProject()

			if !agents.Exists(name, projectPath) {
				return fmt.Errorf("agent %q not found", name)
			}

			openEditor(agents.FilePath(name, projectPath))

			if _, err := agents.Load(name, projectPath); err != nil {
				tui.Warning(fmt.Sprintf("Validation error: %v", err))
			} else {
				tui.Success(fmt.Sprintf("Charter for %q is valid.", name))
			}
			return nil
		},
	}
}
