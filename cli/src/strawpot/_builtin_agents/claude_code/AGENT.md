---
name: claude-code
description: Claude Code agent
metadata:
  version: "0.1.0"
  strawpot:
    bin:
      macos: strawpot_claude_code
      linux: strawpot_claude_code
    tools:
      claude:
        description: Claude Code CLI
        install:
          macos: npm install -g @anthropic-ai/claude-code
          linux: npm install -g @anthropic-ai/claude-code
    params:
      model:
        type: string
        default: claude-sonnet-4-6
        description: Model to use for Claude Code
    env:
      ANTHROPIC_API_KEY:
        required: false
        description: Anthropic API key (optional if using Plus/Max plan)
---

# Claude Code Agent

Runs Claude Code as a subprocess. Supports interactive and non-interactive
modes, custom model selection, and skill-based prompt augmentation.
