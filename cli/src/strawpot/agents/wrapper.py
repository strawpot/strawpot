"""WrapperRuntime — implements AgentRuntime by calling wrapper CLI subcommands.

Every agent wrapper must expose four subcommands (spawn, wait, alive, kill)
that accept protocol args and return JSON on stdout.  WrapperRuntime is the
single, generic glue between StrawPot and any conforming wrapper CLI.
"""

import json
import os
import subprocess

from strawpot.agents.protocol import AgentHandle, AgentResult
from strawpot.agents.registry import AgentSpec


class WrapperRuntime:
    """Implements AgentRuntime by shelling out to a wrapper CLI.

    The wrapper command comes from ``AgentSpec.wrapper_cmd`` (resolved by the
    registry).  Each public method translates to a subprocess call of the form::

        <wrapper_cmd...> <subcommand> <protocol args...>

    and expects a JSON object on stdout.

    Attributes:
        name: Agent name from the spec (satisfies ``AgentRuntime.name``).
        spec: The resolved AgentSpec.
    """

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec
        self.name = spec.name

    # ------------------------------------------------------------------
    # Internal helpers
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
                wait indefinitely (used by ``wait``).
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
    # AgentRuntime interface
    # ------------------------------------------------------------------

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
        """Start an agent process via ``<wrapper> spawn``.

        Builds the full CLI arg list and expects JSON on stdout::

            {"pid": 1234, "metadata": {"session": "strawpot-ab12"}}
        """
        args: list[str] = [
            "spawn",
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
        return AgentHandle(
            agent_id=agent_id,
            runtime_name=self.name,
            pid=data.get("pid"),
            metadata=data.get("metadata", {}),
        )

    def wait(
        self, handle: AgentHandle, timeout: float | None = None
    ) -> AgentResult:
        """Block until the agent finishes via ``<wrapper> wait``.

        Expects JSON on stdout::

            {"summary": "...", "output": "...", "exit_code": 0}
        """
        args = ["wait", "--agent-id", handle.agent_id]
        if timeout is not None:
            args += ["--timeout", str(timeout)]
        data = self._run_subcommand(args, timeout=None)
        return AgentResult(
            summary=data.get("summary", ""),
            output=data.get("output", ""),
            exit_code=data.get("exit_code", 0),
        )

    def is_alive(self, handle: AgentHandle) -> bool:
        """Check whether the agent is still running via ``<wrapper> alive``.

        Expects JSON on stdout::

            {"alive": true}
        """
        data = self._run_subcommand(
            ["alive", "--agent-id", handle.agent_id]
        )
        return bool(data.get("alive", False))

    def kill(self, handle: AgentHandle) -> None:
        """Forcefully terminate the agent via ``<wrapper> kill``.

        Expects JSON on stdout::

            {"killed": true}
        """
        self._run_subcommand(["kill", "--agent-id", handle.agent_id])
