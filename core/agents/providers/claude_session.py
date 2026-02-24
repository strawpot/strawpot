from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from ..context import SessionContext
from ..session import AgentSession
from ..types import Charter

# Tools allowed by default when no charter override is set
_DEFAULT_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]


class ClaudeSessionProvider:
    """Spawns interactive Claude Code sessions in tmux.

    Each agent runs as ``claude --dangerously-skip-permissions`` inside a
    named tmux session. A ``SessionStart`` hook in ``.claude/settings.json``
    calls ``lt prime --hook``, which prints the charter instructions and skill
    files to stdout — Claude Code prepends this to the agent's context.

    Session naming: ``lt-<agent-name>``

    Usage::

        provider = ClaudeSessionProvider()
        session = await provider.spawn(charter, workdir=Path("worktrees/charlie"), context=ctx)
        session.attach()   # hand terminal to the agent
        # or
        await session.wait()
    """

    def __init__(self, claude_path: str | None = None) -> None:
        self._claude_path = claude_path or shutil.which("claude") or "claude"

    @property
    def name(self) -> str:
        return "claude_session"

    # ------------------------------------------------------------------
    # AgentSessionProvider interface
    # ------------------------------------------------------------------

    async def spawn(
        self,
        charter: Charter,
        workdir: Path,
        context: SessionContext,
    ) -> AgentSession:
        """Prepare the workdir and start a new tmux session for the agent."""
        session_name = self._session_name(charter.name)
        workdir = workdir.resolve()
        workdir.mkdir(parents=True, exist_ok=True)

        self._write_runtime(workdir, charter, context)
        self._write_claude_settings(workdir, charter)

        await self._start_tmux_session(session_name, workdir, charter)
        return AgentSession(session_name=session_name, workdir=workdir, charter=charter)

    async def resume(self, session_name: str, workdir: Path) -> AgentSession:
        """Re-attach to a paused or crashed session.

        If the tmux session no longer exists, a new one is created in the
        same workdir (Claude Code will resume via the stored session ID).
        """
        workdir = workdir.resolve()

        # Read charter from runtime state
        charter = self._read_charter(workdir)

        if not self._session_exists(session_name):
            await self._start_tmux_session(session_name, workdir, charter)

        return AgentSession(session_name=session_name, workdir=workdir, charter=charter)

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _write_runtime(self, workdir: Path, charter: Charter, context: SessionContext) -> None:
        """Write runtime files that ``lt prime --hook`` reads at session start."""
        runtime_dir = workdir / ".loguetown" / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)

        # Agent identity — used by lt prime to find the right charter
        (runtime_dir / "agent.json").write_text(
            json.dumps({"name": charter.name, "role": charter.role}, indent=2)
        )

        # Current work item (optional)
        if context.work:
            (runtime_dir / "work.txt").write_text(context.work)
        else:
            work_file = runtime_dir / "work.txt"
            if work_file.exists():
                work_file.unlink()

    def _write_claude_settings(self, workdir: Path, charter: Charter) -> None:
        """Write ``.claude/settings.json`` with the SessionStart hook."""
        claude_dir = workdir / ".claude"
        claude_dir.mkdir(exist_ok=True)

        settings = {
            "permissions": {
                "allow": charter.allowed_tools or _DEFAULT_TOOLS,
            },
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "lt prime --hook",
                            }
                        ]
                    }
                ]
            },
        }
        (claude_dir / "settings.json").write_text(json.dumps(settings, indent=2))

    async def _start_tmux_session(
        self,
        session_name: str,
        workdir: Path,
        charter: Charter,
    ) -> None:
        cmd = [
            "tmux", "new-session",
            "-d",                        # detached
            "-s", session_name,
            "-c", str(workdir),          # working directory
            self._claude_path,
            "--dangerously-skip-permissions",
        ]
        if charter.model_id:
            cmd.extend(["--model", charter.model_id])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Failed to start tmux session {session_name!r}: "
                f"{stderr.decode().strip()}"
            )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _session_name(agent_name: str) -> str:
        return f"lt-{agent_name}"

    @staticmethod
    def _session_exists(session_name: str) -> bool:
        import subprocess
        r = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True,
        )
        return r.returncode == 0

    @staticmethod
    def _read_charter(workdir: Path) -> Charter:
        """Reconstruct a minimal Charter from the saved runtime identity."""
        agent_json = workdir / ".loguetown" / "runtime" / "agent.json"
        if not agent_json.exists():
            raise FileNotFoundError(
                f"No runtime identity found at {agent_json}. "
                "Was this workdir created by ClaudeSessionProvider.spawn()?"
            )
        data = json.loads(agent_json.read_text())

        # Prefer a full charter YAML if it exists
        charter_path = workdir / ".loguetown" / "agents" / f"{data['name']}.yaml"
        if charter_path.exists():
            return Charter.from_yaml(charter_path)

        # Fall back to a bare charter from the runtime JSON
        from ..types import ModelConfig
        return Charter(
            name=data["name"],
            role=data["role"],
            model=ModelConfig(provider="claude_session"),
        )
