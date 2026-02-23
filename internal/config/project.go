package config

import (
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// Project holds the parsed .loguetown/project.yaml.
type Project struct {
	Project struct {
		ID            string `yaml:"id" json:"id"`
		Name          string `yaml:"name" json:"name"`
		RepoPat       string `yaml:"repo_path" json:"repo_path"`
		DefaultBranch string `yaml:"default_branch" json:"default_branch"`
	} `yaml:"project" json:"project"`
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
