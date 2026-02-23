package agents

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/steveyegge/loguetown/internal/roles"
)

// Charter is the parsed content of a .loguetown/agents/{name}.yaml file.
type Charter struct {
	Name        string              `yaml:"name"`
	Role        string              `yaml:"role"`
	Model       *roles.ModelConfig  `yaml:"model,omitempty"`
	ExtraSkills []string            `yaml:"extra_skills,omitempty"`
	Memory      *roles.MemoryConfig `yaml:"memory,omitempty"`
	Tools       *roles.ToolsConfig  `yaml:"tools,omitempty"`

	// Resolved fields — populated by Resolve(), not stored in YAML.
	ResolvedModel  *roles.ModelConfig  `yaml:"-"`
	ResolvedSkills []string            `yaml:"-"`
	ResolvedTools  *roles.ToolsConfig  `yaml:"-"`
	ResolvedMemory *roles.MemoryConfig `yaml:"-"`
}

// Resolve merges role defaults into the charter and populates Resolved* fields.
func Resolve(c *Charter, role *roles.Role) {
	// Model: charter overrides role
	if c.Model != nil {
		m := role.DefaultModel
		if c.Model.Provider != "" {
			m.Provider = c.Model.Provider
		}
		if c.Model.ID != "" {
			m.ID = c.Model.ID
		}
		if c.Model.Path != "" {
			m.Path = c.Model.Path
		}
		c.ResolvedModel = &m
	} else {
		m := role.DefaultModel // copy
		c.ResolvedModel = &m
	}

	// Skills: role defaults + extra_skills
	c.ResolvedSkills = append([]string{}, role.DefaultSkills...)
	c.ResolvedSkills = append(c.ResolvedSkills, c.ExtraSkills...)

	// Tools: charter overrides role
	if c.Tools != nil {
		t := role.DefaultTools
		if len(c.Tools.Allowed) > 0 {
			t.Allowed = c.Tools.Allowed
		}
		if len(c.Tools.BashAllowlist) > 0 {
			t.BashAllowlist = c.Tools.BashAllowlist
		}
		c.ResolvedTools = &t
	} else {
		t := role.DefaultTools
		c.ResolvedTools = &t
	}

	// Memory: charter overrides role
	if c.Memory != nil && role.DefaultMemory != nil {
		m := *role.DefaultMemory
		if len(c.Memory.Layers) > 0 {
			m.Layers = c.Memory.Layers
		}
		if c.Memory.Provider != "" {
			m.Provider = c.Memory.Provider
		}
		if c.Memory.MaxTokensInjected > 0 {
			m.MaxTokensInjected = c.Memory.MaxTokensInjected
		}
		if c.Memory.Budget != nil {
			m.Budget = c.Memory.Budget
		}
		c.ResolvedMemory = &m
	} else if role.DefaultMemory != nil {
		m := *role.DefaultMemory
		c.ResolvedMemory = &m
	}
}

// AgentsDir returns the agents directory path.
func AgentsDir(projectPath string) string {
	return filepath.Join(projectPath, ".loguetown", "agents")
}

// FilePath returns the YAML file path for a named agent.
func FilePath(name, projectPath string) string {
	return filepath.Join(AgentsDir(projectPath), name+".yaml")
}

// List returns the names of all agents in the project.
func List(projectPath string) ([]string, error) {
	dir := AgentsDir(projectPath)
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

// Load reads, parses, and resolves a charter (merging role defaults).
func Load(name, projectPath string) (*Charter, error) {
	path := FilePath(name, projectPath)
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("agent %q: %w", name, err)
	}

	var c Charter
	if err := yaml.Unmarshal(data, &c); err != nil {
		return nil, fmt.Errorf("agent %q: invalid YAML: %w", name, err)
	}

	if c.Name == "" {
		return nil, fmt.Errorf("agent %q: name is required in charter", name)
	}
	if c.Role == "" {
		return nil, fmt.Errorf("agent %q: role is required in charter", name)
	}

	role, err := roles.Load(c.Role, projectPath)
	if err != nil {
		return nil, fmt.Errorf("agent %q: load role %q: %w", name, c.Role, err)
	}

	Resolve(&c, role)
	return &c, nil
}

// Exists reports whether the agent charter file exists.
func Exists(name, projectPath string) bool {
	_, err := os.Stat(FilePath(name, projectPath))
	return err == nil
}

// Save writes a charter to its YAML file (without Resolved* fields).
func Save(c *Charter, projectPath string) error {
	dir := AgentsDir(projectPath)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}

	// Only marshal storable fields (not Resolved*)
	type stored struct {
		Name        string              `yaml:"name"`
		Role        string              `yaml:"role"`
		Model       *roles.ModelConfig  `yaml:"model,omitempty"`
		ExtraSkills []string            `yaml:"extra_skills,omitempty"`
		Memory      *roles.MemoryConfig `yaml:"memory,omitempty"`
		Tools       *roles.ToolsConfig  `yaml:"tools,omitempty"`
	}
	s := stored{
		Name:        c.Name,
		Role:        c.Role,
		Model:       c.Model,
		ExtraSkills: c.ExtraSkills,
		Memory:      c.Memory,
		Tools:       c.Tools,
	}

	data, err := yaml.Marshal(&s)
	if err != nil {
		return err
	}
	return os.WriteFile(FilePath(c.Name, projectPath), data, 0o644)
}

// Template returns a commented starter YAML for a new agent charter.
func Template(name, roleName, modelID string) string {
	modelLine := ""
	if modelID != "" {
		modelLine = fmt.Sprintf("\nmodel:\n  provider: claude\n  id: %s\n", modelID)
	}
	return fmt.Sprintf(`name: %s
role: %s
%s
# extra_skills:
#   - implementer/react-patterns.md

# memory:
#   max_tokens_injected: 8000

# tools:
#   allowed: [read, write, bash]
#   bash_allowlist:
#     - "npm *"
#     - "git *"
`, name, roleName, modelLine)
}
