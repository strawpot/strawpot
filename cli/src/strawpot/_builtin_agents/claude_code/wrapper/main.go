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
	AgentID           string
	WorkingDir        string
	AgentWorkspaceDir string
	RolePrompt        string
	MemoryPrompt      string
	Task              string
	Config            string
	SkillsDirs        []string
	RolesDirs         []string
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
		case "--agent-workspace-dir":
			i++
			ba.AgentWorkspaceDir = args[i]
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

	// Validate required args
	if ba.AgentWorkspaceDir == "" {
		fmt.Fprintln(os.Stderr, "Error: --agent-workspace-dir is required")
		os.Exit(1)
	}

	// Create claude/ folder structure inside agent workspace dir.
	// This becomes the single --add-dir for Claude Code.
	claudeDir := filepath.Join(ba.AgentWorkspaceDir, "claude")
	if err := os.MkdirAll(claudeDir, 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to create claude dir: %v\n", err)
		os.Exit(1)
	}

	// Write prompt file into claude/
	promptFile := filepath.Join(claudeDir, "prompt.md")
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

	// Symlink each skills-dir into claude/.claude/skills/<name>/
	if len(ba.SkillsDirs) > 0 {
		skillsTarget := filepath.Join(claudeDir, ".claude", "skills")
		if err := os.MkdirAll(skillsTarget, 0o755); err != nil {
			fmt.Fprintf(os.Stderr, "Failed to create skills dir: %v\n", err)
			os.Exit(1)
		}
		for _, d := range ba.SkillsDirs {
			name := filepath.Base(d)
			link := filepath.Join(skillsTarget, name)
			if err := os.Symlink(d, link); err != nil {
				fmt.Fprintf(os.Stderr, "Failed to symlink skill %s: %v\n", name, err)
				os.Exit(1)
			}
		}
	}

	// Symlink each roles-dir into claude/roles/<name>/
	if len(ba.RolesDirs) > 0 {
		rolesTarget := filepath.Join(claudeDir, "roles")
		if err := os.MkdirAll(rolesTarget, 0o755); err != nil {
			fmt.Fprintf(os.Stderr, "Failed to create roles dir: %v\n", err)
			os.Exit(1)
		}
		for _, d := range ba.RolesDirs {
			name := filepath.Base(d)
			link := filepath.Join(rolesTarget, name)
			if err := os.Symlink(d, link); err != nil {
				fmt.Fprintf(os.Stderr, "Failed to symlink role %s: %v\n", name, err)
				os.Exit(1)
			}
		}
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

	// Single --add-dir pointing to the claude/ folder.
	// Claude Code discovers .claude/skills/ within it natively.
	cmd = append(cmd, "--add-dir", claudeDir)

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
