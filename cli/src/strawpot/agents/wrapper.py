"""WrapperRuntime — implements AgentRuntime via wrapper CLI + internal process management.

The wrapper CLI only needs two subcommands: ``setup`` (interactive auth) and
``build`` (translate protocol args to native agent command).  Process lifecycle
(spawn via Popen, PID tracking, wait, kill) is handled internally by
WrapperRuntime — wrappers never manage processes.
"""

import json
import logging
import os
import subprocess
import sys
import time

from strawpot._process import is_pid_alive, kill_process_tree
from strawpot.agents.protocol import AgentHandle, AgentResult, TokenUsage
from strawpot.agents.registry import AgentSpec

logger = logging.getLogger(__name__)


def _parse_stream_json_log(
    log_content: str,
) -> tuple[str, TokenUsage | None]:
    """Parse a stream-json JSONL log to extract result text and token usage.

    Returns ``(output_text, usage)`` where *output_text* is the human-readable
    result and *usage* is a :class:`TokenUsage` if a ``result`` message was
    found, otherwise ``(raw_content, None)`` as a fallback for non-stream-json
    logs.
    """
    if not log_content.strip():
        return "", None

    result_msg = None
    for line in log_content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict) and parsed.get("type") == "result":
            result_msg = parsed

    if result_msg is None:
        # Not stream-json format — return raw content.
        return log_content, None

    output_text = result_msg.get("result", "")
    if not isinstance(output_text, str):
        output_text = str(output_text) if output_text is not None else ""

    raw_usage = result_msg.get("usage")
    if isinstance(raw_usage, dict):
        usage = TokenUsage(
            input_tokens=raw_usage.get("input_tokens", 0),
            output_tokens=raw_usage.get("output_tokens", 0),
            cache_read_input_tokens=raw_usage.get("cache_read_input_tokens", 0),
            cache_creation_input_tokens=raw_usage.get(
                "cache_creation_input_tokens", 0
            ),
        )
    else:
        usage = TokenUsage()

    usage.cost_usd = result_msg.get("cost_usd")
    usage.model = result_msg.get("model", "")

    return output_text, usage


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
        skills_dirs: list[str],
        roles_dirs: list[str],
        files_dirs: list[str],
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
        ]
        for sd in skills_dirs:
            args.extend(["--skills-dir", sd])
        for rd in roles_dirs:
            args.extend(["--roles-dir", rd])
        for fd in files_dirs:
            args.extend(["--files-dir", fd])

        logger.debug(
            "spawn agent_id=%s working_dir=%s agent_workspace_dir=%s "
            "skills_dirs=%s roles_dirs=%s task_len=%d role_prompt_len=%d",
            agent_id, working_dir, agent_workspace_dir,
            skills_dirs, roles_dirs, len(task), len(role_prompt),
        )

        data = self._run_subcommand(args, extra_env=env)
        agent_cmd = data["cmd"]
        cwd = data.get("cwd", working_dir)

        logger.debug("wrapper build returned cmd=%s cwd=%s", agent_cmd, cwd)

        # 2. Launch via Popen
        log_path = self._log_file(agent_id)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        # Prepend skill directories to PATH so agents find staged binaries
        # (e.g. denden) before any stale global installs.
        skill_bin_paths: list[str] = []
        for sd in skills_dirs:
            if os.path.isdir(sd):
                for entry in os.scandir(sd):
                    if entry.is_dir(follow_symlinks=True):
                        skill_bin_paths.append(entry.path)
        if skill_bin_paths:
            parent_path = os.environ.get("PATH", "")
            env["PATH"] = os.pathsep.join(skill_bin_paths) + os.pathsep + parent_path

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

        # Read captured output and parse stream-json if available
        log_path = self._log_file(handle.agent_id)
        raw_log = ""
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                raw_log = f.read()

        output, usage = _parse_stream_json_log(raw_log)

        return AgentResult(
            summary="Agent completed",
            output=output,
            exit_code=exit_code,
            usage=usage,
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
