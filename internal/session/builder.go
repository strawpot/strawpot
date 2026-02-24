// Package session assembles the system prompt for an agent run from role
// definition, retrieved skill chunks, and retrieved memory chunks.
package session

import (
	"fmt"
	"strings"

	"github.com/juhgiyo/loguetown/internal/agents"
	"github.com/juhgiyo/loguetown/internal/embeddings"
	"github.com/juhgiyo/loguetown/internal/memory"
	"github.com/juhgiyo/loguetown/internal/skills"
)

// Session holds the assembled system prompt and metadata for one agent run.
type Session struct {
	AgentName    string
	Role         string
	SystemPrompt string
	SkillsUsed   int
	MemoryUsed   int
}

// Config controls how skills and memory are retrieved.
type Config struct {
	SkillTopK     int
	SkillMinSim   float32
	MemoryTopK    int
	MemoryMinSim  float32
	WorkDir       string // worktree or repo path shown in prompt
	ProjectID     string // used to scope semantic_local and episodic retrieval
	AgentName     string // used to scope agent-scoped episodic memory retrieval
	ProjectName   string
	DefaultBranch string
	Branch        string // current run branch
}

// Build assembles the system prompt for an agent run.
// charter must be resolved (i.e. loaded via agents.Load).
// task is the natural-language task description.
// embProvider may be nil; when nil, skills and memory retrieval are skipped.
func Build(charter *agents.Charter, task string, cfg Config, embProvider embeddings.Provider) (*Session, error) {
	var sb strings.Builder
	skillsUsed, memoryUsed := 0, 0

	// ── Identity ──────────────────────────────────────────────────────────────
	sb.WriteString("## Identity\n\n")
	sb.WriteString(fmt.Sprintf("You are **%s**, acting as **%s**.\n\n",
		charter.Name, charter.Role))

	// ── Tools ─────────────────────────────────────────────────────────────────
	if charter.ResolvedTools != nil && len(charter.ResolvedTools.Allowed) > 0 {
		sb.WriteString("## Allowed Tools\n\n")
		sb.WriteString(strings.Join(charter.ResolvedTools.Allowed, ", ") + "\n\n")
		if len(charter.ResolvedTools.BashAllowlist) > 0 {
			sb.WriteString("**Bash allowlist** (only these patterns may be executed):\n")
			for _, p := range charter.ResolvedTools.BashAllowlist {
				sb.WriteString("- " + p + "\n")
			}
			sb.WriteString("\n")
		}
	}

	// ── Skills ────────────────────────────────────────────────────────────────
	if embProvider != nil && task != "" {
		topK := cfg.SkillTopK
		if topK <= 0 {
			topK = 5
		}
		minSim := cfg.SkillMinSim
		if minSim <= 0 {
			minSim = 0.2
		}
		results, err := skills.Search(task, embProvider, topK, minSim)
		if err == nil && len(results) > 0 {
			sb.WriteString("## Relevant Skills\n\n")
			for _, r := range results {
				heading := r.Title
				if heading == "" {
					heading = r.FilePath
				}
				sb.WriteString(fmt.Sprintf("### %s\n\n", heading))
				if r.Content != "" {
					sb.WriteString(r.Content + "\n\n")
				}
			}
			skillsUsed = len(results)
		}
	}

	// ── Memory ────────────────────────────────────────────────────────────────
	if embProvider != nil && task != "" {
		topK := cfg.MemoryTopK
		if topK <= 0 {
			topK = 5
		}
		minSim := cfg.MemoryMinSim
		if minSim <= 0 {
			minSim = 0.3
		}

		layers := []struct {
			name      string
			heading   string
			projectID string // empty = global (no project filter)
			agentName string // non-empty for agent-scoped episodic retrieval
		}{
			{"semantic_global", "Cross-Project Knowledge", "", ""},
			{"semantic_local", "Project Knowledge", cfg.ProjectID, ""},
			{"episodic", "Past Experiences", cfg.ProjectID, cfg.AgentName},
		}

		for _, l := range layers {
			chunks, err := memory.Retrieve(l.name, l.projectID, l.agentName, task, topK, float32(minSim), embProvider)
			if err != nil || len(chunks) == 0 {
				continue
			}
			if memoryUsed == 0 {
				sb.WriteString("## Memory\n\n")
			}
			sb.WriteString(fmt.Sprintf("### %s\n\n", l.heading))
			for _, c := range chunks {
				if c.Title != "" {
					sb.WriteString(fmt.Sprintf("**%s**\n\n", c.Title))
				}
				if c.Content != "" {
					sb.WriteString(c.Content + "\n\n")
				}
			}
			memoryUsed += len(chunks)
		}
	}

	// ── Repository Context ────────────────────────────────────────────────────
	sb.WriteString("## Repository Context\n\n")
	if cfg.ProjectName != "" {
		sb.WriteString(fmt.Sprintf("Project: **%s**\n", cfg.ProjectName))
	}
	if cfg.WorkDir != "" {
		sb.WriteString(fmt.Sprintf("Working directory: `%s`\n", cfg.WorkDir))
	}
	if cfg.Branch != "" {
		sb.WriteString(fmt.Sprintf("Branch: `%s`\n", cfg.Branch))
	}
	if cfg.DefaultBranch != "" {
		sb.WriteString(fmt.Sprintf("Default branch: `%s`\n", cfg.DefaultBranch))
	}
	sb.WriteString("\n")

	// ── Guidelines ────────────────────────────────────────────────────────────
	sb.WriteString("## Guidelines\n\n")
	sb.WriteString("- Work entirely within the provided working directory.\n")
	sb.WriteString("- Only run bash commands that match the allowlist patterns above.\n")
	sb.WriteString("- Commit your changes with clear, descriptive commit messages.\n")
	sb.WriteString("- When the task is complete, stop. Do not add unrequested features.\n\n")

	return &Session{
		AgentName:    charter.Name,
		Role:         charter.Role,
		SystemPrompt: strings.TrimSpace(sb.String()),
		SkillsUsed:   skillsUsed,
		MemoryUsed:   memoryUsed,
	}, nil
}
