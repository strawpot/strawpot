package checks

import (
	"bytes"
	"os/exec"
	"path"
	"path/filepath"
	"strings"

	"github.com/juhgiyo/loguetown/internal/config"
)

// PipelineResult is the combined outcome of running multiple check steps.
type PipelineResult struct {
	Results  []Result
	Passed   bool     // false if any blocking check failed
	Warnings []string // names of warn-only checks that failed
}

// RunPipeline runs all steps in order inside workDir.
// Steps whose names appear in the skip set (derived from path routing) are
// recorded as skipped rather than executed. The pipeline stops at the first
// blocking failure unless all failures are warn-only.
//
// baseSHA is used to determine which files changed (for path routing). Pass ""
// to disable path routing.
func RunPipeline(projectID, runID string, steps []config.CheckStep, routing map[string]config.PathRoutingRule, workDir, artifactDir, baseSHA string) PipelineResult {
	skip := computeSkipSet(workDir, baseSHA, routing)

	pr := PipelineResult{Passed: true}

	for _, step := range steps {
		if skip[step.Name] {
			pr.Results = append(pr.Results, Result{Name: step.Name, Skipped: true, Passed: true})
			continue
		}

		r := Run(projectID, runID, step, workDir, artifactDir)
		pr.Results = append(pr.Results, r)

		if !r.Passed {
			if r.Blocking {
				pr.Passed = false
				break // stop at first blocking failure
			}
			pr.Warnings = append(pr.Warnings, step.Name)
		}
	}
	return pr
}

// computeSkipSet returns the set of check names to skip based on path routing.
// Returns an empty map when baseSHA is "" or git diff fails.
func computeSkipSet(workDir, baseSHA string, routing map[string]config.PathRoutingRule) map[string]bool {
	if baseSHA == "" || len(routing) == 0 {
		return map[string]bool{}
	}
	changed, err := ChangedPaths(workDir, baseSHA)
	if err != nil || len(changed) == 0 {
		return map[string]bool{}
	}
	return SkipForPaths(changed, routing)
}

// ChangedPaths returns the list of files changed between baseSHA and HEAD in workDir.
func ChangedPaths(workDir, baseSHA string) ([]string, error) {
	var out bytes.Buffer
	cmd := exec.Command("git", "diff", "--name-only", baseSHA, "HEAD")
	cmd.Dir = workDir
	cmd.Stdout = &out
	if err := cmd.Run(); err != nil {
		return nil, err
	}
	var paths []string
	for _, line := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		if line != "" {
			paths = append(paths, line)
		}
	}
	return paths, nil
}

// SkipForPaths returns the set of check names to skip given the changed files.
// A routing rule applies (and its skips are applied) only when ALL changed
// files match at least one of the rule's patterns.
func SkipForPaths(changedPaths []string, routing map[string]config.PathRoutingRule) map[string]bool {
	skip := map[string]bool{}
	for _, rule := range routing {
		if len(changedPaths) == 0 {
			continue
		}
		allMatch := true
		for _, fp := range changedPaths {
			if !matchesAnyPattern(fp, rule.Patterns) {
				allMatch = false
				break
			}
		}
		if allMatch {
			for _, name := range rule.Skip {
				skip[name] = true
			}
		}
	}
	return skip
}

// matchesAnyPattern returns true if filePath matches any of the given patterns.
func matchesAnyPattern(filePath string, patterns []string) bool {
	for _, pattern := range patterns {
		if matchGlob(pattern, filePath) {
			return true
		}
	}
	return false
}

// matchGlob returns true if filePath matches the glob pattern.
// Supports:
//   - "dir/**"   → any file under dir/
//   - "**/*.go"  → any .go file at any depth
//   - "*.md"     → any .md file (matched against base name)
//   - "README*"  → base name starts with README
func matchGlob(pattern, filePath string) bool {
	pattern = filepath.ToSlash(pattern)
	filePath = filepath.ToSlash(filePath)

	// "dir/**" — any file directly or transitively under dir/
	if strings.HasSuffix(pattern, "/**") {
		dir := strings.TrimSuffix(pattern, "/**")
		return strings.HasPrefix(filePath, dir+"/")
	}

	// "**/<suffix>" — suffix matches anywhere in the path
	if strings.HasPrefix(pattern, "**/") {
		suffix := strings.TrimPrefix(pattern, "**/")
		if m, _ := path.Match(suffix, path.Base(filePath)); m {
			return true
		}
		if m, _ := path.Match(suffix, filePath); m {
			return true
		}
		// Check each path tail (e.g. "a/b/c" tails: "a/b/c", "b/c", "c")
		parts := strings.Split(filePath, "/")
		for i := range parts {
			sub := strings.Join(parts[i:], "/")
			if m, _ := path.Match(suffix, sub); m {
				return true
			}
		}
		return false
	}

	// No slash in pattern → match against base name only (e.g. "*.md")
	if !strings.Contains(pattern, "/") {
		m, _ := path.Match(pattern, path.Base(filePath))
		return m
	}

	// Full-path glob match
	m, _ := path.Match(pattern, filePath)
	return m
}
