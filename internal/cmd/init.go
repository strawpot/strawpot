package cmd

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/google/uuid"
	"github.com/juhgiyo/loguetown/internal/chronicle"
	"github.com/juhgiyo/loguetown/internal/config"
	"github.com/juhgiyo/loguetown/internal/roles"
	"github.com/juhgiyo/loguetown/internal/storage"
	"github.com/juhgiyo/loguetown/internal/tui"
	"github.com/spf13/cobra"
)

func newInitCmd() *cobra.Command {
	var force bool

	cmd := &cobra.Command{
		Use:   "init",
		Short: "Scaffold .loguetown/ in the current repository",
		RunE: func(cmd *cobra.Command, args []string) error {
			cwd, _ := os.Getwd()
			gitRoot := config.FindGitRoot(cwd)
			if gitRoot == "" {
				tui.Fatal("Not inside a git repository. Run 'git init' first.")
			}

			ltDir := filepath.Join(gitRoot, ".loguetown")
			projectYAML := filepath.Join(ltDir, "project.yaml")

			if _, err := os.Stat(projectYAML); err == nil && !force {
				tui.Warning(".loguetown/ already exists. Use --force to add missing files.")
				if p, err := config.LoadProject(gitRoot); err == nil {
					tui.Info(fmt.Sprintf("Project: %s (%s)", p.Project.Name, p.Project.ID))
				}
				return nil
			}

			tui.Header("Initializing Loguetown")

			projectID := uuid.New().String()[:12]
			projectName := filepath.Base(gitRoot)

			// 1. Directory structure
			dirs := []string{
				ltDir,
				filepath.Join(ltDir, "roles"),
				filepath.Join(ltDir, "agents"),
				filepath.Join(ltDir, "skills"),
				filepath.Join(ltDir, "memory"),
			}
			for _, role := range []string{"implementer", "reviewer", "fixer", "planner", "shared"} {
				dirs = append(dirs, filepath.Join(ltDir, "skills", role))
			}
			for _, d := range dirs {
				if err := os.MkdirAll(d, 0o755); err != nil {
					return fmt.Errorf("create dir %s: %w", d, err)
				}
			}

			// 2. project.yaml
			if _, err := os.Stat(projectYAML); os.IsNotExist(err) {
				if err := os.WriteFile(projectYAML, []byte(defaultProjectYAML(projectName, projectID)), 0o644); err != nil {
					return err
				}
				tui.Success("Created .loguetown/project.yaml")
			}

			// 3. Default role YAMLs
			created := 0
			for _, r := range roles.Defaults() {
				if !roles.Exists(r.Name, gitRoot) {
					if err := roles.Save(r, gitRoot); err != nil {
						tui.Warning(fmt.Sprintf("Could not write role %s: %v", r.Name, err))
					} else {
						created++
					}
				}
			}
			if created > 0 {
				tui.Success(fmt.Sprintf("Created %d role definitions in .loguetown/roles/", created))
			}

			// 4. Skill stub files
			skillsCreated := 0
			for relPath, content := range skillStubs {
				full := filepath.Join(ltDir, "skills", relPath)
				if _, err := os.Stat(full); os.IsNotExist(err) {
					if err := os.WriteFile(full, []byte(content), 0o644); err == nil {
						skillsCreated++
					}
				}
			}
			if skillsCreated > 0 {
				tui.Success(fmt.Sprintf("Created %d skill stub files in .loguetown/skills/", skillsCreated))
			}

			// 5. Register in SQLite + emit chronicle event
			// Use existing id if re-running with --force
			dbID := projectID
			if p, err := config.LoadProject(gitRoot); err == nil && p.Project.ID != "" {
				dbID = p.Project.ID
			}

			db, err := storage.Get()
			if err != nil {
				tui.Warning(fmt.Sprintf("SQLite unavailable: %v", err))
			} else {
				_, err = db.Exec(
					"INSERT OR IGNORE INTO projects (id, name, repo_path, default_branch, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
					dbID, projectName, gitRoot, "main",
				)
				if err != nil {
					tui.Warning(fmt.Sprintf("SQLite registration failed: %v", err))
				} else {
					_, _ = chronicle.Emit(dbID, "human:user", "PROJECT_INITIALIZED", map[string]interface{}{
						"project_name": projectName,
						"repo_path":    gitRoot,
					})
					tui.Success("Registered project in ~/.loguetown/db.sqlite")
				}
			}

			fmt.Println()
			tui.Success(fmt.Sprintf("Loguetown initialized in %s", gitRoot))
			fmt.Println()
			tui.Info("Next steps:")
			fmt.Println("  lt role list                               # see the 4 built-in roles")
			fmt.Println("  lt agent create --name charlie --role implementer")
			fmt.Println("  lt agent list")
			return nil
		},
	}

	cmd.Flags().BoolVar(&force, "force", false, "Add missing files only (never overwrites)")
	return cmd
}

