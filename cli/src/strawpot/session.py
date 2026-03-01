"""Session lifecycle — owns denden server, isolation, orchestrator, and delegation."""

import json
import logging
import os
import shutil
import subprocess
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from denden import (
    DenDenServer,
    denied_response,
    error_response,
    ok_response,
)
from denden.gen import denden_pb2

from strawpot.agents.protocol import AgentHandle
from strawpot.agents.wrapper import WrapperRuntime
from strawpot.config import StrawPotConfig
from strawpot.context import build_prompt
from strawpot.delegation import (
    DelegateRequest,
    PolicyDenied,
    create_agent_workspace,
    handle_delegate,
    stage_role,
)
from strawpot.isolation.protocol import IsolatedEnv, Isolator, NoneIsolator
from strawpot.isolation.worktree import WorktreeIsolator

logger = logging.getLogger(__name__)


def resolve_isolator(isolation: str) -> Isolator:
    """Return an Isolator instance for the given isolation mode.

    Args:
        isolation: One of ``"none"`` or ``"worktree"``.

    Raises:
        ValueError: If the isolation mode is unknown.
    """
    if isolation == "none":
        return NoneIsolator()
    if isolation == "worktree":
        return WorktreeIsolator()
    raise ValueError(f"Unknown isolation mode: {isolation}")


