package session

import (
	"os"
	"strings"
	"testing"

	"github.com/steveyegge/loguetown/internal/agents"
	"github.com/steveyegge/loguetown/internal/roles"
)

// TestMain isolates the storage singleton in a temp home dir.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "session-test-*")
	if err != nil {
		os.Exit(1)
	}
	defer os.RemoveAll(dir)
	os.Setenv("HOME", dir)
	os.Exit(m.Run())
}

// minimalCharter returns a resolved Charter with basic fields for testing.
func minimalCharter(name, role string) *agents.Charter {
	c := &agents.Charter{
		Name: name,
		Role: role,
		ResolvedTools: &roles.ToolsConfig{
			Allowed: []string{"read", "write", "bash"},
		},
	}
	return c
}

// ── Build tests ───────────────────────────────────────────────────────────────

func TestBuildNilProviderContainsSections(t *testing.T) {
	charter := minimalCharter("alice", "implementer")
	cfg := Config{
		WorkDir:       "/tmp/worktree",
		ProjectName:   "my-project",
		DefaultBranch: "main",
		Branch:        "lt/plan1/task1/a1",
	}

	sess, err := Build(charter, "Add login form", cfg, nil)
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	if sess.AgentName != "alice" {
		t.Errorf("AgentName: want 'alice', got %q", sess.AgentName)
	}
	if sess.Role != "implementer" {
		t.Errorf("Role: want 'implementer', got %q", sess.Role)
	}
	if sess.SkillsUsed != 0 {
		t.Errorf("SkillsUsed: want 0 (nil provider), got %d", sess.SkillsUsed)
	}
	if sess.MemoryUsed != 0 {
		t.Errorf("MemoryUsed: want 0 (nil provider), got %d", sess.MemoryUsed)
	}

	prompt := sess.SystemPrompt
	for _, want := range []string{
		"## Identity",
		"alice",
		"implementer",
		"## Repository Context",
		"my-project",
		"/tmp/worktree",
		"lt/plan1/task1/a1",
		"## Guidelines",
	} {
		if !strings.Contains(prompt, want) {
			t.Errorf("SystemPrompt missing %q", want)
		}
	}
}

func TestBuildNilProviderSkipsSkillsAndMemory(t *testing.T) {
	charter := minimalCharter("bob", "reviewer")
	cfg := Config{ProjectName: "test-project"}

	sess, err := Build(charter, "Review the PR", cfg, nil)
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	if strings.Contains(sess.SystemPrompt, "## Relevant Skills") {
		t.Error("prompt should not contain Skills section when provider is nil")
	}
	if strings.Contains(sess.SystemPrompt, "## Memory") {
		t.Error("prompt should not contain Memory section when provider is nil")
	}
}

func TestBuildToolsSection(t *testing.T) {
	charter := minimalCharter("charlie", "implementer")
	charter.ResolvedTools = &roles.ToolsConfig{
		Allowed:       []string{"read", "write"},
		BashAllowlist: []string{"npm *", "git *"},
	}
	cfg := Config{ProjectName: "tools-project"}

	sess, err := Build(charter, "Do something", cfg, nil)
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	prompt := sess.SystemPrompt
	if !strings.Contains(prompt, "## Allowed Tools") {
		t.Error("prompt missing '## Allowed Tools' section")
	}
	if !strings.Contains(prompt, "npm *") {
		t.Error("prompt missing bash allowlist entry 'npm *'")
	}
	if !strings.Contains(prompt, "git *") {
		t.Error("prompt missing bash allowlist entry 'git *'")
	}
}

func TestBuildEmptyTaskNilProvider(t *testing.T) {
	charter := minimalCharter("dave", "planner")
	cfg := Config{ProjectName: "empty-task-project"}

	// Empty task with nil provider — should not error, should still produce a prompt
	sess, err := Build(charter, "", cfg, nil)
	if err != nil {
		t.Fatalf("Build empty task: %v", err)
	}
	if sess.SystemPrompt == "" {
		t.Error("SystemPrompt should not be empty even for empty task")
	}
	if !strings.Contains(sess.SystemPrompt, "## Identity") {
		t.Error("prompt missing '## Identity' section")
	}
}

func TestBuildNoToolsSection(t *testing.T) {
	charter := minimalCharter("eve", "planner")
	charter.ResolvedTools = &roles.ToolsConfig{Allowed: nil} // no allowed tools
	cfg := Config{ProjectName: "no-tools-project"}

	sess, err := Build(charter, "Plan the sprint", cfg, nil)
	if err != nil {
		t.Fatalf("Build: %v", err)
	}
	if strings.Contains(sess.SystemPrompt, "## Allowed Tools") {
		t.Error("prompt should not contain Allowed Tools section when no tools allowed")
	}
}
