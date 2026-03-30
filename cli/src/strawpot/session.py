"""Session lifecycle — owns denden server, isolation, orchestrator, and delegation."""

import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import warnings
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
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
from strawpot.cancel import (
    AgentState,
    CancelReason,
    cancel_dir,
    get_children,
    get_subtree_bottom_up,
    mark_signal_done,
    read_cancel_signals,
)
from strawpot.config import StrawPotConfig
from strawpot.context import build_prompt
from strawpot.delegation import (
    DelegateRequest,
    PolicyDenied,
    _build_delegatable_roles,
    _compose_memory_prompt,
    _discover_all_roles,
    _format_memory_prompt,
    _parse_role_deps,
    _recall_identity,
    _recall_warm_start,
    build_skill_descriptions,
    create_agent_workspace,
    handle_delegate,
    stage_role,
)
from strawpot_memory.memory_protocol import MemoryProvider, RecallResult
from strawpot.memory.registry import MemorySpec, load_provider, resolve_memory
from strawpot._process import is_pid_alive, kill_process_tree
from strawpot.isolation.protocol import IsolatedEnv, Isolator, NoneIsolator
from strawpot.progress import ProgressEvent
from strawpot.trace import Tracer

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Crash recovery
# ------------------------------------------------------------------


def recover_stale_sessions(
    working_dir: str, config: StrawPotConfig
) -> list[str]:
    """Detect and clean up stale sessions left behind by crashes.

    Scans ``.strawpot/sessions/`` for session files whose ``pid`` is no
    longer alive.  For each stale session the session directory is archived.

    Called at the beginning of ``strawpot start`` so orphaned session
    artifacts are cleaned up before a new session starts.

    Args:
        working_dir: Project directory (CWD at invocation time).
        config: Merged StrawPot configuration.

    Returns:
        List of recovered ``run_id`` strings.
    """
    strawpot_dir = os.path.join(working_dir, ".strawpot")
    sessions_dir = os.path.join(strawpot_dir, "sessions")
    running_dir = os.path.join(strawpot_dir, "running")
    if not os.path.isdir(running_dir):
        return []

    recovered: list[str] = []

    for entry in sorted(os.listdir(running_dir)):
        if not entry.startswith("run_"):
            continue
        link_path = os.path.join(running_dir, entry)
        # Clean up orphaned symlinks (target deleted)
        if os.path.islink(link_path) and not os.path.exists(link_path):
            os.unlink(link_path)
            continue
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
        stored = data.get("working_dir", "")
        if os.path.abspath(stored) != os.path.abspath(working_dir):
            continue

        pid = data.get("pid")
        if pid is not None and is_pid_alive(pid):
            continue  # still running

        run_id = data.get("run_id", entry)
        logger.info("Recovering stale session: %s", run_id)

        # --- Kill remaining agent PIDs ---
        for agent_id, agent_info in data.get("agents", {}).items():
            agent_pid = agent_info.get("pid")
            if agent_pid and is_pid_alive(agent_pid):
                try:
                    kill_process_tree(agent_pid)
                    logger.info(
                        "Killed stale agent %s (pid=%s) in session %s",
                        agent_id, agent_pid, run_id,
                    )
                except Exception:
                    logger.debug(
                        "Failed to kill stale agent %s (pid=%s)",
                        agent_id, agent_pid,
                    )

        # --- Swap running symlink to archive ---
        if os.path.islink(link_path):
            os.unlink(link_path)
        archive_dir = os.path.join(strawpot_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        archive_link = os.path.join(archive_dir, entry)
        if not os.path.exists(archive_link):
            os.symlink(os.path.join("..", "sessions", entry), archive_link)

        recovered.append(run_id)

    return recovered


@dataclass(frozen=True)
class AskUserRequest:
    """Transport-agnostic representation of an ask_user request."""

    question: str
    choices: list[str]
    default_value: str
    why: str
    response_format: str


@dataclass(frozen=True)
class AskUserResponse:
    """Transport-agnostic representation of an ask_user response.

    Attributes:
        text: Plain text answer.
        json: JSON string for structured responses (converted to
            protobuf Struct on the wire). Leave empty for text-only.
    """

    text: str = ""
    json: str = ""


def _default_ask_user_handler(req: AskUserRequest) -> AskUserResponse:
    """Default ask_user handler — auto-responds for headless/autonomous mode."""
    if req.default_value:
        return AskUserResponse(text=req.default_value)
    return AskUserResponse(text="Proceed with your best judgment.")


_SESSION_RECAP_RE = re.compile(
    r"## Session Recap\b",
)


def _track_recall(entry_ids: list[str], project_dir: str | None) -> None:
    """Record recall frequency for importance tracking.

    Failures are silently logged — recall tracking is best-effort and
    must never break the recall handler.
    """
    try:
        from strawpot.memory.importance import record_recall

        record_recall(entry_ids, project_dir)
    except Exception:
        logger.debug("Recall tracking failed", exc_info=True)


def _boost_by_importance(
    result: RecallResult,
    project_dir: str | None,
) -> RecallResult:
    """Boost recall result scores by importance factor.

    Entries with higher recall frequency and recency get a score boost.
    The boost is multiplicative: ``score * (1 + importance / 10)``.
    This preserves the original BM25 ordering for entries with no
    importance data while lifting frequently-used entries.

    Returns the same RecallResult with adjusted scores and re-sorted.
    """
    try:
        from strawpot.memory.importance import (
            importance_score,
            load_stats,
        )

        stats = load_stats(project_dir)
        if not stats:
            return result

        for entry in result.entries:
            entry_stats = stats.get(entry.entry_id)
            if entry_stats is not None:
                imp = importance_score(entry_stats)
                entry.score *= 1.0 + imp / 10.0

        result.entries.sort(key=lambda e: e.score, reverse=True)
    except Exception:
        logger.debug("Importance boosting failed", exc_info=True)

    return result


def _extract_session_recap(output: str) -> str:
    """Extract the last ``## Session Recap`` section from agent output.

    When multiple recaps exist (e.g. a quoted previous recap followed by
    the agent's own), the *last* one is used to avoid capturing stale
    content.  The capture stops at the next ``## `` heading (if any) so
    trailing content is excluded.

    Returns the recap text (trimmed), or an empty string if no recap
    is found.
    """
    if not output:
        return ""
    # Find the last occurrence of the heading.
    matches = list(_SESSION_RECAP_RE.finditer(output))
    if not matches:
        return ""
    last = matches[-1]
    tail = output[last.start():]
    # Stop at the next heading (if any) to avoid capturing unrelated content.
    next_heading = re.search(r"\n## (?!Session Recap\b)", tail)
    if next_heading:
        tail = tail[:next_heading.start()]
    recap = tail.strip()
    # Cap at 2000 chars to prevent context bloat in future sessions.
    return recap[:2000]


class Session:
    """Orchestration session — manages the full lifecycle.

    A session starts a denden gRPC server, spawns the orchestrator agent,
    and handles delegation requests from sub-agents.

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
        task: str = "",
        run_id: str | None = None,
        ask_user_handler: Callable[[AskUserRequest], AskUserResponse] | None = None,
        headless: bool = False,
        system_prompt: str = "",
        memory_task: str = "",
        group_id: str | None = None,
        on_event: Callable[[ProgressEvent], None] | None = None,
    ) -> None:
        self.config = config
        self.wrapper = wrapper
        self.runtime = runtime
        self.isolator = isolator
        self.task = task
        self.system_prompt = system_prompt
        self.memory_task = memory_task or task
        self._resolve_role = resolve_role
        self._resolve_role_dirs = resolve_role_dirs
        self._ask_user_handler = ask_user_handler or _default_ask_user_handler
        self._provided_run_id = run_id
        self._headless = headless
        self._group_id: str | None = group_id
        self._on_event = on_event

        self._run_id: str | None = None
        self._env: IsolatedEnv | None = None
        self._working_dir: str | None = None
        self._server: DenDenServer | None = None
        self._denden_addr: str | None = None
        self._orchestrator_handle: AgentHandle | None = None
        self._agents: dict[str, AgentHandle] = {}
        self._agent_info: dict[str, dict] = {}
        self._session_file: str | None = None
        self._session_data: dict = {}
        self._memory_provider: MemoryProvider | None = None
        self._tracer: Tracer | None = None
        self._session_span_id: str | None = None
        self._session_start_time: float = 0.0
        self._agent_spans: dict[str, str] = {}
        self._orchestrator_result: AgentResult | None = None
        self._orchestrator_role_prompt: str = ""
        self._files_dirs: list[str] = []
        self._delegation_cache: OrderedDict[str, tuple[str, "denden_pb2.DelegateResult", float]] = OrderedDict()
        self._delegation_lock = threading.RLock()
        self._delegation_key_locks: dict[str, threading.RLock] = {}
        self._delegation_count: int = 0
        self._shutting_down: bool = False
        self._interrupted: bool = False
        self._last_sigint_time: float = 0.0
        self._cancel_watcher_stop = threading.Event()

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
        self._run_id = self._provided_run_id or f"run_{uuid.uuid4().hex[:12]}"

        # Set session_dir on wrapper so PID/log files go to the right place
        self.wrapper.session_dir = self._session_dir()

        # Activate file-based ask_user bridge when env var is set
        bridge_mode = os.environ.get("STRAWPOT_ASK_USER_BRIDGE")
        if bridge_mode == "file" and self._ask_user_handler is _default_ask_user_handler:
            from strawpot.ask_user_bridge import make_file_bridge_handler

            self._ask_user_handler = make_file_bridge_handler(self._session_dir())

        # Initialize tracer (before try block so session_dir exists)
        self._session_start_time = time.monotonic()
        if self.config.trace:
            self._tracer = Tracer(self._session_dir(), self._run_id)
            self._session_span_id = self._tracer.session_start(
                run_id=self._run_id,
                role=self.config.orchestrator_role,
                runtime=self.config.runtime,
                isolation="none",
                task=self.task or "",
            )

        original_sigint = signal.getsignal(signal.SIGINT)
        try:
            # 1. Create isolated environment
            self._env = self.isolator.create(
                session_id=self._run_id, base_dir=working_dir
            )

            # 1b. Resolve memory provider (if configured)
            if self.config.memory and self.config.memory != "none":
                spec = resolve_memory(
                    self.config.memory,
                    working_dir,
                    self.config.memory_config,
                )
                self._memory_provider = load_provider(spec)

            # 2. Start denden server in background
            self._start_denden_server()

            # 3. Resolve orchestrator role + build prompt
            resolved = self._resolve_role(
                self.config.orchestrator_role, kind="role"
            )
            _, role_dep_slugs, _, wildcard = _parse_role_deps(
                resolved["path"]
            )

            # Build delegatable roles so the orchestrator prompt lists them
            if wildcard:
                role_dep_slugs = [slug for slug, _ in _discover_all_roles(working_dir)]
            delegatable = _build_delegatable_roles(
                role_dep_slugs,
                self.config.orchestrator_role,
                self._resolve_role_dirs,
            )

            skill_descs = build_skill_descriptions(
                resolved, working_dir=working_dir,
            )
            role_prompt = build_prompt(
                resolved["slug"],
                resolved["path"],
                skills=skill_descs or None,
                delegatable_roles=delegatable or None,
                custom_prompt=self.system_prompt or None,
            )
            self._orchestrator_role_prompt = role_prompt

            # 4. Stage role + create agent workspace
            agent_id = f"agent_{uuid.uuid4().hex[:12]}"
            skills_dir, roles_dir = stage_role(
                self._session_dir(), resolved,
                working_dir=working_dir,
            )
            workspace = create_agent_workspace(
                self._session_dir(), agent_id
            )

            # 5a. Memory get for orchestrator
            memory_prompt = ""
            if self._memory_provider is not None:
                get_result = self._memory_provider.get(
                    session_id=self._run_id,
                    agent_id=agent_id,
                    role=self.config.orchestrator_role,
                    behavior_ref=role_prompt,
                    task=self.memory_task,
                    group_id=self._group_id,
                )
                if get_result.context_cards:
                    memory_prompt = _format_memory_prompt(get_result)
                if self._tracer is not None:
                    self._tracer.memory_get(
                        span_id=self._session_span_id,
                        provider=self._memory_provider.name,
                        session_id=self._run_id,
                        agent_id=agent_id,
                        role=self.config.orchestrator_role,
                        behavior_ref=role_prompt,
                        task=self.memory_task,
                        cards=get_result.context_cards or [],
                        card_count=len(get_result.context_cards) if get_result.context_cards else 0,
                        group_id=self._group_id,
                    )

                # 5a-ii. Identity bootstrap + session warm-start
                recall_kwargs = dict(
                    session_id=self._run_id,
                    agent_id=agent_id,
                    role=self.config.orchestrator_role,
                    group_id=self._group_id,
                )
                memory_prompt = _compose_memory_prompt(
                    _recall_identity(self._memory_provider, **recall_kwargs),
                    _recall_warm_start(self._memory_provider, **recall_kwargs),
                    memory_prompt,
                )

            # 5b. Resolve project files directories
            files_dirs: list[str] = []
            files_dir = os.path.join(self._working_dir, ".strawpot", "files")
            if os.path.isdir(files_dir):
                files_dirs.append(files_dir)
            self._files_dirs = files_dirs

            # 5c. Spawn orchestrator (interactive mode)
            env = {
                "PERMISSION_MODE": self.config.permission_mode,
                "DENDEN_ADDR": self._denden_addr,
                "DENDEN_AGENT_ID": agent_id,
                "DENDEN_RUN_ID": self._run_id,
                "STRAWPOT_ROLE": self.config.orchestrator_role,
            }

            # Register the agent BEFORE spawning so that if the
            # orchestrator immediately issues a delegation via denden,
            # _agent_role() can already resolve its role (avoids
            # "unknown" requester).
            self._register_agent(
                agent_id,
                role=self.config.orchestrator_role,
                parent_id=None,
            )

            handle = self.runtime.spawn(
                agent_id=agent_id,
                working_dir=self._env.path,
                agent_workspace_dir=workspace,
                role_prompt=role_prompt,
                memory_prompt=memory_prompt,
                skills_dirs=[skills_dir],
                roles_dirs=[roles_dir],
                files_dirs=files_dirs,
                task=self.task,
                env=env,
            )
            self._orchestrator_handle = handle
            self._agent_info[agent_id]["pid"] = handle.pid
            if self._tracer is not None:
                agent_context = role_prompt
                if memory_prompt:
                    agent_context += "\n\n" + memory_prompt
                self._tracer.agent_spawn(
                    span_id=self._session_span_id,
                    agent_id=agent_id,
                    role=self.config.orchestrator_role,
                    runtime=self.config.runtime,
                    pid=handle.pid,
                    working_dir=self._env.path,
                    agent_workspace_dir=workspace,
                    skills_dirs=[skills_dir],
                    roles_dirs=[roles_dir],
                    files_dirs=files_dirs,
                    task=self.task or "",
                    context=agent_context,
                )
                self._agent_spans[agent_id] = self._session_span_id

            self._emit(
                "session_start", self.config.orchestrator_role,
            )

            # 6. Write session state file
            self._write_session_file()

            # 6a. Start cancel signal watcher
            self._start_cancel_watcher()

            # 6b. Start activity watcher (emits tool_start/tool_end
            #     trace events by monitoring agent log files).
            self._start_activity_watcher()

            # 7. Install signal handler before blocking attach
            signal.signal(signal.SIGINT, self._handle_sigint)

            # 8. Block until orchestrator exits
            if self.task:
                result = self.runtime.wait(handle)
                self._orchestrator_result = result
                if result.exit_code != 0:
                    sys.exit(result.exit_code)
            else:
                self.runtime.attach(handle)

        finally:
            signal.signal(signal.SIGINT, original_sigint)
            self.stop()

    def stop(self) -> None:
        """Clean up the session: kill agents, stop server, remove isolation."""
        # 0. Stop cancel watcher
        self._cancel_watcher_stop.set()

        # 0a. Memory dump for orchestrator agent
        if self._memory_provider is not None and self._run_id is not None:
            orch_agent_id = None
            for aid, info in self._agent_info.items():
                if info.get("parent") is None:
                    orch_agent_id = aid
                    break
            if orch_agent_id is not None:
                result = self._orchestrator_result
                status = "success" if (result is None or result.exit_code == 0) else "failure"
                output = result.output if result else ""
                try:
                    self._memory_provider.dump(
                        session_id=self._run_id,
                        agent_id=orch_agent_id,
                        role=self.config.orchestrator_role,
                        behavior_ref=self._orchestrator_role_prompt,
                        task=self.memory_task,
                        status=status,
                        output=output,
                        group_id=self._group_id,
                    )
                except Exception:
                    logger.debug("Orchestrator memory.dump failed", exc_info=True)
                if self._tracer is not None and self._session_span_id is not None:
                    self._tracer.memory_dump(
                        span_id=self._session_span_id,
                        provider=self._memory_provider.name,
                        session_id=self._run_id,
                        agent_id=orch_agent_id,
                        role=self.config.orchestrator_role,
                        behavior_ref=self._orchestrator_role_prompt,
                        task=self.memory_task,
                        status=status,
                        output=output,
                        group_id=self._group_id,
                    )

                # 0a-ii. Store session recap for warm-start
                recap = _extract_session_recap(output)
                if recap:
                    try:
                        self._memory_provider.remember(
                            session_id=self._run_id,
                            agent_id=orch_agent_id,
                            role=self.config.orchestrator_role,
                            content=recap,
                            keywords=[
                                "session-recap",
                                "warm-start",
                                self.config.orchestrator_role,
                                self._run_id,
                            ],
                            scope="project",
                            group_id=self._group_id,
                        )
                    except Exception:
                        logger.warning(
                            "Session recap remember failed for role=%s (recap_len=%d)",
                            self.config.orchestrator_role,
                            len(recap),
                            exc_info=True,
                        )

        # 0b. Emit session_end trace + progress events before cleanup
        end_duration_ms = self._elapsed_ms(self._session_start_time)
        files_changed = self._detect_files_changed()

        if self._tracer is not None and self._session_span_id is not None:
            result = self._orchestrator_result
            exit_code = result.exit_code if result else 0
            self._tracer.session_end(
                span_id=self._session_span_id,
                merge_action="pending",
                duration_ms=end_duration_ms,
                output=result.output if result else "",
                exit_code=exit_code,
                files_changed=files_changed,
            )

        orch_result = self._orchestrator_result
        end_status = "ok" if (orch_result is None or orch_result.exit_code == 0) else "error"
        files_detail = f"{len(files_changed)} files changed" if files_changed else ""
        self._emit(
            "session_end", self.config.orchestrator_role,
            detail=files_detail, duration_ms=end_duration_ms, status=end_status,
        )

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

        # 4. Archive session directory for GUI history browsing
        self._archive_session_dir()

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

        # Level 2: second Ctrl+C within window → force shutdown
        if (
            self._interrupted
            and (now - self._last_sigint_time) < self._SIGINT_ESCALATION_WINDOW
        ):
            self._shutdown_orchestrator(force=True)
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

    def _shutdown_orchestrator(self, *, force: bool = False) -> None:
        """Cancel all agents via cascading cancel and mark session as shutting down.

        Uses ``cancel_agent()`` starting from the orchestrator so
        sub-agents are terminated in bottom-up order before the
        orchestrator itself.  Falls back to a flat kill if cancel
        fails or if there is no tracked orchestrator agent.
        """
        self._shutting_down = True
        if force:
            sys.stderr.write("\nForce shutting down...\n")
        else:
            sys.stderr.write(
                "\nShutting down... press Ctrl+C again to force quit.\n"
            )
        orch_id = (
            self._orchestrator_handle.agent_id
            if self._orchestrator_handle
            else None
        )
        if orch_id and orch_id in self._agent_info:
            try:
                self.cancel_agent(
                    orch_id,
                    reason=CancelReason.USER,
                    force=force,
                    timeout=5.0,
                )
                return
            except Exception:
                logger.debug("Cascading cancel failed, falling back to kill", exc_info=True)
        # Fallback: no agent tracking or cancel failed — flat kill.
        if self._orchestrator_handle:
            try:
                self.runtime.kill(self._orchestrator_handle)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Cancel signal watcher
    # ------------------------------------------------------------------

    _CANCEL_POLL_INTERVAL = 0.5  # seconds

    def _start_cancel_watcher(self) -> None:
        """Start a daemon thread that polls for cancel signal files."""
        session_dir = self._session_dir()
        # Create cancel directory so writers don't need to.
        os.makedirs(cancel_dir(session_dir), exist_ok=True)

        # Install SIGUSR1 handler to wake the watcher immediately.
        try:
            signal.signal(signal.SIGUSR1, self._handle_sigusr1)
        except (OSError, ValueError):
            # SIGUSR1 not available on all platforms (e.g., Windows).
            pass

        t = threading.Thread(
            target=self._cancel_watcher_loop,
            name="cancel-watcher",
            daemon=True,
        )
        t.start()

    def _handle_sigusr1(self, signum, frame) -> None:
        """SIGUSR1 wakes the cancel watcher by interrupting its sleep."""
        # No-op — the signal itself interrupts Event.wait().
        pass

    def _cancel_watcher_loop(self) -> None:
        """Poll for cancel signal files and trigger cancel_agent()."""
        session_dir = self._session_dir()
        while not self._cancel_watcher_stop.is_set():
            try:
                signals = read_cancel_signals(session_dir)
                for sig in signals:
                    self._process_cancel_signal(sig)
            except Exception:
                logger.debug("Cancel watcher error", exc_info=True)
            # Wait for stop or SIGUSR1 wake-up.
            self._cancel_watcher_stop.wait(timeout=self._CANCEL_POLL_INTERVAL)

    def _process_cancel_signal(self, sig: dict) -> None:
        """Process a single cancel signal from the watcher."""
        agent_id = sig.get("agent_id")
        force = sig.get("force", False)
        signal_path = sig.get("_path", "")

        try:
            if agent_id:
                # Cancel specific agent.
                self.cancel_agent(agent_id, reason=CancelReason.USER, force=force)
            else:
                # Cancel entire run — find the orchestrator.
                orch_id = None
                for aid, info in self._agent_info.items():
                    if info.get("parent") is None:
                        orch_id = aid
                        break
                if orch_id:
                    self.cancel_agent(orch_id, reason=CancelReason.USER, force=force)
        except Exception:
            logger.debug("Failed to process cancel signal: %s", signal_path, exc_info=True)
        finally:
            if signal_path:
                mark_signal_done(signal_path)

    # ------------------------------------------------------------------
    # Activity watcher — emits tool_start / tool_end trace events
    # ------------------------------------------------------------------

    _ACTIVITY_POLL_INTERVAL = 1.0  # seconds

    def _start_activity_watcher(self) -> None:
        """Start a daemon thread that monitors agent logs for activity."""
        if self._tracer is None:
            return  # Tracing disabled — nothing to emit.
        t = threading.Thread(
            target=self._activity_watcher_loop,
            name="activity-watcher",
            daemon=True,
        )
        t.start()

    def _activity_watcher_loop(self) -> None:
        """Poll agent .log files and emit tool_start/tool_end + activity_update trace events.

        Precondition: ``self._tracer`` is not None (checked by caller).
        """
        from strawpot.activity import (
            ActivityInfo,
            get_agent_log_path,
            parse_activity_structured,
            read_last_activity_line,
        )

        tracer = self._tracer
        assert tracer is not None  # guaranteed by _start_activity_watcher
        session_dir = self._session_dir()
        # Track current activity per agent: agent_id -> ActivityInfo
        current: dict[str, ActivityInfo] = {}

        while not self._cancel_watcher_stop.is_set():
            try:
                # Snapshot running agents to avoid holding locks.
                running_agents = [
                    (aid, self._agent_spans.get(aid, ""))
                    for aid, info in list(self._agent_info.items())
                    if info.get("state", AgentState.RUNNING) == AgentState.RUNNING
                ]

                for agent_id, span_id in running_agents:
                    log_path = get_agent_log_path(session_dir, agent_id)
                    last_line = read_last_activity_line(log_path)
                    parsed = parse_activity_structured(last_line) if last_line else None

                    prev = current.get(agent_id)

                    if parsed and (prev is None or parsed != prev):
                        # Activity changed — close previous, open new.
                        if prev is not None:
                            tracer.tool_end(
                                span_id=span_id,
                                agent_id=agent_id,
                                tool=prev.tool,
                            )
                        tracer.tool_start(
                            span_id=span_id,
                            agent_id=agent_id,
                            tool=parsed.tool,
                            summary=parsed.summary,
                        )
                        tracer.activity_update(
                            span_id=span_id,
                            agent_id=agent_id,
                            action=parsed.tool,
                            target=parsed.target,
                        )
                        current[agent_id] = parsed

                    elif parsed is None and prev is not None:
                        # Activity cleared.
                        tracer.tool_end(
                            span_id=span_id,
                            agent_id=agent_id,
                            tool=prev.tool,
                        )
                        del current[agent_id]

                # Emit tool_end for agents that stopped while active.
                running_ids = {aid for aid, _ in running_agents}
                for aid in list(current):
                    if aid not in running_ids:
                        prev = current.pop(aid)
                        span_id = self._agent_spans.get(aid, "")
                        tracer.tool_end(
                            span_id=span_id, agent_id=aid, tool=prev.tool,
                        )

            except OSError:
                logger.debug("Activity watcher I/O error", exc_info=True)
            except Exception:
                logger.warning("Activity watcher error", exc_info=True)

            self._cancel_watcher_stop.wait(timeout=self._ACTIVITY_POLL_INTERVAL)

        # Drain: emit tool_end for any activities still tracked at shutdown.
        for aid, prev in current.items():
            span_id = self._agent_spans.get(aid, "")
            try:
                tracer.tool_end(span_id=span_id, agent_id=aid, tool=prev.tool)
            except Exception:
                logger.debug("Failed to emit final tool_end for %s", aid)

    # ------------------------------------------------------------------
    # Denden server
    # ------------------------------------------------------------------

    def _start_denden_server(self) -> None:
        """Create and start the denden gRPC server.

        Always uses port 0 (OS-assigned) to avoid port collisions when
        multiple sessions run concurrently.  The actual bound address is
        stored in ``self._denden_addr`` and passed to child agents.
        """
        host = self.config.denden_addr.rsplit(":", 1)[0]
        self._server = DenDenServer(addr=f"{host}:0")
        self._server.on_delegate(self._handle_delegate)
        self._server.on_ask_user(self._handle_ask_user)
        self._server.on_remember(self._handle_remember)
        self._server.on_recall(self._handle_recall)
        if hasattr(self._server, "on_cancel"):
            self._server.on_cancel(self._handle_cancel)
        self._server.start()

        self._denden_addr = self._server.bound_addr

    def _stop_denden_server(self) -> None:
        """Stop the denden gRPC server."""
        if self._server is not None:
            try:
                self._server.stop(grace=5)
            except Exception:
                logger.debug("Failed to stop denden server", exc_info=True)

    # ------------------------------------------------------------------
    # Denden handlers
    # ------------------------------------------------------------------

    def _get_key_lock(self, cache_key: str) -> threading.RLock:
        """Return (or create) a per-cache-key RLock."""
        with self._delegation_lock:
            lock = self._delegation_key_locks.get(cache_key)
            if lock is None:
                lock = threading.RLock()
                self._delegation_key_locks[cache_key] = lock
            return lock

    def _cache_lookup(self, cache_key: str) -> tuple[str, "denden_pb2.DelegateResult"] | None:
        """Check cache under *_delegation_lock*; evict if TTL expired."""
        with self._delegation_lock:
            cached = self._delegation_cache.get(cache_key)
            if cached is None:
                return None
            cached_output, cached_delegate_res, cached_at = cached
            ttl = self.config.cache_ttl_seconds
            if ttl > 0 and (time.monotonic() - cached_at) > ttl:
                del self._delegation_cache[cache_key]
                return None
            return cached_output, cached_delegate_res

    def _cache_store(self, cache_key: str, output: str, delegate_res: "denden_pb2.DelegateResult") -> None:
        """Store a result in the cache under *_delegation_lock*."""
        with self._delegation_lock:
            max_entries = self.config.cache_max_entries
            if max_entries > 0 and len(self._delegation_cache) >= max_entries:
                self._delegation_cache.popitem(last=False)
            self._delegation_cache[cache_key] = (
                output,
                delegate_res,
                time.monotonic(),
            )

    @staticmethod
    def _elapsed_ms(t0: float) -> int:
        """Milliseconds elapsed since *t0* (from ``time.monotonic()``)."""
        return int((time.monotonic() - t0) * 1000)

    def _emit_event(self, event: ProgressEvent) -> None:
        """Emit a progress event to the registered callback.

        Swallows ``Exception`` subclasses -- ``BaseException`` (KeyboardInterrupt,
        SystemExit) still propagates.  On the first failure the callback is
        disabled for the rest of the session (circuit-breaker).
        """
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception:
            logger.warning("Event callback failed; progress output disabled", exc_info=True)
            self._on_event = None

    def _emit(
        self,
        kind: str,
        role: str,
        detail: str = "",
        duration_ms: int = 0,
        status: str = "",
        depth: int = 0,
    ) -> None:
        """Construct a :class:`ProgressEvent` with an auto-generated timestamp and emit it."""
        self._emit_event(ProgressEvent(
            kind=kind, role=role, detail=detail,
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_ms=duration_ms, status=status, depth=depth,
        ))

    def _handle_delegate(
        self, request: denden_pb2.DenDenRequest
    ) -> denden_pb2.DenDenResponse:
        """Handle a delegate request from a sub-agent.

        Thread-safe: a class-level ``_delegation_lock`` guards shared
        cache / counter state, and a per-cache-key ``RLock`` ensures
        that parallel identical requests are deduplicated — only the
        first thread executes the delegation while the others wait and
        then return the cached result.
        """
        payload = request.delegate
        trace = request.trace

        return_format = "JSON" if payload.task.return_format == denden_pb2.JSON else "TEXT"

        # Empty delegateTo means self-delegation — resolve to the agent's own role
        role_slug = payload.delegate_to
        if not role_slug:
            role_slug = self._agent_role(trace.agent_instance_id)

        delegate_req = DelegateRequest(
            role_slug=role_slug,
            task_text=payload.task.text,
            parent_agent_id=trace.agent_instance_id,
            parent_role=self._agent_role(trace.agent_instance_id),
            run_id=trace.run_id,
            depth=self._agent_depth(trace.agent_instance_id),
            return_format=return_format,
        )

        # Look up the span for the requesting agent (for call tree)
        requester_span = self._agent_spans.get(
            trace.agent_instance_id, self._session_span_id
        )

        # --- Max delegations check (before cache — cache hits count too) ---
        _denied_for_limit = False
        with self._delegation_lock:
            max_del = self.config.max_num_delegations
            if max_del > 0 and self._delegation_count >= max_del:
                _denied_for_limit = True
            else:
                self._delegation_count += 1
        if _denied_for_limit:
            reason = "DENY_DELEGATIONS_LIMIT"
            if self._tracer is not None:
                self._tracer.delegate_denied(
                    role=delegate_req.role_slug,
                    parent_span=requester_span,
                    reason=reason,
                    depth=delegate_req.depth,
                )
            self._emit(
                "delegate_denied", delegate_req.role_slug,
                detail="DENY_DELEGATIONS_LIMIT", status="denied",
                depth=delegate_req.depth,
            )
            return denied_response(
                request.request_id,
                reason,
                f"Session delegation limit reached ({max_del})",
            )

        # --- Cache check (fast path) ---
        cache_key: str | None = None
        key_lock: threading.RLock | None = None
        if self.config.cache_delegations:
            cache_key = self._delegation_cache_key(
                delegate_req.role_slug,
                delegate_req.task_text,
                return_format,
            )
            # Quick cache check before acquiring the per-key lock
            hit = self._cache_lookup(cache_key)
            if hit is not None:
                cached_output, cached_delegate_res = hit
                logger.info(
                    "Delegation cache hit for role=%s, output_len=%d, format=%s",
                    delegate_req.role_slug,
                    len(cached_output),
                    return_format,
                )
                if self._tracer is not None:
                    span = self._tracer.delegate_start(
                        role=delegate_req.role_slug,
                        parent_span=requester_span,
                        context=delegate_req.task_text,
                        depth=delegate_req.depth,
                        parent_agent_id=delegate_req.parent_agent_id,
                        cache_hit=True,
                    )
                    self._tracer.delegate_end(
                        span_id=span,
                        exit_code=0,
                        duration_ms=0,
                        output=cached_output,
                        role=delegate_req.role_slug,
                        cache_hit=True,
                    )
                self._emit(
                    "delegate_cached", delegate_req.role_slug,
                    status="cached", depth=delegate_req.depth,
                )
                return ok_response(
                    request.request_id,
                    delegate_result=cached_delegate_res,
                )

            # Acquire a per-key lock so parallel identical requests
            # are serialised: the first thread delegates, the rest wait
            # and pick up the cached result.
            key_lock = self._get_key_lock(cache_key)

        # If caching is enabled, hold the per-key lock for the
        # delegation so duplicate requests block here.
        if key_lock is not None:
            key_lock.acquire()
        try:
            t0 = time.monotonic()
            # Re-check cache after acquiring per-key lock (another
            # thread may have populated it while we were waiting).
            if cache_key is not None:
                hit = self._cache_lookup(cache_key)
                if hit is not None:
                    cached_output, cached_delegate_res = hit
                    logger.info(
                        "Delegation cache hit (after wait) for role=%s",
                        delegate_req.role_slug,
                    )
                    if self._tracer is not None:
                        span = self._tracer.delegate_start(
                            role=delegate_req.role_slug,
                            parent_span=requester_span,
                            context=delegate_req.task_text,
                            depth=delegate_req.depth,
                            parent_agent_id=delegate_req.parent_agent_id,
                            cache_hit=True,
                        )
                        self._tracer.delegate_end(
                            span_id=span,
                            exit_code=0,
                            duration_ms=0,
                            output=cached_output,
                            role=delegate_req.role_slug,
                            cache_hit=True,
                        )
                    self._emit(
                        "delegate_cached", delegate_req.role_slug,
                        status="cached", depth=delegate_req.depth,
                    )
                    return ok_response(
                        request.request_id,
                        delegate_result=cached_delegate_res,
                    )

            self._emit(
                "delegate_start", delegate_req.role_slug,
                detail=delegate_req.task_text[:60], depth=delegate_req.depth,
            )

            # Wrap register_agent to capture the spawned agent_id so
            # we can update its state when delegation completes.
            delegate_agent_id: str | None = None

            def _register_and_capture(
                agent_id: str, role: str, parent_id: str | None, pid: int | None = None,
            ) -> None:
                nonlocal delegate_agent_id
                delegate_agent_id = agent_id
                self._register_agent(agent_id, role, parent_id, pid)

            result = handle_delegate(
                request=delegate_req,
                config=self.config,
                runtime=self.wrapper,
                working_dir=self._env.path,
                session_dir=self._session_dir(),
                resolve_role=self._resolve_role,
                resolve_role_dirs=self._resolve_role_dirs,
                denden_addr=self._denden_addr,
                memory_provider=self._memory_provider,
                tracer=self._tracer,
                parent_span=requester_span,
                agent_spans=self._agent_spans,
                register_agent=_register_and_capture,
                files_dirs=self._files_dirs,
                group_id=self._group_id,
            )

            # Update agent state based on completion result.
            if delegate_agent_id is not None:
                end_state = (
                    AgentState.FAILED if result.exit_code != 0
                    else AgentState.COMPLETED
                )
                self._update_agent_state(delegate_agent_id, end_state)

            if result.exit_code != 0:
                self._emit(
                    "delegate_end", delegate_req.role_slug,
                    duration_ms=self._elapsed_ms(t0), status="error",
                    depth=delegate_req.depth,
                )
                msg = f"Sub-agent exited with code {result.exit_code}"
                if result.output:
                    tail = result.output[-2000:] if len(result.output) > 2000 else result.output
                    msg = f"{msg}\n\nAgent output:\n{tail}"
                return error_response(
                    request.request_id,
                    "ERR_SUBAGENT_NONZERO_EXIT",
                    msg,
                )
            # Build protobuf delegate result
            delegate_res = self._build_delegate_result(
                result.output, return_format
            )
            # Cache successful results with non-empty output
            if cache_key is not None and result.output:
                self._cache_store(cache_key, result.output, delegate_res)
            self._emit(
                "delegate_end", delegate_req.role_slug,
                duration_ms=self._elapsed_ms(t0), status="ok",
                depth=delegate_req.depth,
            )
            return ok_response(
                request.request_id,
                delegate_result=delegate_res,
            )
        except PolicyDenied as exc:
            if self._tracer is not None:
                self._tracer.delegate_denied(
                    role=delegate_req.role_slug,
                    parent_span=requester_span,
                    reason=exc.reason,
                    depth=delegate_req.depth,
                )
            self._emit(
                "delegate_denied", delegate_req.role_slug,
                detail=exc.reason, duration_ms=self._elapsed_ms(t0),
                status="denied", depth=delegate_req.depth,
            )
            return denied_response(
                request.request_id, exc.reason, str(exc)
            )
        except Exception as exc:
            logger.exception("Delegation failed for %s", request.request_id)
            self._emit(
                "delegate_end", delegate_req.role_slug,
                detail=str(exc), duration_ms=self._elapsed_ms(t0),
                status="error", depth=delegate_req.depth,
            )
            return error_response(
                request.request_id,
                "ERR_SUBAGENT_FAILURE",
                str(exc),
            )
        finally:
            if key_lock is not None:
                key_lock.release()

    def _handle_ask_user(
        self, request: denden_pb2.DenDenRequest
    ) -> denden_pb2.DenDenResponse:
        """Handle an ask_user request via the pluggable handler callback."""
        ask = request.ask_user
        trace = request.trace
        agent_id = trace.agent_instance_id
        role = self._agent_role(agent_id)
        requester_span = self._agent_spans.get(
            agent_id, self._session_span_id
        )

        req = AskUserRequest(
            question=ask.question,
            choices=list(ask.choices),
            default_value=ask.default_value,
            why=ask.why,
            response_format=ask.response_format,
        )

        # Trace: ask_user_start
        ask_span = None
        if self._tracer is not None:
            parts = [ask.question]
            if ask.choices:
                parts.append(f"\nChoices: {', '.join(ask.choices)}")
            if ask.default_value:
                parts.append(f"\nDefault: {ask.default_value}")
            if ask.why:
                parts.append(f"\nWhy: {ask.why}")
            ask_span = self._tracer.ask_user_start(
                parent_span=requester_span,
                request_id=request.request_id,
                question="\n".join(parts),
                agent_id=agent_id,
                role=role,
                session_id=self._run_id,
            )
        t0 = time.monotonic()
        depth = self._agent_depth(agent_id)
        self._emit(
            "ask_user_start", role,
            detail=ask.question[:60], depth=depth,
        )

        try:
            resp = self._ask_user_handler(req)
        except Exception as exc:
            if self._tracer is not None and ask_span is not None:
                self._tracer.ask_user_end(
                    span_id=ask_span,
                    request_id=request.request_id,
                    answer=f"ERROR: {exc}",
                    duration_ms=self._elapsed_ms(t0),
                    agent_id=agent_id,
                    role=role,
                    session_id=self._run_id,
                )
            self._emit(
                "ask_user_end", role, detail=str(exc),
                duration_ms=self._elapsed_ms(t0), status="error", depth=depth,
            )
            logger.exception("ask_user handler failed")
            return error_response(
                request.request_id,
                "ERR_ASK_USER",
                str(exc),
            )

        if self._tracer is not None and ask_span is not None:
            self._tracer.ask_user_end(
                span_id=ask_span,
                request_id=request.request_id,
                answer=resp.text,
                duration_ms=self._elapsed_ms(t0),
                agent_id=agent_id,
                role=role,
                session_id=self._run_id,
            )
        self._emit(
            "ask_user_end", role,
            duration_ms=self._elapsed_ms(t0), status="ok", depth=depth,
        )

        result = denden_pb2.AskUserResult(text=resp.text)
        if resp.json:
            import json as _json

            result.json.update(_json.loads(resp.json))
        return ok_response(request.request_id, ask_user_result=result)

    def _handle_remember(
        self, request: denden_pb2.DenDenRequest
    ) -> denden_pb2.DenDenResponse:
        """Handle a remember request by routing to the memory provider."""
        if self._memory_provider is None:
            return error_response(
                request.request_id,
                "ERR_NO_MEMORY",
                "no memory provider configured",
            )

        remember = request.remember
        trace = request.trace

        try:
            result = self._memory_provider.remember(
                session_id=trace.run_id,
                agent_id=trace.agent_instance_id,
                role=self._agent_role(trace.agent_instance_id),
                content=remember.content,
                keywords=list(remember.keywords) or None,
                scope=remember.scope or "project",
                group_id=self._group_id,
            )
            if self._tracer is not None:
                span_id = self._agent_spans.get(
                    trace.agent_instance_id, self._session_span_id
                )
                if span_id:
                    self._tracer.memory_remember(
                        span_id=span_id,
                        provider=self._memory_provider.name,
                        session_id=self._run_id or trace.run_id,
                        agent_id=trace.agent_instance_id,
                        role=self._agent_role(trace.agent_instance_id),
                        content=remember.content,
                        keywords=list(remember.keywords) or None,
                        scope=remember.scope or "project",
                        status=result.status,
                        entry_id=result.entry_id,
                        parent_agent_id=None,
                        group_id=self._group_id,
                    )
            return ok_response(
                request.request_id,
                remember_result=denden_pb2.RememberResult(
                    status=result.status,
                    entry_id=result.entry_id,
                ),
            )
        except Exception as exc:
            logger.exception("remember handler failed")
            return error_response(
                request.request_id,
                "ERR_REMEMBER",
                str(exc),
            )

    def _handle_recall(
        self, request: denden_pb2.DenDenRequest
    ) -> denden_pb2.DenDenResponse:
        """Handle a recall request by querying the memory provider."""
        if self._memory_provider is None:
            return error_response(
                request.request_id,
                "ERR_NO_MEMORY",
                "no memory provider configured",
            )

        recall = request.recall
        trace = request.trace

        try:
            result = self._memory_provider.recall(
                session_id=trace.run_id,
                agent_id=trace.agent_instance_id,
                role=self._agent_role(trace.agent_instance_id),
                query=recall.query,
                keywords=list(recall.keywords) or None,
                scope=recall.scope or "",
                max_results=recall.max_results or 10,
                group_id=self._group_id,
            )

            # Boost scores by importance and track recall frequency
            if result.entries:
                result = _boost_by_importance(
                    result, self._working_dir
                )
                _track_recall(
                    [e.entry_id for e in result.entries],
                    self._working_dir,
                )

            recall_entries = [
                denden_pb2.RecallEntry(
                    entry_id=e.entry_id,
                    content=e.content,
                    keywords=e.keywords,
                    scope=e.scope,
                    score=e.score,
                )
                for e in result.entries
            ]
            if self._tracer is not None:
                span_id = self._agent_spans.get(
                    trace.agent_instance_id, self._session_span_id
                )
                if span_id:
                    self._tracer.memory_recall(
                        span_id=span_id,
                        provider=self._memory_provider.name,
                        session_id=self._run_id or trace.run_id,
                        agent_id=trace.agent_instance_id,
                        role=self._agent_role(trace.agent_instance_id),
                        query=recall.query,
                        scope=recall.scope or "",
                        result_count=len(result.entries),
                        results=[
                            {"content": e.content, "score": e.score, "scope": e.scope}
                            for e in result.entries
                        ] if result.entries else None,
                        parent_agent_id=None,
                        group_id=self._group_id,
                    )
            return ok_response(
                request.request_id,
                recall_result=denden_pb2.RecallResult(entries=recall_entries),
            )
        except Exception as exc:
            logger.exception("recall handler failed")
            return error_response(
                request.request_id,
                "ERR_RECALL",
                str(exc),
            )

    def _handle_cancel(
        self, request: denden_pb2.DenDenRequest
    ) -> denden_pb2.DenDenResponse:
        """Handle a cancel request from a sub-agent.

        Validates that the requesting agent has authority to cancel the
        target (must be in the same session), then calls cancel_agent().
        """
        cancel = request.cancel
        trace = request.trace
        target_id = cancel.agent_id
        force = cancel.force

        # Validate the target agent exists.
        if target_id not in self._agent_info:
            return error_response(
                request.request_id,
                "ERR_CANCEL_AGENT_NOT_FOUND",
                f"Agent not found: {target_id}",
            )

        # Validate the requesting agent is in the same session.
        requester_id = trace.agent_instance_id
        if requester_id and requester_id not in self._agent_info:
            return error_response(
                request.request_id,
                "ERR_CANCEL_UNAUTHORIZED",
                "Requesting agent not found in this session",
            )

        try:
            cancelled = self.cancel_agent(
                target_id,
                reason=CancelReason.USER,
                force=force,
            )
            # Use getattr to safely check for cancel_result — the proto
            # may not have been regenerated yet in the denden package.
            if hasattr(denden_pb2, "CancelResult"):
                return ok_response(
                    request.request_id,
                    cancel_result=denden_pb2.CancelResult(
                        cancelled_agents=cancelled,
                    ),
                )
            # Fallback: return as generic OK if CancelResult not available.
            return ok_response(request.request_id)
        except Exception as exc:
            logger.exception("cancel handler failed")
            return error_response(
                request.request_id,
                "ERR_CANCEL",
                str(exc),
            )

    # ------------------------------------------------------------------
    # Session directory and state file
    # ------------------------------------------------------------------

    def _session_dir(self) -> str:
        """Return the session directory: ``.strawpot/sessions/<run_id>/``.

        Also creates a ``.strawpot/running/<run_id>`` symlink so active
        sessions can be discovered without scanning all session directories.
        """
        d = os.path.join(self._working_dir, ".strawpot", "sessions", self._run_id)
        os.makedirs(d, exist_ok=True)
        # Create running/ symlink at .strawpot/running/
        running_dir = os.path.join(self._working_dir, ".strawpot", "running")
        os.makedirs(running_dir, exist_ok=True)
        running_link = os.path.join(running_dir, self._run_id)
        if not os.path.islink(running_link):
            os.symlink(os.path.join("..", "sessions", self._run_id), running_link)
        return d

    def _sessions_base_dir(self) -> str:
        """Return the parent directory for all sessions."""
        return os.path.join(self._working_dir, ".strawpot", "sessions")

    def _detect_files_changed(self) -> list[str]:
        """Detect files changed during this session.

        Diffs uncommitted changes against HEAD.
        Returns an empty list for non-git repos or on error.
        """
        try:
            cwd = self._working_dir
            if not cwd:
                return []
            # Uncommitted changes (staged + unstaged)
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=cwd,
                capture_output=True, text=True, encoding="utf-8",
                timeout=10,
            )
            files: set[str] = set()
            if result.returncode == 0 and result.stdout.strip():
                files.update(result.stdout.strip().splitlines())
            return sorted(files)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return []

    def _write_session_file(self) -> None:
        """Write session state to disk."""
        if not (self._working_dir and self._run_id):
            return
        self._session_file = os.path.join(
            self._session_dir(), "session.json"
        )
        self._session_data = {
            "run_id": self._run_id,
            "working_dir": self._working_dir,
            "runtime": self.config.runtime,
            "denden_addr": self._denden_addr,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "task": self.task or None,
            "agents": {},
        }

        # Add registered agents
        for agent_id, info in self._agent_info.items():
            self._session_data["agents"][agent_id] = info

        with open(self._session_file, "w", encoding="utf-8") as f:
            json.dump(self._session_data, f, indent=2)

    def _archive_session_dir(self) -> None:
        """Swap the running symlink for an archive symlink.

        The session directory stays in place at
        ``.strawpot/sessions/<run_id>/``; only the symlinks change.
        """
        if not (self._working_dir and self._run_id):
            return
        strawpot_dir = os.path.join(self._working_dir, ".strawpot")
        # Remove running symlink
        running_link = os.path.join(strawpot_dir, "running", self._run_id)
        if os.path.islink(running_link):
            os.unlink(running_link)
        # Create archive symlink
        archive_dir = os.path.join(strawpot_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        archive_link = os.path.join(archive_dir, self._run_id)
        if not os.path.exists(archive_link):
            os.symlink(os.path.join("..", "sessions", self._run_id), archive_link)

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
        """Record an agent in the session state (in-memory and on-disk).

        Thread-safe: acquires ``_delegation_lock`` to avoid races with
        the DenDen handler thread that may be updating agent states.
        """
        with self._delegation_lock:
            self._agent_info[agent_id] = {
                "role": role,
                "runtime": self.config.runtime,
                "parent": parent_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "pid": pid,
                "state": AgentState.RUNNING,
            }
            self._write_session_file()

    def _update_agent_state(
        self,
        agent_id: str,
        state: AgentState,
        cancel_reason: CancelReason | None = None,
    ) -> None:
        """Update the state of a registered agent (in-memory and on-disk).

        Thread-safe: acquires ``_delegation_lock`` to avoid races with
        the DenDen handler thread that may be registering new agents.
        """
        with self._delegation_lock:
            info = self._agent_info.get(agent_id)
            if info is None:
                return
            info["state"] = state
            if cancel_reason is not None:
                info["cancel_reason"] = cancel_reason
            self._write_session_file()

    def cancel_agent(
        self,
        agent_id: str,
        *,
        reason: CancelReason = CancelReason.USER,
        force: bool = False,
        timeout: float = 10.0,
    ) -> list[str]:
        """Cancel an agent and all its descendants (cascading).

        Descendants are cancelled in bottom-up order (leaves first) to
        prevent orphaned sub-agents.  Each agent goes through a graceful
        phase (SIGINT) followed by a force kill (SIGKILL) if it does not
        exit within *timeout* seconds.

        Args:
            agent_id: The agent to cancel.
            reason: Why the agent is being cancelled.
            force: Skip graceful interrupt and kill immediately.
            timeout: Seconds to wait for graceful shutdown before force kill.

        Returns:
            List of agent IDs that were cancelled (including *agent_id*).
        """
        # Build the cancel order: descendants bottom-up, then the target.
        subtree = get_subtree_bottom_up(agent_id, self._agent_info)
        cancel_order = subtree + [agent_id]

        # Emit cancel_start trace event.
        cancel_start_time = time.monotonic()
        if self._tracer is not None and self._session_span_id is not None:
            self._tracer.agent_cancel_start(
                span_id=self._session_span_id,
                agent_id=agent_id,
                reason=str(reason),
                force=force,
                descendants=subtree,
            )

        # Emit cancel_start progress event.
        info = self._agent_info.get(agent_id)
        role = info.get("role", "unknown") if info else "unknown"
        desc_count = len(subtree)
        desc_detail = f" + {desc_count} descendants" if desc_count > 0 else ""
        self._emit(
            "cancel_start", role,
            detail=f"{agent_id[:8]}{desc_detail}",
            depth=self._agent_depth(agent_id),
        )

        cancelled: list[str] = []
        for i, aid in enumerate(cancel_order):
            info = self._agent_info.get(aid)
            if info is None:
                continue

            # Determine the cancel reason for this agent.
            if aid == agent_id:
                agent_reason = reason
            elif info.get("parent") == agent_id:
                agent_reason = CancelReason.PARENT
            else:
                agent_reason = CancelReason.ANCESTOR

            # Skip agents that already finished.
            current_state = info.get("state")
            if current_state in (
                AgentState.COMPLETED,
                AgentState.FAILED,
                AgentState.CANCELLED,
            ):
                cancelled.append(aid)
                continue

            # Mark as CANCELLING.
            self._update_agent_state(aid, AgentState.CANCELLING, agent_reason)

            pid = info.get("pid")
            if pid is None or not is_pid_alive(pid):
                # No live process — just mark as cancelled.
                self._update_agent_state(aid, AgentState.CANCELLED, agent_reason)
                cancelled.append(aid)
                continue

            if not force:
                # Graceful interrupt: send SIGINT.
                try:
                    os.kill(pid, signal.SIGINT)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

                # Wait for graceful shutdown.
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline and is_pid_alive(pid):
                    time.sleep(0.1)

            # Force kill if still alive (or if force=True).
            if is_pid_alive(pid):
                try:
                    kill_process_tree(pid)
                except Exception:
                    logger.debug("Failed to kill agent %s (pid=%s)", aid, pid)

            self._update_agent_state(aid, AgentState.CANCELLED, agent_reason)
            cancelled.append(aid)

        # Emit cancel_complete trace event.
        cancel_duration_ms = int((time.monotonic() - cancel_start_time) * 1000)
        if self._tracer is not None and self._session_span_id is not None:
            self._tracer.agent_cancel_complete(
                span_id=self._session_span_id,
                agent_id=agent_id,
                cancelled_agents=cancelled,
                duration_ms=cancel_duration_ms,
            )

        # Emit cancel_complete progress event.
        self._emit(
            "cancel_complete", role,
            detail=f"{len(cancelled)} agents",
            duration_ms=cancel_duration_ms,
            depth=self._agent_depth(agent_id),
        )

        return cancelled

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

    @staticmethod
    def _delegation_cache_key(
        role_slug: str, task_text: str, return_format: str
    ) -> str:
        raw = f"{role_slug}\0{task_text}\0{return_format}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_delegate_result(
        output: str, return_format: str
    ) -> "denden_pb2.DelegateResult":
        delegate_res = denden_pb2.DelegateResult()
        if output:
            if return_format == "JSON":
                try:
                    parsed = json.loads(output)
                    if isinstance(parsed, dict):
                        delegate_res.json.update(parsed)
                    else:
                        delegate_res.text = output
                except (json.JSONDecodeError, ValueError):
                    delegate_res.text = output
            else:
                delegate_res.text = output
        return delegate_res
