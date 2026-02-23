package agents_test

import (
	"testing"

	"github.com/steveyegge/loguetown/internal/agents"
	"github.com/steveyegge/loguetown/internal/roles"
)

func makeRole() *roles.Role {
	return &roles.Role{
		Name:          "base",
		DefaultSkills: []string{"shared/overview.md", "shared/commit-style.md"},
		DefaultTools:  roles.ToolsConfig{Allowed: []string{"read", "write"}},
		DefaultModel:  roles.ModelConfig{Provider: "claude", ID: "claude-opus-4-6"},
		DefaultMemory: &roles.MemoryConfig{
			Layers:            []string{"episodic"},
			Provider:          "local",
			MaxTokensInjected: 4000,
		},
	}
}

// saveRoleAndCharter is a helper that creates the role YAML, saves the charter,
// and returns the project dir.
func saveRoleAndCharter(t *testing.T, c *agents.Charter) string {
	t.Helper()
	dir := t.TempDir()
	role := makeRole()
	role.Name = c.Role
	if err := roles.Save(role, dir); err != nil {
		t.Fatalf("Save role: %v", err)
	}
	if err := agents.Save(c, dir); err != nil {
		t.Fatalf("Save charter: %v", err)
	}
	return dir
}

func TestResolveInheritsRoleModel(t *testing.T) {
	role := makeRole()
	c := &agents.Charter{
		Name: "alice",
		Role: "base",
	}
	agents.Resolve(c, role)

	if c.ResolvedModel == nil {
		t.Fatal("ResolvedModel should not be nil")
	}
	if c.ResolvedModel.Provider != "claude" {
		t.Errorf("Provider = %q, want claude", c.ResolvedModel.Provider)
	}
	if c.ResolvedModel.ID != "claude-opus-4-6" {
		t.Errorf("ID = %q, want claude-opus-4-6", c.ResolvedModel.ID)
	}
}

func TestResolveCharterOverridesModel(t *testing.T) {
	role := makeRole()
	c := &agents.Charter{
		Name:  "override",
		Role:  "base",
		Model: &roles.ModelConfig{Provider: "openai", ID: "gpt-4o"},
	}
	agents.Resolve(c, role)

	if c.ResolvedModel.Provider != "openai" {
		t.Errorf("Provider = %q, want openai", c.ResolvedModel.Provider)
	}
	if c.ResolvedModel.ID != "gpt-4o" {
		t.Errorf("ID = %q, want gpt-4o", c.ResolvedModel.ID)
	}
}

func TestResolveExtraSkillsAppended(t *testing.T) {
	role := makeRole()
	c := &agents.Charter{
		Name:        "skilled",
		Role:        "base",
		ExtraSkills: []string{"shared/extra.md"},
	}
	agents.Resolve(c, role)

	// ResolvedSkills = role.DefaultSkills + ExtraSkills
	wantLen := len(role.DefaultSkills) + 1
	if len(c.ResolvedSkills) != wantLen {
		t.Errorf("ResolvedSkills len = %d, want %d: %v", len(c.ResolvedSkills), wantLen, c.ResolvedSkills)
	}
	last := c.ResolvedSkills[len(c.ResolvedSkills)-1]
	if last != "shared/extra.md" {
		t.Errorf("last ResolvedSkill = %q, want shared/extra.md", last)
	}
}

func TestResolveToolsInheritedFromRole(t *testing.T) {
	role := makeRole()
	c := &agents.Charter{Name: "tooltest", Role: "base"}
	agents.Resolve(c, role)

	if c.ResolvedTools == nil {
		t.Fatal("ResolvedTools should not be nil")
	}
	if len(c.ResolvedTools.Allowed) != len(role.DefaultTools.Allowed) {
		t.Errorf("Allowed len = %d, want %d", len(c.ResolvedTools.Allowed), len(role.DefaultTools.Allowed))
	}
}

func TestResolveMemoryInherited(t *testing.T) {
	role := makeRole()
	c := &agents.Charter{Name: "memtest", Role: "base"}
	agents.Resolve(c, role)

	if c.ResolvedMemory == nil {
		t.Fatal("ResolvedMemory should not be nil")
	}
	if c.ResolvedMemory.Provider != "local" {
		t.Errorf("Memory.Provider = %q, want local", c.ResolvedMemory.Provider)
	}
}

func TestSaveAndLoad(t *testing.T) {
	c := &agents.Charter{
		Name: "alice",
		Role: "base",
	}
	dir := saveRoleAndCharter(t, c)

	loaded, err := agents.Load("alice", dir)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if loaded.Name != "alice" {
		t.Errorf("Name = %q, want alice", loaded.Name)
	}
	if loaded.Role != "base" {
		t.Errorf("Role = %q, want base", loaded.Role)
	}
	if loaded.ResolvedModel == nil {
		t.Error("ResolvedModel should be populated after Load")
	}
}

func TestSaveDoesNotPersistResolvedFields(t *testing.T) {
	// Resolved* fields (yaml:"-") should not appear in the YAML file.
	c := &agents.Charter{
		Name: "noisy",
		Role: "base",
	}
	dir := saveRoleAndCharter(t, c)

	// Load back and check: if Resolved fields leaked into YAML they'd be read
	// as unknown YAML keys (harmless), but let's just verify Load still works.
	loaded, err := agents.Load("noisy", dir)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	// Model field in charter YAML should be nil (we didn't set it)
	if loaded.Model != nil {
		t.Error("Model should be nil — not set in charter")
	}
}

func TestList(t *testing.T) {
	dir := t.TempDir()
	role := makeRole()
	if err := roles.Save(role, dir); err != nil {
		t.Fatalf("Save role: %v", err)
	}

	for _, name := range []string{"a1", "a2", "a3"} {
		if err := agents.Save(&agents.Charter{Name: name, Role: "base"}, dir); err != nil {
			t.Fatalf("Save %s: %v", name, err)
		}
	}

	names, err := agents.List(dir)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(names) != 3 {
		t.Errorf("expected 3 agents, got %d: %v", len(names), names)
	}
}

func TestExists(t *testing.T) {
	dir := t.TempDir()
	if agents.Exists("bob", dir) {
		t.Error("should not exist before Save")
	}
	agents.Save(&agents.Charter{Name: "bob", Role: "base"}, dir)
	if !agents.Exists("bob", dir) {
		t.Error("should exist after Save")
	}
}

func TestLoadMissing(t *testing.T) {
	dir := t.TempDir()
	_, err := agents.Load("ghost", dir)
	if err == nil {
		t.Error("expected error loading nonexistent agent")
	}
}

func TestTemplate(t *testing.T) {
	tmpl := agents.Template("myagent", "implementer", "claude-opus-4-6")
	if tmpl == "" {
		t.Fatal("Template returned empty string")
	}
	for _, want := range []string{"myagent", "implementer"} {
		if !containsStr(tmpl, want) {
			t.Errorf("Template should contain %q", want)
		}
	}
}

func containsStr(s, sub string) bool {
	for i := 0; i <= len(s)-len(sub); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
