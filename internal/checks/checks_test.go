package checks

import (
	"os"
	"strings"
	"testing"

	"github.com/juhgiyo/loguetown/internal/config"
)

// TestMain isolates the storage singleton in a temp home dir.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "checks-test-*")
	if err != nil {
		os.Exit(1)
	}
	defer os.RemoveAll(dir)
	os.Setenv("HOME", dir)
	os.Exit(m.Run())
}

func TestRunPassingCheck(t *testing.T) {
	workDir := t.TempDir()
	artifactDir := t.TempDir()
	step := config.CheckStep{Name: "echo", Run: "echo hello"}

	res := Run("", "run1", step, workDir, artifactDir)
	if !res.Passed {
		t.Errorf("expected passed, got exitCode=%d stderr=%q", res.ExitCode, res.Stderr)
	}
	if res.Blocking {
		t.Error("passing check should not be blocking")
	}
	if res.Skipped {
		t.Error("check was not skipped")
	}
	if !strings.Contains(res.Stdout, "hello") {
		t.Errorf("expected stdout to contain 'hello', got %q", res.Stdout)
	}
	if res.ArtifactPath == "" {
		t.Error("expected artifact path to be set")
	}
}

func TestRunFailingBlockingCheck(t *testing.T) {
	workDir := t.TempDir()
	artifactDir := t.TempDir()
	step := config.CheckStep{Name: "fail", Run: "exit 1"}

	res := Run("", "run2", step, workDir, artifactDir)
	if res.Passed {
		t.Error("expected failure")
	}
	if !res.Blocking {
		t.Error("expected blocking (default on_fail)")
	}
	if res.ExitCode == 0 {
		t.Error("expected non-zero exit code")
	}
}

func TestRunFailingWarnCheck(t *testing.T) {
	workDir := t.TempDir()
	artifactDir := t.TempDir()
	step := config.CheckStep{Name: "warn", Run: "exit 2", OnFail: "warn"}

	res := Run("", "run3", step, workDir, artifactDir)
	if res.Passed {
		t.Error("expected failure")
	}
	if res.Blocking {
		t.Error("warn check should not be blocking")
	}
}

func TestRunTimeout(t *testing.T) {
	workDir := t.TempDir()
	artifactDir := t.TempDir()
	step := config.CheckStep{Name: "slow", Run: "sleep 10", TimeoutSeconds: 1}

	res := Run("", "run4", step, workDir, artifactDir)
	if res.Passed {
		t.Error("expected timeout to fail")
	}
}

// ── Pipeline tests ─────────────────────────────────────────────────────────────

func TestRunPipelineAllPass(t *testing.T) {
	workDir := t.TempDir()
	artifactDir := t.TempDir()
	steps := []config.CheckStep{
		{Name: "a", Run: "echo a"},
		{Name: "b", Run: "echo b"},
	}

	pr := RunPipeline("", "r1", steps, nil, workDir, artifactDir, "")
	if !pr.Passed {
		t.Error("expected pipeline to pass")
	}
	if len(pr.Results) != 2 {
		t.Errorf("expected 2 results, got %d", len(pr.Results))
	}
}

func TestRunPipelineStopsOnBlock(t *testing.T) {
	workDir := t.TempDir()
	artifactDir := t.TempDir()
	steps := []config.CheckStep{
		{Name: "a", Run: "echo a"},
		{Name: "fail", Run: "exit 1"},      // blocking — should stop here
		{Name: "never", Run: "echo never"}, // must not run
	}

	pr := RunPipeline("", "r2", steps, nil, workDir, artifactDir, "")
	if pr.Passed {
		t.Error("expected pipeline to fail")
	}
	if len(pr.Results) != 2 {
		t.Errorf("expected 2 results (stopped at block), got %d", len(pr.Results))
	}
}

func TestRunPipelineContinuesOnWarn(t *testing.T) {
	workDir := t.TempDir()
	artifactDir := t.TempDir()
	steps := []config.CheckStep{
		{Name: "warn", Run: "exit 1", OnFail: "warn"},
		{Name: "ok", Run: "echo ok"},
	}

	pr := RunPipeline("", "r3", steps, nil, workDir, artifactDir, "")
	if !pr.Passed {
		t.Error("expected pipeline to pass (all blocks pass, warn is ignored)")
	}
	if len(pr.Warnings) != 1 || pr.Warnings[0] != "warn" {
		t.Errorf("expected one warning 'warn', got %v", pr.Warnings)
	}
	if len(pr.Results) != 2 {
		t.Errorf("expected 2 results, got %d", len(pr.Results))
	}
}

// ── Path routing tests ─────────────────────────────────────────────────────────

func TestMatchGlobStar(t *testing.T) {
	cases := []struct {
		pattern string
		path    string
		want    bool
	}{
		{"docs/**", "docs/readme.md", true},
		{"docs/**", "docs/api/endpoints.md", true},
		{"docs/**", "src/main.go", false},
		{"*.md", "README.md", true},
		{"*.md", "docs/readme.md", true},
		{"*.md", "src/main.go", false},
		{"src/**", "src/foo/bar.go", true},
		{"src/**", "docs/foo.go", false},
		{"**/test_*.go", "internal/checks/test_foo.go", true},
		{"**/test_*.go", "main.go", false},
	}

	for _, tc := range cases {
		got := matchGlob(tc.pattern, tc.path)
		if got != tc.want {
			t.Errorf("matchGlob(%q, %q) = %v, want %v", tc.pattern, tc.path, got, tc.want)
		}
	}
}

func TestSkipForPathsDocsOnly(t *testing.T) {
	routing := map[string]config.PathRoutingRule{
		"docs_only": {
			Patterns: []string{"docs/**", "*.md"},
			Skip:     []string{"lint", "test"},
		},
	}

	// All docs → skip lint and test
	skip := SkipForPaths([]string{"docs/readme.md", "CHANGELOG.md"}, routing)
	if !skip["lint"] {
		t.Error("expected lint to be skipped")
	}
	if !skip["test"] {
		t.Error("expected test to be skipped")
	}

	// Mixed docs + source → nothing skipped
	skip2 := SkipForPaths([]string{"docs/readme.md", "src/main.go"}, routing)
	if skip2["lint"] || skip2["test"] {
		t.Error("expected no skips when source files are changed")
	}
}