func defaultProjectYAML(name, id string) string {
	return fmt.Sprintf(`project:
  id: %s
  name: %s
  repo_path: .
  default_branch: main

orchestrator:
  model:
    provider: claude
    id: claude-opus-4-6
  max_tasks_per_plan: 20
  stale_run_timeout_minutes: 20

scheduler:
  max_parallel_runs: 3
  max_fix_attempts: 3

embeddings:
  provider: local
  model: all-MiniLM-L6-v2
  dimensions: 384

memory:
  episodic_retention:
    max_entries: 100
    max_days: 90
  retrieval:
    top_k: 5
    min_similarity: 0.65
  max_tokens_injected: 6000

checks: {}
# Example:
# checks:
#   setup:
#     run: "npm ci"
#   lint:
#     run: "npx eslint src"
#   typecheck:
#     run: "npx tsc --noEmit"
#   test_fast:
#     run: "npm test -- --testPathPattern=unit"
#     timeout_seconds: 60
#   test_full:
#     run: "npm test"
#     timeout_seconds: 300

merge:
  approval_policy: require_human
  strategy: squash
  require_checks: []
  require_review: true
  restricted_paths: []

escalation:
  auto_bump_after_minutes: 30
  critical_task_threshold: 3

notifications:
  on_needs_human:
    desktop: true
  on_escalation_bumped:
    desktop: true
  on_merge_ready:
    desktop: true

gui:
  port: 4242
  auth: false
`, id, name)
}

var skillStubs = map[string]string{
	"implementer/typescript-patterns.md":  "# TypeScript Patterns\n\n<!-- Document TypeScript conventions for this codebase -->\n",
	"implementer/testing-conventions.md":  "# Testing Conventions\n\n<!-- Document how to write tests in this codebase -->\n",
	"implementer/git-workflow.md":         "# Git Workflow\n\n<!-- Document commit style, branch rules, PR process -->\n",
	"reviewer/code-review-checklist.md":   "# Code Review Checklist\n\n<!-- Document what a thorough review checks -->\n",
	"reviewer/security-checklist.md":      "# Security Checklist\n\n<!-- OWASP top 10, injection, auth issues, etc. -->\n",
	"fixer/debugging-strategies.md":       "# Debugging Strategies\n\n<!-- Document approaches for debugging common issues -->\n",
	"fixer/minimal-change-principle.md":   "# Minimal Change Principle\n\nMake the smallest possible change to fix the issue.\n",
	"planner/decomposition-heuristics.md": "# Decomposition Heuristics\n\n<!-- Guide for breaking objectives into DAG tasks -->\n",
	"shared/commit-style.md": `# Commit Style

Use conventional commits: ` + "`type(scope): description`" + `

- ` + "`feat:`" + ` — new feature
- ` + "`fix:`" + ` — bug fix
- ` + "`refactor:`" + ` — code refactor without behavior change
- ` + "`test:`" + ` — add or update tests
- ` + "`docs:`" + ` — documentation changes
- ` + "`chore:`" + ` — build, deps, config

Keep the subject line under 72 characters. Use imperative mood.
`,
	"shared/project-overview.md": `# Project Overview

<!-- Describe the project architecture here. This file is read by all agents. -->

## Architecture

## Key Directories

## Development Commands
`,
}
