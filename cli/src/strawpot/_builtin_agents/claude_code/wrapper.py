#!/usr/bin/env python3
"""Claude Code wrapper — translates StrawPot protocol to Claude Code CLI.

This wrapper runs Claude Code inside tmux sessions, mapping protocol args
to ``claude`` CLI flags.  It is the default (built-in) wrapper and serves
as a reference implementation for other wrapper authors.

Subcommands: setup, spawn, wait, alive, kill
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

APPROVAL_MODE_MAP = {
    "auto": "auto",
    "suggest": "default",
    "force": "plan",
}


def _session_name(agent_id: str) -> str:
    """Derive a tmux session name from the agent id."""
    return f"strawpot-{agent_id[:8]}"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, raising on failure."""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_setup(args: argparse.Namespace) -> None:
    """Ensure Claude Code is authenticated and ready.

    Runs ``claude /login`` interactively so the user can complete the
    OAuth flow (for Plus/Max plans) or verify their API key.  This is a
    one-time operation — subsequent spawns skip it.
    """
    import shutil

    claude = shutil.which("claude")
    if claude is None:
        print("Error: claude CLI not found on PATH.", file=sys.stderr)
        print(
            "Install it with: npm install -g @anthropic-ai/claude-code",
            file=sys.stderr,
        )
        sys.exit(1)

    # Run interactive login — stdin/stdout pass through to the user
    result = subprocess.run(
        [claude, "/login"],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    sys.exit(result.returncode)


def cmd_spawn(args: argparse.Namespace) -> None:
    """Start a Claude Code session inside tmux."""
    config = json.loads(args.config) if args.config else {}
    model = config.get("model")
    session = _session_name(args.agent_id)

    # --- Build system prompt file ---
    runtime_dir = os.path.join(args.working_dir, ".strawpot", "runtime")
    os.makedirs(runtime_dir, exist_ok=True)
    prompt_file = os.path.join(runtime_dir, f"{args.agent_id}-prompt.md")

    parts = []
    if args.role_prompt:
        parts.append(args.role_prompt)
    if args.memory_prompt:
        parts.append(args.memory_prompt)
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write("\n\n".join(parts) if parts else "")

    # --- Build claude command ---
    claude_cmd: list[str] = ["claude"]

    if args.task:
        claude_cmd += ["-p", args.task]

    claude_cmd += ["--system-prompt", prompt_file]

    if model:
        claude_cmd += ["--model", model]

    # Approval mode from environment
    approval_mode = os.environ.get("APPROVAL_MODE", "suggest")
    permission_mode = APPROVAL_MODE_MAP.get(approval_mode, "default")
    claude_cmd += ["--permission-mode", permission_mode]

    # Append skill prompts
    for skills_dir in args.skills_dirs:
        for skill_file in sorted(glob.glob(os.path.join(skills_dir, "*.md"))):
            claude_cmd += ["--append-system-prompt", skill_file]

    # --- Launch in tmux ---
    tmux_cmd = [
        "tmux", "new-session",
        "-d",
        "-s", session,
        "-c", args.working_dir,
        "--", *claude_cmd,
    ]
    result = _run(tmux_cmd)
    if result.returncode != 0:
        print(
            json.dumps({"error": f"tmux failed: {result.stderr.strip()}"}),
            file=sys.stderr,
        )
        sys.exit(1)

    # Get tmux server PID
    pid_result = _run(["tmux", "display-message", "-p", "#{pid}"])
    pid = int(pid_result.stdout.strip()) if pid_result.returncode == 0 else None

    print(json.dumps({"pid": pid, "metadata": {"session": session}}))


def cmd_wait(args: argparse.Namespace) -> None:
    """Poll until the tmux session exits, then return captured output."""
    session = _session_name(args.agent_id)
    timeout = args.timeout
    elapsed = 0.0
    poll_interval = 1.0

    while True:
        result = _run(["tmux", "has-session", "-t", session])
        if result.returncode != 0:
            break
        if timeout is not None and elapsed >= timeout:
            break
        time.sleep(poll_interval)
        elapsed += poll_interval

    # Capture whatever output remains in the pane
    capture = _run(["tmux", "capture-pane", "-t", session, "-p"])
    output = capture.stdout if capture.returncode == 0 else ""

    print(
        json.dumps({
            "summary": "Session ended",
            "output": output,
            "exit_code": 0,
        })
    )


def cmd_alive(args: argparse.Namespace) -> None:
    """Check if the tmux session is still running."""
    session = _session_name(args.agent_id)
    result = _run(["tmux", "has-session", "-t", session])
    print(json.dumps({"alive": result.returncode == 0}))


def cmd_kill(args: argparse.Namespace) -> None:
    """Kill the tmux session."""
    session = _session_name(args.agent_id)
    _run(["tmux", "kill-session", "-t", session])
    print(json.dumps({"killed": True}))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Entry point for the Claude Code wrapper CLI."""
    parser = argparse.ArgumentParser(
        description="Claude Code wrapper for StrawPot"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- setup --
    subparsers.add_parser("setup")

    # -- spawn --
    sp = subparsers.add_parser("spawn")
    sp.add_argument("--agent-id", required=True)
    sp.add_argument("--working-dir", required=True)
    sp.add_argument("--role-prompt", default="")
    sp.add_argument("--memory-prompt", default="")
    sp.add_argument("--task", default="")
    sp.add_argument("--config", default="{}")
    sp.add_argument("--skills-dir", dest="skills_dirs", action="append", default=[])
    sp.add_argument("--roles-dir", dest="roles_dirs", action="append", default=[])

    # -- wait --
    wp = subparsers.add_parser("wait")
    wp.add_argument("--agent-id", required=True)
    wp.add_argument("--timeout", type=float, default=None)

    # -- alive --
    ap = subparsers.add_parser("alive")
    ap.add_argument("--agent-id", required=True)

    # -- kill --
    kp = subparsers.add_parser("kill")
    kp.add_argument("--agent-id", required=True)

    parsed = parser.parse_args(argv)

    dispatch = {
        "setup": cmd_setup,
        "spawn": cmd_spawn,
        "wait": cmd_wait,
        "alive": cmd_alive,
        "kill": cmd_kill,
    }
    dispatch[parsed.command](parsed)


if __name__ == "__main__":
    main()
