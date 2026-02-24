"""lt prime — SessionStart hook for Strawpot agents.

Called by Claude Code's ``SessionStart`` hook::

    # .claude/settings.json
    {
      "hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": "lt prime --hook"}]}]
      }
    }

Claude Code pipes a JSON object to stdin::

    {"session_id": "...", "transcript_path": "...", "source": "startup|resume|compact|clear"}

``lt prime --hook`` reads this, builds the session context from the charter
and skills directory, and prints the formatted markdown to stdout. Claude Code
prepends that output to the agent's context window.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .agents.context import ContextBuilder, SessionContext
from .agents.types import Charter
from .skills.manager import SkillManager


# ---------------------------------------------------------------------------
# Core logic (importable for testing)
# ---------------------------------------------------------------------------


def build_prime_output(workdir: Path, hook_input: dict | None = None) -> str:
    """Build the context string that gets injected at session start.

    Args:
        workdir:    The agent's working directory (where .strawpot/ lives).
        hook_input: Parsed JSON from Claude Code's SessionStart hook stdin.
                    May be None when called outside hook context (e.g. tests).
    """
    runtime_dir = workdir / ".strawpot" / "runtime"

    # --- Resolve charter ---------------------------------------------------
    agent_json = runtime_dir / "agent.json"
    if not agent_json.exists():
        return "# Strawpot\n\nNo agent identity found in this directory."

    identity = json.loads(agent_json.read_text())
    agent_name: str = identity["name"]
    agent_role: str = identity["role"]

    # Prefer full charter YAML; fall back to bare charter from runtime JSON
    charter_path = workdir / ".strawpot" / "agents" / f"{agent_name}.yaml"
    if charter_path.exists():
        charter = Charter.from_yaml(charter_path)
    else:
        from .agents.types import ModelConfig
        charter = Charter(
            name=agent_name,
            role=agent_role,
            model=ModelConfig(provider="claude_session"),
        )

    # --- Resolve skill pools -----------------------------------------------
    skill_pools = SkillManager.from_charter(charter, workdir=workdir).pools()

    # --- Load current work -------------------------------------------------
    work_file = runtime_dir / "work.txt"
    work = work_file.read_text().strip() if work_file.exists() else None

    # --- Persist session ID (for resume support) ---------------------------
    if hook_input and hook_input.get("session_id"):
        session_file = runtime_dir / "session.json"
        session_file.write_text(
            json.dumps(
                {
                    "session_id": hook_input["session_id"],
                    "source": hook_input.get("source", "startup"),
                    "transcript_path": hook_input.get("transcript_path"),
                },
                indent=2,
            )
        )

    # --- Build and return context ------------------------------------------
    ctx = SessionContext(charter=charter, skill_pools=skill_pools, work=work)
    return ContextBuilder().build(ctx)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the ``lt prime`` command."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="lt prime",
        description="Print session context for injection via the SessionStart hook.",
    )
    parser.add_argument(
        "--hook",
        action="store_true",
        help="Hook mode: read SessionStart JSON from stdin.",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Working directory (default: current directory).",
    )
    args = parser.parse_args()

    workdir = (args.workdir or Path.cwd()).resolve()

    hook_input: dict | None = None
    if args.hook:
        raw = sys.stdin.read().strip()
        if raw:
            try:
                hook_input = json.loads(raw)
            except json.JSONDecodeError:
                pass  # non-fatal; context is still built without session metadata

    output = build_prime_output(workdir=workdir, hook_input=hook_input)
    print(output)
