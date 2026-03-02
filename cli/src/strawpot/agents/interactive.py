"""Interactive runtimes — terminal-attached orchestrator sessions.

Used only for the orchestrator agent that needs an interactive terminal
session.  Sub-agents (delegated tasks) use WrapperRuntime directly.

Two implementations are provided:

* **InteractiveWrapperRuntime** — wraps any WrapperRuntime with tmux.
  Supports detach/reattach but requires tmux (macOS / Linux only).
* **DirectWrapperRuntime** — cross-platform fallback that runs the agent
  process directly attached to the current terminal.  No detach/reattach,
  but works everywhere including Windows and minimal containers.
"""

import json
import os
import subprocess
import sys
import time

from strawpot.agents.protocol import AgentHandle, AgentResult
from strawpot.agents.wrapper import WrapperRuntime


def _tmux(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a tmux command."""
    return subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        **kwargs,
    )


def _session_name(agent_id: str) -> str:
    """Derive a tmux session name from the agent id."""
    return f"strawpot-{agent_id[:8]}"


class InteractiveWrapperRuntime:
    """Wraps a WrapperRuntime with tmux session management.

    Instead of calling ``<wrapper> spawn`` (which launches a background
    process), this runtime:

    1. Calls ``<wrapper> build`` to get the translated agent command.
    2. Launches that command inside a tmux session.
    3. Manages the tmux session lifecycle (wait, alive, kill).

    .. note::

        Requires tmux (macOS / Linux only).  On Windows and environments
        without tmux, use ``DirectWrapperRuntime`` instead.  The CLI
        auto-selects the appropriate runtime via ``shutil.which("tmux")``.

    Attributes:
        name: Agent name (delegated from the inner runtime).
    """

    def __init__(self, inner: WrapperRuntime) -> None:
        self.inner = inner
        self.name = inner.name

    def spawn(
        self,
        *,
        agent_id: str,
        working_dir: str,
        agent_workspace_dir: str,
        role_prompt: str,
        memory_prompt: str,
        skills_dir: str,
        roles_dirs: list[str],
        task: str,
        env: dict[str, str],
    ) -> AgentHandle:
        """Start the agent inside a tmux session.

        Calls ``<wrapper> build`` to get the agent command, then wraps
        it in ``tmux new-session``.
        """
        # 1. Call <wrapper> build to get the translated command
        args: list[str] = [
            "build",
            "--agent-id", agent_id,
            "--working-dir", working_dir,
            "--agent-workspace-dir", agent_workspace_dir,
            "--role-prompt", role_prompt,
            "--memory-prompt", memory_prompt,
            "--task", task,
            "--config", json.dumps(self.inner.spec.config),
            "--skills-dir", skills_dir,
        ]
        for rd in roles_dirs:
            args.extend(["--roles-dir", rd])

        data = self.inner._run_subcommand(args, extra_env=env)
        agent_cmd = data["cmd"]
        cwd = data.get("cwd", working_dir)

        # 2. Launch in tmux
        session = _session_name(agent_id)
        tmux_cmd = [
            "tmux", "new-session",
            "-d",
            "-s", session,
            "-c", cwd,
            "--", *agent_cmd,
        ]
        full_env = {**os.environ, **env} if env else None
        result = subprocess.run(
            tmux_cmd, capture_output=True, text=True, env=full_env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"tmux new-session failed: {result.stderr.strip()}"
            )

        # Get tmux server PID
        pid_result = _tmux(["display-message", "-p", "#{pid}"])
        pid = (
            int(pid_result.stdout.strip())
            if pid_result.returncode == 0
            else None
        )

        return AgentHandle(
            agent_id=agent_id,
            runtime_name=self.name,
            pid=pid,
            metadata={"session": session},
        )

    def wait(
        self, handle: AgentHandle, timeout: float | None = None
    ) -> AgentResult:
        """Poll until the tmux session exits, then capture output."""
        session = handle.metadata.get(
            "session", _session_name(handle.agent_id)
        )
        elapsed = 0.0
        poll_interval = 1.0

        while True:
            result = _tmux(["has-session", "-t", session])
            if result.returncode != 0:
                break
            if timeout is not None and elapsed >= timeout:
                break
            time.sleep(poll_interval)
            elapsed += poll_interval

        # Capture whatever output remains in the pane
        capture = _tmux(["capture-pane", "-t", session, "-p"])
        output = capture.stdout if capture.returncode == 0 else ""

        return AgentResult(
            summary="Session ended",
            output=output,
            exit_code=0,
        )

    def is_alive(self, handle: AgentHandle) -> bool:
        """Check whether the tmux session is still running."""
        session = handle.metadata.get(
            "session", _session_name(handle.agent_id)
        )
        result = _tmux(["has-session", "-t", session])
        return result.returncode == 0

    def kill(self, handle: AgentHandle) -> None:
        """Kill the tmux session."""
        session = handle.metadata.get(
            "session", _session_name(handle.agent_id)
        )
        _tmux(["kill-session", "-t", session])

    def interrupt(self, handle: AgentHandle) -> bool:
        """Forward Ctrl+C to the tmux pane."""
        session = handle.metadata.get(
            "session", _session_name(handle.agent_id)
        )
        _tmux(["send-keys", "-t", session, "C-c"])
        return True

    def attach(self, handle: AgentHandle) -> None:
        """Attach the user's terminal to the tmux session.

        This is not part of the AgentRuntime protocol — it is specific
        to interactive mode and called by the session layer after
        spawning the orchestrator.
        """
        session = handle.metadata.get(
            "session", _session_name(handle.agent_id)
        )
        subprocess.run(
            ["tmux", "attach-session", "-t", session],
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )


class DirectWrapperRuntime:
    """Cross-platform fallback for interactive sessions.

    Runs the agent process directly attached to the current terminal
    via ``subprocess.Popen``.  No detach/reattach capability, but works
    on all platforms (Windows, Linux, macOS) without tmux.

    Attributes:
        name: Agent name (delegated from the inner runtime).
    """

    def __init__(self, inner: WrapperRuntime) -> None:
        self.inner = inner
        self.name = inner.name
        self._procs: dict[str, subprocess.Popen] = {}

    def spawn(
        self,
        *,
        agent_id: str,
        working_dir: str,
        agent_workspace_dir: str,
        role_prompt: str,
        memory_prompt: str,
        skills_dir: str,
        roles_dirs: list[str],
        task: str,
        env: dict[str, str],
    ) -> AgentHandle:
        """Start the agent attached to the current terminal.

        Calls ``<wrapper> build`` to get the agent command, then launches
        it with stdin/stdout/stderr inherited from the parent process.
        """
        # 1. Call <wrapper> build to get the translated command
        args: list[str] = [
            "build",
            "--agent-id", agent_id,
            "--working-dir", working_dir,
            "--agent-workspace-dir", agent_workspace_dir,
            "--role-prompt", role_prompt,
            "--memory-prompt", memory_prompt,
            "--task", task,
            "--config", json.dumps(self.inner.spec.config),
            "--skills-dir", skills_dir,
        ]
        for rd in roles_dirs:
            args.extend(["--roles-dir", rd])

        data = self.inner._run_subcommand(args, extra_env=env)
        agent_cmd = data["cmd"]
        cwd = data.get("cwd", working_dir)

        # 2. Launch directly with terminal attached
        full_env = {**os.environ, **env} if env else None
        proc = subprocess.Popen(
            agent_cmd,
            cwd=cwd,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            env=full_env,
        )
        self._procs[agent_id] = proc

        return AgentHandle(
            agent_id=agent_id,
            runtime_name=self.name,
            pid=proc.pid,
            metadata={},
        )

    def wait(
        self, handle: AgentHandle, timeout: float | None = None
    ) -> AgentResult:
        """Block until the process exits."""
        proc = self._procs.get(handle.agent_id)
        if proc is None:
            return AgentResult(summary="Session ended")
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
        return AgentResult(
            summary="Session ended",
            exit_code=proc.returncode if proc.returncode is not None else 0,
        )

    def is_alive(self, handle: AgentHandle) -> bool:
        """Check whether the process is still running."""
        proc = self._procs.get(handle.agent_id)
        if proc is None:
            return False
        return proc.poll() is None

    def kill(self, handle: AgentHandle) -> None:
        """Terminate the process."""
        proc = self._procs.get(handle.agent_id)
        if proc is not None:
            proc.terminate()

    def interrupt(self, handle: AgentHandle) -> bool:
        """No-op — the agent already received SIGINT from the OS."""
        return False

    def attach(self, handle: AgentHandle) -> None:
        """Wait for the process to complete.

        Unlike tmux attach, this is a no-op if the process is already
        running with the terminal attached.  It simply blocks until exit.
        """
        proc = self._procs.get(handle.agent_id)
        if proc is not None:
            proc.wait()
