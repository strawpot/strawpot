// Claude Code wrapper — translates StrawPot protocol to Claude Code CLI.
//
// This wrapper is a pure translation layer: it maps StrawPot protocol args
// to "claude" CLI flags.  It does NOT manage processes, sessions, or any
// infrastructure — that is handled by WrapperRuntime in StrawPot core.
//
// Subcommands: setup, build
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "Usage: wrapper <setup|build> [args...]")
		os.Exit(1)
	}

	switch os.Args[1] {
	case "setup":
		cmdSetup()
	case "build":
		cmdBuild(os.Args[2:])
	default:
		fmt.Fprintf(os.Stderr, "Unknown subcommand: %s\n", os.Args[1])
		os.Exit(1)
	}
}

// ---------------------------------------------------------------------------
// setup
// ---------------------------------------------------------------------------

func cmdSetup() {
	claudePath, err := exec.LookPath("claude")
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error: claude CLI not found on PATH.")
		fmt.Fprintln(os.Stderr, "Install it with: npm install -g @anthropic-ai/claude-code")
		os.Exit(1)
	}

	cmd := exec.Command(claudePath, "/login")
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			os.Exit(exitErr.ExitCode())
		}
		os.Exit(1)
	}
}

// ---------------------------------------------------------------------------
// build
// ---------------------------------------------------------------------------

type buildArgs struct {
	AgentID      string
	WorkingDir   string
	RolePrompt   string
	MemoryPrompt string
	Task         string
	Config       string
	SkillsDirs   []string
	RolesDirs    []string
}

func parseBuildArgs(args []string) buildArgs {
	var ba buildArgs
	ba.Config = "{}"

	for i := 0; i < len(args); i++ {
		if i+1 >= len(args) {
			break
		}
		switch args[i] {
		case "--agent-id":
			i++
			ba.AgentID = args[i]
		case "--working-dir":
			i++
			ba.WorkingDir = args[i]
		case "--role-prompt":
			i++
			ba.RolePrompt = args[i]
		case "--memory-prompt":
			i++
			ba.MemoryPrompt = args[i]
		case "--task":
			i++
			ba.Task = args[i]
		case "--config":
			i++
			ba.Config = args[i]
		case "--skills-dir":
			i++
			ba.SkillsDirs = append(ba.SkillsDirs, args[i])
		case "--roles-dir":
			i++
			ba.RolesDirs = append(ba.RolesDirs, args[i])
		}
	}
	return ba
}

func cmdBuild(args []string) {
	ba := parseBuildArgs(args)

	// Parse config JSON
	var config map[string]interface{}
	if err := json.Unmarshal([]byte(ba.Config), &config); err != nil {
		config = map[string]interface{}{}
	}

	// Write system prompt file
	runtimeDir := filepath.Join(ba.WorkingDir, ".strawpot", "runtime")
	if err := os.MkdirAll(runtimeDir, 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to create runtime dir: %v\n", err)
		os.Exit(1)
	}

	promptFile := filepath.Join(runtimeDir, ba.AgentID+"-prompt.md")
	var parts []string
	if ba.RolePrompt != "" {
		parts = append(parts, ba.RolePrompt)
	}
	if ba.MemoryPrompt != "" {
		parts = append(parts, ba.MemoryPrompt)
	}
	if err := os.WriteFile(promptFile, []byte(strings.Join(parts, "\n\n")), 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to write prompt file: %v\n", err)
		os.Exit(1)
	}

	// Build claude command
	cmd := []string{"claude"}

	if ba.Task != "" {
		cmd = append(cmd, "-p", ba.Task)
	}

	cmd = append(cmd, "--system-prompt", promptFile)

	if model, ok := config["model"].(string); ok && model != "" {
		cmd = append(cmd, "--model", model)
	}

	if pm := os.Getenv("PERMISSION_MODE"); pm != "" {
		cmd = append(cmd, "--permission-mode", pm)
	}

	// Append skill prompts (sorted glob of *.md files)
	for _, skillsDir := range ba.SkillsDirs {
		pattern := filepath.Join(skillsDir, "*.md")
		matches, err := filepath.Glob(pattern)
		if err != nil {
			continue
		}
		sort.Strings(matches)
		for _, m := range matches {
			cmd = append(cmd, "--append-system-prompt", m)
		}
	}

	// Output JSON
	result := map[string]interface{}{
		"cmd": cmd,
		"cwd": ba.WorkingDir,
	}

	enc := json.NewEncoder(os.Stdout)
	if err := enc.Encode(result); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to encode JSON: %v\n", err)
		os.Exit(1)
	}
}
