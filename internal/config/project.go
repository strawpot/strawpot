package config

import (
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// EmbeddingsConfig configures the embedding provider used for skills and memory.
type EmbeddingsConfig struct {
	Provider   string `yaml:"provider" json:"provider"`           // ollama | openai
	Model      string `yaml:"model" json:"model"`
	BaseURL    string `yaml:"base_url,omitempty" json:"base_url,omitempty"`
	Dimensions int    `yaml:"dimensions" json:"dimensions"`
	APIKey     string `yaml:"api_key,omitempty" json:"api_key,omitempty"`
}

// MemoryRetrievalConfig controls vector search parameters.
type MemoryRetrievalConfig struct {
	TopK          int     `yaml:"top_k" json:"top_k"`
	MinSimilarity float64 `yaml:"min_similarity" json:"min_similarity"`
}

// EpisodicRetentionConfig controls how long episodic memories are kept.
type EpisodicRetentionConfig struct {
	MaxEntries int `yaml:"max_entries" json:"max_entries"`
	MaxDays    int `yaml:"max_days" json:"max_days"`
}

// MemoryConfig configures memory storage and retrieval.
type MemoryConfig struct {
	EpisodicRetention EpisodicRetentionConfig `yaml:"episodic_retention" json:"episodic_retention"`
	Retrieval         MemoryRetrievalConfig   `yaml:"retrieval" json:"retrieval"`
	MaxTokensInjected int                     `yaml:"max_tokens_injected" json:"max_tokens_injected"`
}

// RunnerConfig configures the agent execution provider.
type RunnerConfig struct {
	Provider       string `yaml:"provider" json:"provider"`                 // claude-code | anthropic-api
	Model          string `yaml:"model,omitempty" json:"model,omitempty"`   // for anthropic-api
	APIKey         string `yaml:"api_key,omitempty" json:"api_key,omitempty"` // or ANTHROPIC_API_KEY
	MaxTurns       int    `yaml:"max_turns" json:"max_turns"`               // agentic loop cap
	TimeoutMinutes int    `yaml:"timeout_minutes" json:"timeout_minutes"`
}

// Project holds the parsed .loguetown/project.yaml.
type Project struct {
	Project struct {
		ID            string `yaml:"id" json:"id"`
		Name          string `yaml:"name" json:"name"`
		RepoPat       string `yaml:"repo_path" json:"repo_path"`
		DefaultBranch string `yaml:"default_branch" json:"default_branch"`
	} `yaml:"project" json:"project"`
	Embeddings EmbeddingsConfig `yaml:"embeddings" json:"embeddings"`
	Memory     MemoryConfig     `yaml:"memory" json:"memory"`
	Runner     RunnerConfig     `yaml:"runner" json:"runner"`
}

// FindProjectPath walks up from startDir looking for .loguetown/project.yaml.
// Returns the directory containing .loguetown/, or "" if not found.
func FindProjectPath(startDir string) string {
	dir := startDir
	for {
		if _, err := os.Stat(filepath.Join(dir, ".loguetown", "project.yaml")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return ""
		}
		dir = parent
	}
}

// FindGitRoot walks up from startDir looking for a .git directory.
func FindGitRoot(startDir string) string {
	dir := startDir
	for {
		if _, err := os.Stat(filepath.Join(dir, ".git")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return ""
		}
		dir = parent
	}
}

// LoadProject reads and parses the project config.
func LoadProject(projectPath string) (*Project, error) {
	path := filepath.Join(projectPath, ".loguetown", "project.yaml")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read project.yaml: %w", err)
	}

	var p Project
	if err := yaml.Unmarshal(data, &p); err != nil {
		return nil, fmt.Errorf("parse project.yaml: %w", err)
	}
	return &p, nil
}
