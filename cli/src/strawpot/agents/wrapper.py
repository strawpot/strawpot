"""WrapperRuntime — implements AgentRuntime via wrapper CLI + internal process management.

The wrapper CLI only needs two subcommands: ``setup`` (interactive auth) and
``build`` (translate protocol args to native agent command).  Process lifecycle
(spawn via Popen, PID tracking, wait, kill) is handled internally by
WrapperRuntime — wrappers never manage processes.
"""

import json
import os
import signal
import subprocess
import sys
import time

from strawpot.agents.protocol import AgentHandle, AgentResult
from strawpot.agents.registry import AgentSpec


class WrapperRuntime:
    """Implements AgentRuntime by calling ``<wrapper> build`` then managing processes.

    The wrapper command comes from ``AgentSpec.wrapper_cmd`` (resolved by the
    registry).  ``build`` is called to translate protocol args to the agent's
    native command; the process is then launched and tracked internally.

    Attributes:
        name: Agent name from the spec (satisfies ``AgentRuntime.name``).
        spec: The resolved AgentSpec.
    """

    def __init__(
        self, spec: AgentSpec, runtime_dir: str | None = None
    ) -> None:
        self.spec = spec
        self.name = spec.name
        self._runtime_dir = runtime_dir or os.path.join(
            os.environ.get("TMPDIR", "/tmp"), "strawpot"
        )

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
        return os.path.join(self._runtime_dir, f"{agent_id}.pid")

    def _log_file(self, agent_id: str) -> str:
        """Path to the output log file for the given agent."""
        return os.path.join(self._runtime_dir, f"{agent_id}.log")

    def _write_pid(self, agent_id: str, pid: int) -> None:
        """Write PID to the PID file."""
        os.makedirs(self._runtime_dir, exist_ok=True)
        with open(self._pid_file(agent_id), "w") as f:
            f.write(str(pid))

    def _read_pid(self, agent_id: str) -> int | None:
        """Read the PID from the PID file, or None if not found."""
        try:
            with open(self._pid_file(agent_id)) as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return None

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        """Check whether a process is still running."""
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # process exists but we can't signal it

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
        role_prompt: str,
        memory_prompt: str,
        skills_dirs: list[str],
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
            "--role-prompt", role_prompt,
            "--memory-prompt", memory_prompt,
            "--task", task,
            "--config", json.dumps(self.spec.config),
        ]
        for d in skills_dirs:
            args += ["--skills-dir", d]
        for d in roles_dirs:
            args += ["--roles-dir", d]

        data = self._run_subcommand(args, extra_env=env)
        agent_cmd = data["cmd"]
        cwd = data.get("cwd", working_dir)

        # 2. Launch via Popen
        log_path = self._log_file(agent_id)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        full_env = {**os.environ, **env} if env else None
        with open(log_path, "w") as log_fh:
            proc = subprocess.Popen(
                agent_cmd,
                cwd=cwd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=full_env,
            )

        # 3. Write PID file
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
        """Block until the agent finishes by polling PID.

        Reads captured output from the log file.
        """
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
            with open(log_path) as f:
                output = f.read()

        return AgentResult(
            summary="Agent completed",
            output=output,
            exit_code=0,
        )

    def is_alive(self, handle: AgentHandle) -> bool:
        """Check whether the agent process is still running."""
        pid = handle.pid or self._read_pid(handle.agent_id)
        if pid is None:
            return False
        return self._is_process_alive(pid)

    def kill(self, handle: AgentHandle) -> None:
        """Forcefully terminate the agent process via SIGTERM."""
        pid = handle.pid or self._read_pid(handle.agent_id)
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