class Session:
    """Orchestration session — manages the full lifecycle.

    A session creates an isolated environment, starts a denden gRPC
    server, spawns the orchestrator agent, and handles delegation
    requests from sub-agents.

    Args:
        config: Merged StrawPot configuration.
        wrapper: WrapperRuntime for sub-agent delegation.
        runtime: Interactive runtime for the orchestrator agent
            (InteractiveWrapperRuntime or DirectWrapperRuntime).
        isolator: Isolator for session environment setup.
        resolve_role: Callable to resolve a role slug to a resolved dict.
            Signature: ``(slug, kind="role") -> dict``.
        resolve_role_dirs: Callable mapping a role slug to its directory
            path, or ``None`` if not resolvable.
    """

    def __init__(
        self,
        config: StrawPotConfig,
        wrapper: WrapperRuntime,
        runtime,
        isolator: Isolator,
        *,
        resolve_role: Callable[..., dict],
        resolve_role_dirs: Callable[[str], str | None],
    ) -> None:
        self.config = config
        self.wrapper = wrapper
        self.runtime = runtime
        self.isolator = isolator
        self._resolve_role = resolve_role
        self._resolve_role_dirs = resolve_role_dirs

        self._run_id: str | None = None
        self._env: IsolatedEnv | None = None
        self._working_dir: str | None = None
        self._server: DenDenServer | None = None
        self._server_thread: threading.Thread | None = None
        self._orchestrator_handle: AgentHandle | None = None
        self._agents: dict[str, AgentHandle] = {}
        self._agent_info: dict[str, dict] = {}
        self._session_file: str | None = None
        self._session_data: dict = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self, working_dir: str) -> None:
        """Run the full session lifecycle.

        Blocks until the orchestrator agent exits, then runs cleanup.

        Args:
            working_dir: Project directory (CWD at invocation time).
        """
        self._working_dir = working_dir
        self._run_id = f"run_{uuid.uuid4().hex[:12]}"

        # Set session_dir on wrapper so PID/log files go to the right place
        self.wrapper.session_dir = self._session_dir()

        try:
            # 1. Create isolated environment
            self._env = self.isolator.create(
                session_id=self._run_id, base_dir=working_dir
            )

            # 2. Start denden server in background
            self._start_denden_server()

            # 3. Resolve orchestrator role + build prompt
            resolved = self._resolve_role(
                self.config.orchestrator_role, kind="role"
            )
            role_prompt = build_prompt(resolved)

            # 4. Stage role + create agent workspace
            agent_id = f"agent_{uuid.uuid4().hex[:12]}"
            skills_dirs, roles_dirs = stage_role(
                self._session_dir(), resolved
            )
            workspace = create_agent_workspace(
                self._session_dir(), agent_id
            )

            # 5. Spawn orchestrator (interactive mode)
            env = {
                "PERMISSION_MODE": self.config.permission_mode,
                "DENDEN_ADDR": self.config.denden_addr,
                "DENDEN_AGENT_ID": agent_id,
                "DENDEN_RUN_ID": self._run_id,
            }

            handle = self.runtime.spawn(
                agent_id=agent_id,
                working_dir=self._env.path,
                agent_workspace_dir=workspace,
                role_prompt=role_prompt,
                memory_prompt="",
                skills_dirs=skills_dirs,
                roles_dirs=roles_dirs,
                task="",
                env=env,
            )
            self._orchestrator_handle = handle
            self._register_agent(
                agent_id,
                role=self.config.orchestrator_role,
                parent_id=None,
                pid=handle.pid,
            )

            # 6. Write session state file
            self._write_session_file()

            # 7. Attach — blocks until orchestrator exits
            self.runtime.attach(handle)

        finally:
            self.stop()

    def stop(self) -> None:
        """Clean up the session: kill agents, stop server, remove isolation."""
        # 1. Kill remaining sub-agents
        for agent_id, handle in self._agents.items():
            if handle is self._orchestrator_handle:
                continue
            try:
                if self.wrapper.is_alive(handle):
                    self.wrapper.kill(handle)
            except Exception:
                logger.debug("Failed to kill agent %s", agent_id)

        # 2. Stop denden server
        self._stop_denden_server()

        # 3. Isolator cleanup
        if self._env and self._working_dir:
            try:
                self.isolator.cleanup(
                    self._env, base_dir=self._working_dir
                )
            except Exception:
                logger.debug("Isolator cleanup failed", exc_info=True)

        # 4. Remove session directory (includes session.json, agent workspaces, staged roles)
        self._remove_session_dir()

    # ------------------------------------------------------------------
    # Denden server
    # ------------------------------------------------------------------

    def _start_denden_server(self) -> None:
        """Create and start the denden gRPC server in a daemon thread."""
        self._server = DenDenServer(addr=self.config.denden_addr)
        self._server.on_delegate(self._handle_delegate)
        self._server.on_ask_user(self._handle_ask_user)

        self._server_thread = threading.Thread(
            target=self._server.run, daemon=True
        )
        self._server_thread.start()

    def _stop_denden_server(self) -> None:
        """Stop the denden gRPC server."""
        if self._server and self._server._server:
            try:
                self._server._server.stop(grace=5)
            except Exception:
                logger.debug("Failed to stop denden server", exc_info=True)

    # ------------------------------------------------------------------
    # Denden handlers
    # ------------------------------------------------------------------

    def _handle_delegate(
        self, request: denden_pb2.DenDenRequest
    ) -> denden_pb2.DenDenResponse:
        """Handle a delegate request from a sub-agent."""
        payload = request.delegate
        trace = request.trace

        delegate_req = DelegateRequest(
            role_slug=payload.delegate_to,
            task_text=payload.task.text,
            parent_agent_id=trace.agent_instance_id,
            parent_role=self._agent_role(trace.agent_instance_id),
            run_id=trace.run_id,
            depth=self._agent_depth(trace.agent_instance_id),
        )

        try:
            result = handle_delegate(
                request=delegate_req,
                config=self.config,
                runtime=self.wrapper,
                working_dir=self._env.path,
                session_dir=self._session_dir(),
                resolve_role=self._resolve_role,
                resolve_role_dirs=self._resolve_role_dirs,
            )
            return ok_response(
                request.request_id,
                delegate_result=denden_pb2.DelegateResult(
                    summary=result.summary,
                ),
            )
        except PolicyDenied as exc:
            return denied_response(
                request.request_id, exc.reason, str(exc)
            )
        except Exception as exc:
            logger.exception("Delegation failed for %s", request.request_id)
            return error_response(
                request.request_id,
                "ERR_SUBAGENT_FAILURE",
                str(exc),
            )

    def _handle_ask_user(
        self, request: denden_pb2.DenDenRequest
    ) -> denden_pb2.DenDenResponse:
        """Handle an ask_user request (placeholder)."""
        return error_response(
            request.request_id,
            "NOT_IMPLEMENTED",
            "ask_user is not yet implemented",
        )

    # ------------------------------------------------------------------
    # Session directory and state file
    # ------------------------------------------------------------------

    def _session_dir(self) -> str:
        """Return the session directory: ``.strawpot/sessions/<run_id>/``."""
        d = os.path.join(self._working_dir, ".strawpot", "sessions", self._run_id)
        os.makedirs(d, exist_ok=True)
        return d

    def _sessions_base_dir(self) -> str:
        """Return the parent directory for all sessions."""
        return os.path.join(self._working_dir, ".strawpot", "sessions")

    @staticmethod
    def _detect_base_branch(working_dir: str) -> str | None:
        """Detect the current git branch, or None if not a git repo."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=working_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except FileNotFoundError:
            pass
        return None

    def _write_session_file(self) -> None:
        """Write session state to disk."""
        self._session_file = os.path.join(
            self._session_dir(), "session.json"
        )
        self._session_data = {
            "run_id": self._run_id,
            "working_dir": self._working_dir,
            "isolation": self.config.isolation,
            "runtime": self.config.runtime,
            "denden_addr": self.config.denden_addr,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "agents": {},
        }

        base_branch = self._detect_base_branch(self._working_dir)
        if base_branch:
            self._session_data["base_branch"] = base_branch

        if self._env and self._env.branch:
            self._session_data["worktree"] = self._env.path
            self._session_data["worktree_branch"] = self._env.branch

        # Add registered agents
        for agent_id, info in self._agent_info.items():
            self._session_data["agents"][agent_id] = info

        with open(self._session_file, "w", encoding="utf-8") as f:
            json.dump(self._session_data, f, indent=2)

    def _remove_session_dir(self) -> None:
        """Remove the entire session directory."""
        if self._working_dir and self._run_id:
            session_dir = os.path.join(
                self._working_dir, ".strawpot", "sessions", self._run_id
            )
            if os.path.isdir(session_dir):
                try:
                    shutil.rmtree(session_dir)
                except OSError:
                    logger.debug(
                        "Failed to remove session dir %s", session_dir
                    )

    # ------------------------------------------------------------------
    # Agent tracking
    # ------------------------------------------------------------------

    def _register_agent(
        self,
        agent_id: str,
        role: str,
        parent_id: str | None,
        pid: int | None = None,
    ) -> None:
        """Record an agent in the session state."""
        self._agent_info[agent_id] = {
            "role": role,
            "runtime": self.config.runtime,
            "parent": parent_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "pid": pid,
        }

    def _agent_role(self, agent_id: str) -> str:
        """Return the role of a registered agent."""
        info = self._agent_info.get(agent_id, {})
        return info.get("role", "unknown")

    def _agent_depth(self, agent_id: str) -> int:
        """Calculate delegation depth by traversing the parent chain."""
        depth = 0
        current = agent_id
        while current:
            info = self._agent_info.get(current, {})
            parent = info.get("parent")
            if parent:
                depth += 1
                current = parent
            else:
                break
        return depth
