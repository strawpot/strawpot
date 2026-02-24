package cmd

import (
	"fmt"
	"os"
	"os/exec"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"

	"github.com/juhgiyo/loguetown/internal/config"
	"github.com/juhgiyo/loguetown/internal/roles"
	"github.com/juhgiyo/loguetown/internal/tui"
)

func newRoleCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "role",
		Short: "Manage agent roles",
	}

	cmd.AddCommand(roleListCmd())
	cmd.AddCommand(roleShowCmd())
	cmd.AddCommand(roleCreateCmd())
	cmd.AddCommand(roleEditCmd())
	cmd.AddCommand(roleDeleteCmd())
	return cmd
}

func requireProject() string {
	cwd, _ := os.Getwd()
	p := config.FindProjectPath(cwd)
	if p == "" {
		tui.Fatal("No .loguetown/project.yaml found. Run 'lt init' first.")
	}
	return p
}

func roleListCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List all roles in .loguetown/roles/",
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()
			names, err := roles.List(projectPath)
			if err != nil {
				return err
			}
			if len(names) == 0 {
				tui.Info("No roles found. Run 'lt init' to scaffold default roles.")
				return nil
			}

			var rows [][]string
			for _, name := range names {
				r, err := roles.Load(name, projectPath)
				if err != nil {
					rows = append(rows, []string{name, "(invalid yaml)", "", "", ""})
					continue
				}
				rows = append(rows, []string{
					name,
					r.Description,
					fmt.Sprintf("%s/%s", r.DefaultModel.Provider, r.DefaultModel.ID),
					fmt.Sprintf("%d", len(r.DefaultSkills)),
					joinStrings(r.DefaultTools.Allowed),
				})
			}

			tui.Table([]string{"Name", "Description", "Default Model", "Skills", "Tools"}, rows)
			return nil
		},
	}
}

func roleShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show <name>",
		Short: "Print resolved role YAML",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()
			r, err := roles.Load(args[0], projectPath)
			if err != nil {
				return err
			}
			tui.Header(fmt.Sprintf("Role: %s", args[0]))
			data, _ := yaml.Marshal(r)
			fmt.Print(string(data))
			return nil
		},
	}
}

func roleCreateCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "create <name>",
		Short: "Scaffold a new role YAML file",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			name := args[0]
			projectPath := requireProject()

			if roles.Exists(name, projectPath) {
				tui.Warning(fmt.Sprintf("Role %q already exists. Use 'lt role edit %s' to modify it.", name, name))
				return nil
			}

			path := roles.FilePath(name, projectPath)
			if err := os.WriteFile(path, []byte(roles.Template(name)), 0o644); err != nil {
				return err
			}
			tui.Success(fmt.Sprintf("Created .loguetown/roles/%s.yaml", name))
			openEditor(path)
			return nil
		},
	}
}

func roleEditCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "edit <name>",
		Short: "Open role YAML in $EDITOR",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			name := args[0]
			projectPath := requireProject()
			if !roles.Exists(name, projectPath) {
				return fmt.Errorf("role %q not found; use 'lt role create %s' to create it", name, name)
			}
			openEditor(roles.FilePath(name, projectPath))
			// Re-validate after edit
			if _, err := roles.Load(name, projectPath); err != nil {
				tui.Warning(fmt.Sprintf("Validation error: %v", err))
			} else {
				tui.Success(fmt.Sprintf("Role %q is valid.", name))
			}
			return nil
		},
	}
}

func roleDeleteCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "delete <name>",
		Short: "Remove a role file",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			name := args[0]
			projectPath := requireProject()
			if !roles.Exists(name, projectPath) {
				return fmt.Errorf("role %q not found", name)
			}
			if err := roles.Delete(name, projectPath); err != nil {
				return err
			}
			tui.Success(fmt.Sprintf("Deleted .loguetown/roles/%s.yaml", name))
			return nil
		},
	}
}

func openEditor(path string) {
	editor := os.Getenv("EDITOR")
	if editor == "" {
		editor = os.Getenv("VISUAL")
	}
	if editor == "" {
		tui.Info(fmt.Sprintf("Edit the file: %s", path))
		return
	}
	tui.Info(fmt.Sprintf("Opening in %s...", editor))
	c := exec.Command(editor, path)
	c.Stdin = os.Stdin
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	_ = c.Run()
}

func joinStrings(ss []string) string {
	result := ""
	for i, s := range ss {
		if i > 0 {
			result += ", "
		}
		result += s
	}
	return result
}
