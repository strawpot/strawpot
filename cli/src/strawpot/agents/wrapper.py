"""WrapperRuntime — implements AgentRuntime via wrapper CLI + internal process management.

The wrapper CLI only needs two subcommands: ``setup`` (interactive auth) and
``build`` (translate protocol args to native agent command).  Process lifecycle
(spawn via Popen, PID tracking, wait, kill) is handled internally by
WrapperRuntime — wrappers never manage processes.
"""

import json
import os
import subprocess
import sys
import time

from strawpot._process import is_pid_alive, kill_process_tree
from strawpot.agents.protocol import AgentHandle, AgentResult
from strawpot.agents.registry import AgentSpec


class WrapperRuntime:
    """Implements AgentRuntime by calling ``<wrapper> build`` then managing processes.

    The wrapper command comes from ``AgentSpec.wrapper_cmd`` (resolved by the
    registry).  ``build`` is called to translate protocol args to the agent's
    native command; the process is then launched and tracked internally.

    PID and log files are stored inside the agent workspace directory under
    the session: ``<session_dir>/agents/<agent_id>/.pid`` and ``.log``.

    Attributes:
        name: Agent name from the spec (satisfies ``AgentRuntime.name``).
        spec: The resolved AgentSpec.
        session_dir: Session directory.  Must be set before calling
            :meth:`spawn`.  Typically set by :class:`~strawpot.session.Session`
            after generating the run ID.
    """

    def __init__(
        self, spec: AgentSpec, session_dir: str | None = None
    ) -> None:
        self.spec = spec
        self.name = spec.name
        self.session_dir = session_dir
        self._procs: dict[str, subprocess.Popen] = {}

    # ------------------------------------------------------------------
    # Internal helpers — wrapper CLI
    # ------------------------------------------------------------------

    def _run_subcommand(
        self,
        args: list[str],
        *,
        timeout: float | None = 30,
        extra_env: dict[str, str] | None = None,
    ) -> dict:
        """Run a wrapper subcommand and return parsed JSON from stdout.

        Args:
            args: Subcommand and its arguments (appended to wrapper_cmd).
            timeout: Seconds to wait for the subprocess.  ``None`` means
                wait indefinitely.
            extra_env: Additional environment variables to set for the
                subprocess (merged on top of the current environment).

        Raises:
            RuntimeError: On non-zero exit code or unparseable JSON.
        """
        cmd = [*self.spec.wrapper_cmd, *args]
        env = None
        if extra_env:
            env = {**os.environ, **extra_env}
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Wrapper command failed (exit {result.returncode}): "
                f"{' '.join(cmd)}\nstderr: {result.stderr.strip()}"
            )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Wrapper returned invalid JSON: {result.stdout!r}"
            ) from exc

    # ------------------------------------------------------------------
    # Internal helpers — process lifecycle
    # ------------------------------------------------------------------

    def _pid_file(self, agent_id: str) -> str:
        """Path to the PID file for the given agent."""
        return os.path.join(self.session_dir, "agents", agent_id, ".pid")

    def _log_file(self, agent_id: str) -> str:
        """Path to the output log file for the given agent."""
        return os.path.join(self.session_dir, "agents", agent_id, ".log")

    def _write_pid(self, agent_id: str, pid: int) -> None:
        """Write PID to the PID file."""
        pid_path = self._pid_file(agent_id)
        os.makedirs(os.path.dirname(pid_path), exist_ok=True)
        with open(pid_path, "w", encoding="utf-8") as f:
            f.write(str(pid))

    def _read_pid(self, agent_id: str) -> int | None:
        """Read the PID from the PID file, or None if not found."""
        try:
            with open(self._pid_file(agent_id), encoding="utf-8") as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return None

    _is_process_alive = staticmethod(is_pid_alive)

    # ------------------------------------------------------------------
    # AgentRuntime interface
    # ------------------------------------------------------------------

    def setup(self) -> bool:
        """Run one-time interactive setup via ``<wrapper> setup``.

        Unlike other subcommands, ``setup`` runs with stdin/stdout
        attached to the terminal so the user can interact (e.g. OAuth
        login flow).  No JSON is expected — only the exit code matters.

        Returns:
            True if setup succeeded (exit code 0), False otherwise.
        """
        cmd = [*self.spec.wrapper_cmd, "setup"]
        result = subprocess.run(
            cmd,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        return result.returncode == 0

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
        """Start an agent process.

        Calls ``<wrapper> build`` to get the translated command, then
        launches it via Popen.  PID and log files are managed internally.
        """
        # 1. Call <wrapper> build to get translated command
        args: list[str] = [
            "build",
            "--agent-id", agent_id,
            "--working-dir", working_dir,
            "--agent-workspace-dir", agent_workspace_dir,
            "--role-prompt", role_prompt,
            "--memory-prompt", memory_prompt,
            "--task", task,
            "--config", json.dumps(self.spec.config),
            "--skills-dir", skills_dir,
        ]
        for rd in roles_dirs:
            args.extend(["--roles-dir", rd])

        data = self._run_subcommand(args, extra_env=env)
        agent_cmd = data["cmd"]
        cwd = data.get("cwd", working_dir)

        # 2. Launch via Popen
        log_path = self._log_file(agent_id)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        full_env = {**os.environ, **env} if env else None
        with open(log_path, "w", encoding="utf-8") as log_fh:
            proc = subprocess.Popen(
                agent_cmd,
                cwd=cwd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=full_env,
                start_new_session=True,
            )

        # 3. Track process and write PID file
        self._procs[agent_id] = proc
        self._write_pid(agent_id, proc.pid)

        return AgentHandle(
            agent_id=agent_id,
            runtime_name=self.name,
            pid=proc.pid,
            metadata={},
        )

    def wait(
        self, handle: AgentHandle, timeout: float | None = None
    ) -> AgentResult:
        """Block until the agent finishes.

        Uses the stored Popen object when available for reliable process
        reaping; falls back to PID polling for recovered sessions.
        Reads captured output from the log file.
        """
        proc = self._procs.get(handle.agent_id)
        exit_code = 0

        if proc is not None:
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
            exit_code = proc.returncode if proc.returncode is not None else 0
        else:
            # Fallback: poll PID (e.g. recovered session with only PID file)
            pid = handle.pid or self._read_pid(handle.agent_id)
            elapsed = 0.0
            poll_interval = 0.5

            if pid is not None:
                while self._is_process_alive(pid):
                    if timeout is not None and elapsed >= timeout:
                        break
                    time.sleep(poll_interval)
                    elapsed += poll_interval

        # Read captured output
        log_path = self._log_file(handle.agent_id)
        output = ""
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                output = f.read()

        return AgentResult(
            summary="Agent completed",
            output=output,
            exit_code=exit_code,
        )

    def is_alive(self, handle: AgentHandle) -> bool:
        """Check whether the agent process is still running."""
        proc = self._procs.get(handle.agent_id)
        if proc is not None:
            return proc.poll() is None
        pid = handle.pid or self._read_pid(handle.agent_id)
        if pid is None:
            return False
        return self._is_process_alive(pid)

    def kill(self, handle: AgentHandle) -> None:
        """Forcefully terminate the agent and all its child processes.

        Delegates to :func:`~strawpot._process.kill_process_tree` which
        kills the process group via ``os.killpg``.
        """
        pid = handle.pid or self._read_pid(handle.agent_id)
        if pid is None:
            return
        kill_process_tree(pid)

    def interrupt(self, handle: AgentHandle) -> bool:
        """No-op — non-interactive agents do not support interrupt."""
        return False
