package config_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/steveyegge/loguetown/internal/config"
)

func writeProjectYAML(t *testing.T, dir, content string) {
	t.Helper()
	ltDir := filepath.Join(dir, ".loguetown")
	if err := os.MkdirAll(ltDir, 0o755); err != nil {
		t.Fatalf("mkdir .loguetown: %v", err)
	}
	if err := os.WriteFile(filepath.Join(ltDir, "project.yaml"), []byte(content), 0o644); err != nil {
		t.Fatalf("write project.yaml: %v", err)
	}
}

func TestFindProjectPath(t *testing.T) {
	dir := t.TempDir()
	writeProjectYAML(t, dir, "project:\n  id: test\n")

	got := config.FindProjectPath(dir)
	if got != dir {
		t.Errorf("FindProjectPath(dir) = %q, want %q", got, dir)
	}
}

func TestFindProjectPathFromSubdir(t *testing.T) {
	dir := t.TempDir()
	writeProjectYAML(t, dir, "project:\n  id: test\n")

	subdir := filepath.Join(dir, "src", "components")
	if err := os.MkdirAll(subdir, 0o755); err != nil {
		t.Fatalf("mkdir subdir: %v", err)
	}

	got := config.FindProjectPath(subdir)
	if got != dir {
		t.Errorf("FindProjectPath(subdir) = %q, want %q", got, dir)
	}
}

func TestFindProjectPathMissing(t *testing.T) {
	dir := t.TempDir()
	got := config.FindProjectPath(dir)
	if got != "" {
		t.Errorf("FindProjectPath should return '' when not found, got %q", got)
	}
}

func TestFindGitRoot(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, ".git"), 0o755); err != nil {
		t.Fatalf("mkdir .git: %v", err)
	}

	got := config.FindGitRoot(dir)
	if got != dir {
		t.Errorf("FindGitRoot(dir) = %q, want %q", got, dir)
	}
}

func TestFindGitRootFromSubdir(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, ".git"), 0o755); err != nil {
		t.Fatalf("mkdir .git: %v", err)
	}

	subdir := filepath.Join(dir, "deep", "nested", "path")
	if err := os.MkdirAll(subdir, 0o755); err != nil {
		t.Fatalf("mkdir subdir: %v", err)
	}

	got := config.FindGitRoot(subdir)
	if got != dir {
		t.Errorf("FindGitRoot(subdir) = %q, want %q", got, dir)
	}
}

func TestFindGitRootMissing(t *testing.T) {
	// Use a known isolated temp path that has no .git ancestor.
	dir, err := os.MkdirTemp("", "config-gitroot-*")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(dir)

	// Resolve symlinks to get the real path (macOS /var → /private/var).
	real, err := filepath.EvalSymlinks(dir)
	if err != nil {
		real = dir
	}

	got := config.FindGitRoot(real)
	if got != "" {
		t.Errorf("FindGitRoot should return '' when not found, got %q", got)
	}
}

func TestLoadProject(t *testing.T) {
	dir := t.TempDir()
	yaml := `project:
  id: abc123
  name: my-project
  repo_path: .
  default_branch: main
`
	writeProjectYAML(t, dir, yaml)

	p, err := config.LoadProject(dir)
	if err != nil {
		t.Fatalf("LoadProject: %v", err)
	}
	if p.Project.ID != "abc123" {
		t.Errorf("ID = %q, want abc123", p.Project.ID)
	}
	if p.Project.Name != "my-project" {
		t.Errorf("Name = %q, want my-project", p.Project.Name)
	}
	if p.Project.DefaultBranch != "main" {
		t.Errorf("DefaultBranch = %q, want main", p.Project.DefaultBranch)
	}
}

func TestLoadProjectMissing(t *testing.T) {
	dir := t.TempDir()
	_, err := config.LoadProject(dir)
	if err == nil {
		t.Error("expected error when project.yaml is missing")
	}
}

func TestLoadProjectInvalidYAML(t *testing.T) {
	dir := t.TempDir()
	writeProjectYAML(t, dir, ":: invalid :: yaml ::")
	_, err := config.LoadProject(dir)
	if err == nil {
		t.Error("expected error for invalid YAML")
	}
}
