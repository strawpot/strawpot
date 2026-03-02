"""Session lifecycle — owns denden server, isolation, orchestrator, and delegation."""

import json
import logging
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
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


# ------------------------------------------------------------------
# Crash recovery
# ------------------------------------------------------------------


def recover_stale_sessions(
    working_dir: str, config: StrawPotConfig
) -> list[str]:
    """Detect and clean up stale sessions left behind by crashes.

    Scans ``.strawpot/sessions/`` for session files whose ``pid`` is no
    longer alive.  For each stale session the merge strategy is applied
    (worktree isolation only) and the session directory is removed.

    Called at the beginning of ``strawpot start`` so orphaned worktrees
    and session artifacts are cleaned up before a new session starts.

    Args:
        working_dir: Project directory (CWD at invocation time).
        config: Merged StrawPot configuration (used for merge settings).

    Returns:
        List of recovered ``run_id`` strings.
    """
    from strawpot._process import is_pid_alive

    sessions_dir = os.path.join(working_dir, ".strawpot", "sessions")
    if not os.path.isdir(sessions_dir):
        return []

    recovered: list[str] = []

    for entry in sorted(os.listdir(sessions_dir)):
        session_file = os.path.join(sessions_dir, entry, "session.json")
        if not os.path.isfile(session_file):
            continue

        try:
            with open(session_file, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.debug("Skipping unreadable session file: %s", session_file)
            continue

        # Skip sessions that belong to a different project directory
        if data.get("working_dir") != working_dir:
            continue

        pid = data.get("pid")
        if pid is not None and is_pid_alive(pid):
            continue  # still running

        run_id = data.get("run_id", entry)
        logger.info("Recovering stale session: %s", run_id)

        # --- Merge (worktree isolation only) ---
        delete_branch = True
        isolation = data.get("isolation", "none")
        if isolation == "worktree":
            delete_branch = _recover_merge(data, working_dir, config)

        # --- Isolator cleanup ---
        if isolation == "worktree" and data.get("worktree"):
            try:
                env = IsolatedEnv(
                    path=data["worktree"],
                    branch=data.get("worktree_branch"),
                )
                WorktreeIsolator().cleanup(
                    env, base_dir=working_dir, delete_branch=delete_branch
                )
            except Exception:
                logger.debug(
                    "Isolator cleanup failed for %s", run_id, exc_info=True
                )

        # --- Remove session directory ---
        session_dir = os.path.join(sessions_dir, entry)
        try:
            shutil.rmtree(session_dir)
        except OSError:
            logger.debug("Failed to remove session dir %s", session_dir)

        recovered.append(run_id)

    return recovered


def _recover_merge(
    data: dict, working_dir: str, config: StrawPotConfig
) -> bool:
    """Run the merge strategy for a stale worktree session.

    Returns ``True`` if the branch should be deleted, ``False`` to keep it.
    """
    from strawpot.merge import merge_local, merge_pr, resolve_strategy

    base_branch = data.get("base_branch")
    session_branch = data.get("worktree_branch")
    worktree_dir = data.get("worktree")

    if not base_branch or not session_branch or not worktree_dir:
        logger.debug(
            "Missing branch/worktree info, skipping merge for %s",
            data.get("run_id"),
        )
        return True

    if not os.path.isdir(worktree_dir):
        logger.debug("Worktree directory missing, skipping merge")
        return True

    strategy = resolve_strategy(config.merge_strategy, working_dir)

    try:
        if strategy == "local":
            result = merge_local(
                base_branch=base_branch,
                session_branch=session_branch,
                worktree_dir=worktree_dir,
                base_dir=working_dir,
            )
            logger.info("Recovery merge (local): %s", result.message)
            return True

        if strategy == "pr":
            result = merge_pr(
                base_branch=base_branch,
                session_branch=session_branch,
                worktree_dir=worktree_dir,
                base_dir=working_dir,
                pr_command=config.pr_command,
            )
            logger.info("Recovery merge (PR): %s", result.message)
            return False
    except Exception:
        logger.debug("Recovery merge failed", exc_info=True)

    return True


# ------------------------------------------------------------------
# Isolator resolution
# ------------------------------------------------------------------


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
        self._shutting_down: bool = False
        self._interrupted: bool = False
        self._last_sigint_time: float = 0.0

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
            skills_dir, roles_dir = stage_role(
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
                skills_dir=skills_dir,
                roles_dirs=[roles_dir],
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

            # 7. Install signal handler before blocking attach
            original_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._handle_sigint)

            # 8. Attach — blocks until orchestrator exits
            self.runtime.attach(handle)

        finally:
            signal.signal(signal.SIGINT, original_sigint)
            self.stop()

    def stop(self) -> None:
        """Clean up the session: kill agents, stop server, merge changes, remove isolation."""
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

        # 3. Merge session changes (worktree isolation only)
        delete_branch = True
        if self._env and self._env.branch and self._working_dir:
            try:
                delete_branch = self._merge_session_changes()
            except Exception:
                logger.debug("Merge failed", exc_info=True)

        # 4. Isolator cleanup
        if self._env and self._working_dir:
            try:
                if isinstance(self.isolator, WorktreeIsolator):
                    self.isolator.cleanup(
                        self._env,
                        base_dir=self._working_dir,
                        delete_branch=delete_branch,
                    )
                else:
                    self.isolator.cleanup(
                        self._env, base_dir=self._working_dir
                    )
            except Exception:
                logger.debug("Isolator cleanup failed", exc_info=True)

        # 5. Remove session directory (includes session.json, agent workspaces, staged roles)
        self._remove_session_dir()

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    _SIGINT_ESCALATION_WINDOW = 2.0

    def _handle_sigint(self, signum, frame) -> None:
        """Handle SIGINT (Ctrl+C) during session — three escalation levels.

        1. **First press — Interrupt**: Forward interrupt to the agent
           (cancel current task), keep the session alive.  If the runtime
           reports that the agent already received SIGINT (direct mode),
           escalate immediately to shutdown.
        2. **Second press (within ~2 s) — Shutdown**: Kill the orchestrator
           to unblock ``runtime.attach()`` so cleanup runs via ``finally``.
        3. **Third press (during shutdown) — Force quit**: ``os._exit(1)``.
        """
        now = time.monotonic()

        # Level 3: already shutting down → force quit
        if self._shutting_down:
            sys.stderr.write("\nForce quit.\n")
            os._exit(1)

        # Level 2: second Ctrl+C within window → shutdown
        if (
            self._interrupted
            and (now - self._last_sigint_time) < self._SIGINT_ESCALATION_WINDOW
        ):
            self._shutdown_orchestrator()
            return

        # Level 1: first Ctrl+C (or re-interrupt after window expired)
        self._interrupted = True
        self._last_sigint_time = now

        forwarded = False
        if self._orchestrator_handle:
            try:
                forwarded = self.runtime.interrupt(self._orchestrator_handle)
            except Exception:
                pass

        if forwarded:
            # Interactive (tmux): interrupt was forwarded, wait for second Ctrl+C
            sys.stderr.write(
                "\nInterrupting agent... press Ctrl+C again within 2s to shut down.\n"
            )
        else:
            # Direct mode: agent already got SIGINT, escalate to shutdown
            self._shutdown_orchestrator()

    def _shutdown_orchestrator(self) -> None:
        """Kill the orchestrator and mark session as shutting down."""
        self._shutting_down = True
        sys.stderr.write(
            "\nShutting down... press Ctrl+C again to force quit.\n"
        )
        if self._orchestrator_handle:
            try:
                self.runtime.kill(self._orchestrator_handle)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Merge strategies
    # ------------------------------------------------------------------

    def _merge_session_changes(self) -> bool:
        """Run the configured merge strategy for worktree isolation.

        Must be called *before* isolator cleanup (the worktree needs to
        exist for patch generation).

        Returns:
            ``True`` if the branch should be deleted during cleanup,
            ``False`` if it should be kept (PR strategy).
        """
        from strawpot.merge import merge_local, merge_pr, resolve_strategy

        base_branch = self._session_data.get("base_branch")
        session_branch = self._session_data.get("worktree_branch")

        if not base_branch or not session_branch:
            logger.debug(
                "Missing branch info, skipping merge "
                "(base=%s, session=%s)",
                base_branch,
                session_branch,
            )
            return True

        strategy = resolve_strategy(
            self.config.merge_strategy, self._working_dir
        )

        try:
            if strategy == "local":
                result = merge_local(
                    base_branch=base_branch,
                    session_branch=session_branch,
                    worktree_dir=self._env.path,
                    base_dir=self._working_dir,
                )
                logger.info("Local merge: %s", result.message)
                return True  # always delete branch for local strategy

            if strategy == "pr":
                result = merge_pr(
                    base_branch=base_branch,
                    session_branch=session_branch,
                    worktree_dir=self._env.path,
                    base_dir=self._working_dir,
                    pr_command=self.config.pr_command,
                )
                logger.info("PR merge: %s", result.message)
                return False  # keep branch — it's on remote

        except Exception:
            logger.debug("Merge failed", exc_info=True)

        return True  # fallback: delete branch

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
