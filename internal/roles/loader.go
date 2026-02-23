package roles

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

// ModelConfig specifies the AI model for a role or agent.
type ModelConfig struct {
	Provider string                 `yaml:"provider"` // claude | openai | ollama | custom
	ID       string                 `yaml:"id"`
	Path     string                 `yaml:"path,omitempty"`
	Options  map[string]interface{} `yaml:"options,omitempty"`
}

// ToolsConfig specifies allowed tools and bash commands.
type ToolsConfig struct {
	Allowed      []string `yaml:"allowed"`
	BashAllowlist []string `yaml:"bash_allowlist,omitempty"`
}

// MemoryConfig specifies memory layer settings.
type MemoryConfig struct {
	Layers            []string               `yaml:"layers,omitempty"`
	Provider          string                 `yaml:"provider,omitempty"`
	MaxTokensInjected int                    `yaml:"max_tokens_injected,omitempty"`
	Budget            map[string]interface{} `yaml:"budget,omitempty"`
}

// Role is the parsed content of a .loguetown/roles/{name}.yaml file.
type Role struct {
	Name          string       `yaml:"name"`
	Description   string       `yaml:"description,omitempty"`
	DefaultSkills []string     `yaml:"default_skills"`
	DefaultTools  ToolsConfig  `yaml:"default_tools"`
	DefaultModel  ModelConfig  `yaml:"default_model"`
	DefaultMemory *MemoryConfig `yaml:"default_memory,omitempty"`
}

// Validate checks required fields.
func (r *Role) Validate() error {
	if r.Name == "" {
		return fmt.Errorf("role name is required")
	}
	if r.DefaultModel.Provider == "" {
		return fmt.Errorf("role %q: default_model.provider is required", r.Name)
	}
	if r.DefaultModel.ID == "" {
		return fmt.Errorf("role %q: default_model.id is required", r.Name)
	}
	return nil
}

// RolesDir returns the path to the roles directory for a project.
func RolesDir(projectPath string) string {
	return filepath.Join(projectPath, ".loguetown", "roles")
}

// FilePath returns the YAML file path for a named role.
func FilePath(name, projectPath string) string {
	return filepath.Join(RolesDir(projectPath), name+".yaml")
}

// List returns the names of all roles in the project.
func List(projectPath string) ([]string, error) {
	dir := RolesDir(projectPath)
	entries, err := os.ReadDir(dir)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	var names []string
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		if strings.HasSuffix(name, ".yaml") || strings.HasSuffix(name, ".yml") {
			names = append(names, strings.TrimSuffix(strings.TrimSuffix(name, ".yaml"), ".yml"))
		}
	}
	return names, nil
}

// Load reads and parses a role YAML file.
func Load(name, projectPath string) (*Role, error) {
	path := FilePath(name, projectPath)
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("role %q: %w", name, err)
	}

	var r Role
	if err := yaml.Unmarshal(data, &r); err != nil {
		return nil, fmt.Errorf("role %q: invalid YAML: %w", name, err)
	}

	if err := r.Validate(); err != nil {
		return nil, err
	}
	return &r, nil
}

// Exists reports whether the role YAML file exists.
func Exists(name, projectPath string) bool {
	_, err := os.Stat(FilePath(name, projectPath))
	return err == nil
}

// Save writes a role to its YAML file (creates the roles dir if needed).
func Save(r *Role, projectPath string) error {
	dir := RolesDir(projectPath)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}

	data, err := yaml.Marshal(r)
	if err != nil {
		return err
	}
	return os.WriteFile(FilePath(r.Name, projectPath), data, 0o644)
}

// Delete removes a role YAML file.
func Delete(name, projectPath string) error {
	return os.Remove(FilePath(name, projectPath))
}

// Template returns a starter YAML string for a new role.
func Template(name string) string {
	return fmt.Sprintf(`name: %s
description: "Description of this role"

default_skills:
  - shared/project-overview.md

default_tools:
  allowed: [read, write, bash]
  bash_allowlist:
    - "npm *"
    - "git *"

default_model:
  provider: claude
  id: claude-opus-4-6

default_memory:
  layers: [episodic, semantic_local, semantic_global]
  provider: local
  max_tokens_injected: 8000
`, name)
}

// Defaults returns the four built-in roles scaffolded by lt init.
func Defaults() []*Role {
	return []*Role{
		{
			Name:        "planner",
			Description: "Decomposes an objective into a DAG of tasks",
			DefaultSkills: []string{
				"planner/decomposition-heuristics.md",
				"shared/project-overview.md",
			},
			DefaultTools: ToolsConfig{Allowed: []string{"read"}},
			DefaultModel: ModelConfig{Provider: "claude", ID: "claude-opus-4-6"},
			DefaultMemory: &MemoryConfig{
				Layers:            []string{"episodic", "semantic_local", "semantic_global"},
				Provider:          "local",
				MaxTokensInjected: 6000,
			},
		},
		{
			Name:        "implementer",
			Description: "Writes code to implement features and fix bugs",
			DefaultSkills: []string{
				"implementer/typescript-patterns.md",
				"implementer/testing-conventions.md",
				"implementer/git-workflow.md",
				"shared/commit-style.md",
			},
			DefaultTools: ToolsConfig{
				Allowed:       []string{"read", "write", "bash"},
				BashAllowlist: []string{"npm *", "git *", "npx tsc *", "npx eslint *"},
			},
			DefaultModel: ModelConfig{Provider: "claude", ID: "claude-opus-4-6"},
			DefaultMemory: &MemoryConfig{
				Layers:            []string{"episodic", "semantic_local", "semantic_global"},
				Provider:          "local",
				MaxTokensInjected: 8000,
			},
		},
		{
			Name:        "reviewer",
			Description: "Reviews diffs against acceptance criteria",
			DefaultSkills: []string{
				"reviewer/code-review-checklist.md",
				"reviewer/security-checklist.md",
				"shared/project-overview.md",
			},
			DefaultTools: ToolsConfig{Allowed: []string{"read"}},
			DefaultModel: ModelConfig{Provider: "claude", ID: "claude-opus-4-6"},
			DefaultMemory: &MemoryConfig{
				Layers:            []string{"episodic", "semantic_local", "semantic_global"},
				Provider:          "local",
				MaxTokensInjected: 6000,
			},
		},
		{
			Name:        "fixer",
			Description: "Fixes failing checks or review blockers",
			DefaultSkills: []string{
				"fixer/debugging-strategies.md",
				"fixer/minimal-change-principle.md",
				"shared/commit-style.md",
			},
			DefaultTools: ToolsConfig{
				Allowed:       []string{"read", "write", "bash"},
				BashAllowlist: []string{"npm *", "git *", "npx tsc *", "npx eslint *"},
			},
			DefaultModel: ModelConfig{Provider: "claude", ID: "claude-opus-4-6"},
			DefaultMemory: &MemoryConfig{
				Layers:            []string{"episodic", "semantic_local", "semantic_global"},
				Provider:          "local",
				MaxTokensInjected: 6000,
			},
		},
	}
}
