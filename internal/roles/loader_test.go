package roles_test

import (
	"testing"

	"github.com/steveyegge/loguetown/internal/roles"
)

func baseRole(name string) *roles.Role {
	return &roles.Role{
		Name:          name,
		Description:   "A test role",
		DefaultSkills: []string{"shared/overview.md"},
		DefaultTools:  roles.ToolsConfig{Allowed: []string{"read"}},
		DefaultModel:  roles.ModelConfig{Provider: "claude", ID: "claude-opus-4-6"},
	}
}

func TestSaveAndLoad(t *testing.T) {
	dir := t.TempDir()
	r := baseRole("tester")
	r.DefaultSkills = []string{"shared/overview.md", "shared/commit-style.md"}

	if err := roles.Save(r, dir); err != nil {
		t.Fatalf("Save: %v", err)
	}

	loaded, err := roles.Load("tester", dir)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if loaded.Name != r.Name {
		t.Errorf("Name = %q, want %q", loaded.Name, r.Name)
	}
	if loaded.DefaultModel.Provider != r.DefaultModel.Provider {
		t.Errorf("Provider = %q, want %q", loaded.DefaultModel.Provider, r.DefaultModel.Provider)
	}
	if loaded.DefaultModel.ID != r.DefaultModel.ID {
		t.Errorf("ID = %q, want %q", loaded.DefaultModel.ID, r.DefaultModel.ID)
	}
	if len(loaded.DefaultSkills) != len(r.DefaultSkills) {
		t.Errorf("DefaultSkills len = %d, want %d", len(loaded.DefaultSkills), len(r.DefaultSkills))
	}
}

func TestList(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"alpha", "beta", "gamma"} {
		if err := roles.Save(baseRole(name), dir); err != nil {
			t.Fatalf("Save %s: %v", name, err)
		}
	}

	names, err := roles.List(dir)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(names) != 3 {
		t.Errorf("expected 3 roles, got %d: %v", len(names), names)
	}
}

func TestListEmptyDir(t *testing.T) {
	dir := t.TempDir()
	names, err := roles.List(dir)
	if err != nil {
		t.Fatalf("List empty: %v", err)
	}
	if names != nil {
		t.Errorf("expected nil, got %v", names)
	}
}

func TestExists(t *testing.T) {
	dir := t.TempDir()
	if roles.Exists("check", dir) {
		t.Error("Exists should be false before Save")
	}
	roles.Save(baseRole("check"), dir)
	if !roles.Exists("check", dir) {
		t.Error("Exists should be true after Save")
	}
}

func TestDelete(t *testing.T) {
	dir := t.TempDir()
	roles.Save(baseRole("del"), dir)
	if err := roles.Delete("del", dir); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if roles.Exists("del", dir) {
		t.Error("role should not exist after Delete")
	}
}

func TestLoadMissingRole(t *testing.T) {
	dir := t.TempDir()
	_, err := roles.Load("nonexistent", dir)
	if err == nil {
		t.Error("expected error when loading nonexistent role")
	}
}

func TestValidate(t *testing.T) {
	cases := []struct {
		name    string
		role    *roles.Role
		wantErr bool
	}{
		{
			name:    "valid",
			role:    &roles.Role{Name: "ok", DefaultModel: roles.ModelConfig{Provider: "claude", ID: "x"}},
			wantErr: false,
		},
		{
			name:    "empty name",
			role:    &roles.Role{Name: "", DefaultModel: roles.ModelConfig{Provider: "claude", ID: "x"}},
			wantErr: true,
		},
		{
			name:    "empty provider",
			role:    &roles.Role{Name: "ok", DefaultModel: roles.ModelConfig{Provider: "", ID: "x"}},
			wantErr: true,
		},
		{
			name:    "empty id",
			role:    &roles.Role{Name: "ok", DefaultModel: roles.ModelConfig{Provider: "claude", ID: ""}},
			wantErr: true,
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			err := c.role.Validate()
			if (err != nil) != c.wantErr {
				t.Errorf("Validate() error = %v, wantErr %v", err, c.wantErr)
			}
		})
	}
}

func TestDefaults(t *testing.T) {
	defs := roles.Defaults()
	if len(defs) != 4 {
		t.Fatalf("expected 4 default roles, got %d", len(defs))
	}

	wantNames := map[string]bool{
		"planner": true, "implementer": true, "reviewer": true, "fixer": true,
	}
	for _, r := range defs {
		if err := r.Validate(); err != nil {
			t.Errorf("default role %q failed Validate: %v", r.Name, err)
		}
		if !wantNames[r.Name] {
			t.Errorf("unexpected default role name %q", r.Name)
		}
		delete(wantNames, r.Name)
	}
	for missing := range wantNames {
		t.Errorf("missing default role %q", missing)
	}
}

func TestDefaultsHaveSkills(t *testing.T) {
	for _, r := range roles.Defaults() {
		if len(r.DefaultSkills) == 0 {
			t.Errorf("default role %q has no default_skills", r.Name)
		}
	}
}

func TestDefaultsHaveTools(t *testing.T) {
	for _, r := range roles.Defaults() {
		if len(r.DefaultTools.Allowed) == 0 {
			t.Errorf("default role %q has no allowed tools", r.Name)
		}
	}
}

func TestTemplate(t *testing.T) {
	tmpl := roles.Template("custom")
	if tmpl == "" {
		t.Error("Template returned empty string")
	}
	// Should contain the role name
	if !contains(tmpl, "custom") {
		t.Error("Template should contain the role name")
	}
	// Should contain required fields
	for _, field := range []string{"default_model", "default_tools", "default_skills"} {
		if !contains(tmpl, field) {
			t.Errorf("Template should contain field %q", field)
		}
	}
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub || len(s) > 0 && containsStr(s, sub))
}

func containsStr(s, sub string) bool {
	for i := 0; i <= len(s)-len(sub); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
