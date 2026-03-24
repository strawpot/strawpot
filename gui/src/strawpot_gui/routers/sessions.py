"""Session endpoints."""

import json
import os
import re
import signal
import shutil
import subprocess

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, field_validator

from strawpot.config import load_config
from strawpot_gui.db import _parse_trace, get_db_conn
from strawpot_gui.event_bus import SessionEvent, event_bus

router = APIRouter(prefix="/api", tags=["sessions"])

import logging as _logging

_logger = _logging.getLogger(__name__)


def _drain_pending_task(conn, conversation_id: int | None) -> None:
    """If the conversation has queued tasks, launch the next one (FIFO)."""
    if not conversation_id:
        return

    # Only drain if no session is currently active for this conversation
    active = conn.execute(
        "SELECT 1 FROM sessions "
        "WHERE conversation_id = ? AND status IN ('starting', 'running') LIMIT 1",
        (conversation_id,),
    ).fetchone()
    if active:
        return

    # Pop the oldest queued task
    queued = conn.execute(
        "SELECT * FROM conversation_task_queue "
        "WHERE conversation_id = ? ORDER BY id ASC LIMIT 1",
        (conversation_id,),
    ).fetchone()
    if not queued:
        return

    # Delete from queue before launching (prevents re-entry)
    conn.execute("DELETE FROM conversation_task_queue WHERE id = ?", (queued["id"],))

    conv = conn.execute(
        "SELECT id, project_id, title FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if not conv:
        return

    import json as _json

    from strawpot_gui.routers.conversations import ConversationTask, _launch_conversation_task

    try:
        body = ConversationTask(
            task=queued["task"],
            role=queued["role"],
            context_files=_json.loads(queued["context_files"]) if queued["context_files"] else None,
            interactive=bool(queued["interactive"]),
            system_prompt=queued["system_prompt"],
            runtime=queued["runtime"],
            memory=queued["memory"],
            max_num_delegations=queued["max_num_delegations"],
            cache_delegations=bool(queued["cache_delegations"]) if queued["cache_delegations"] is not None else None,
            cache_max_entries=queued["cache_max_entries"],
            cache_ttl_seconds=queued["cache_ttl_seconds"],
            source=queued["source"],
            source_id=queued["source_id"],
        )
        _launch_conversation_task(conn, conv, body)
        _logger.info("Drained queued task %d for conversation %d", queued["id"], conversation_id)
    except Exception:
        _logger.exception(
            "Failed to drain queued task %d for conversation %d", queued["id"], conversation_id
        )


def _read_startup_error(run_id: str) -> str | None:
    """Read the stderr log captured during session launch."""
    log_path = Path.home() / ".strawpot" / "logs" / f"{run_id}.log"
    try:
        text = log_path.read_text(encoding="utf-8").strip()
        return text if text else None
    except OSError:
        return None


def _refresh_session_status(conn, run_id: str) -> None:
    """Re-check status for a starting/running session from disk.

    Reads session.json for PID liveness and trace.jsonl for completion.
    Updates the DB row if the status has changed.
    """
    row = conn.execute(
        "SELECT status, session_dir, started_at, conversation_id FROM sessions WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if not row or row["status"] not in ("starting", "running"):
        return

    session_dir = row["session_dir"]

    # If session directory doesn't exist, give subprocess time to create it
    if not os.path.isdir(session_dir):
        started_at = row["started_at"]
        if started_at:
            from datetime import datetime, timezone

            age = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(started_at)
            ).total_seconds()
            if age > 15:
                error = _read_startup_error(run_id)
                conn.execute(
                    "UPDATE sessions SET status = 'failed', summary = ? WHERE run_id = ?",
                    (error, run_id),
                )
                _drain_pending_task(conn, row["conversation_id"])
        return

    session_json = os.path.join(session_dir, "session.json")

    # Try to read session.json
    try:
        with open(session_json, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        # session.json not yet written — still starting; fail after 15s
        started_at = row["started_at"]
        if started_at:
            from datetime import datetime, timezone

            age = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(started_at)
            ).total_seconds()
            if age > 15:
                error = _read_startup_error(run_id)
                conn.execute(
                    "UPDATE sessions SET status = 'failed', summary = ? WHERE run_id = ?",
                    (error, run_id),
                )
                _drain_pending_task(conn, row["conversation_id"])
        return

    # Check trace for completion
    trace_path = os.path.join(session_dir, "trace.jsonl")
    trace_info = _parse_trace(trace_path, session_dir)

    if trace_info.get("exit_code") is not None or "ended_at" in trace_info:
        # Session has ended
        exit_code = trace_info.get("exit_code")
        status = "completed" if exit_code == 0 else "failed"
        conn.execute(
            """UPDATE sessions
               SET status = ?, ended_at = ?, duration_ms = ?,
                   exit_code = ?, summary = COALESCE(summary, ?)
               WHERE run_id = ?""",
            (
                status,
                trace_info.get("ended_at"),
                trace_info.get("duration_ms"),
                exit_code,
                trace_info.get("summary"),
                run_id,
            ),
        )
        # Auto-submit pending task if conversation has one queued
        _drain_pending_task(conn, row["conversation_id"])
        return

    # Check PID liveness
    pid = data.get("pid")
    if pid is not None:
        try:
            os.kill(pid, 0)
            # Process alive — mark running if still starting
            if row["status"] == "starting":
                conn.execute(
                    "UPDATE sessions SET status = 'running' WHERE run_id = ?",
                    (run_id,),
                )
        except (ProcessLookupError, OSError):
            # Process gone without trace end — mark failed
            conn.execute(
                "UPDATE sessions SET status = 'failed' WHERE run_id = ?",
                (run_id,),
            )
            _drain_pending_task(conn, row["conversation_id"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SessionOverrides(BaseModel):
    runtime: str | None = None
    memory: str | None = None
    cache_delegations: bool | None = None
    cache_max_entries: int | None = None
    cache_ttl_seconds: int | None = None
    max_num_delegations: int | None = None


class SessionLaunch(BaseModel):
    project_id: int
    task: str
    role: str | None = None
    overrides: SessionOverrides | None = None
    context_files: list[str] | None = None
    system_prompt: str | None = None
    interactive: bool = False
    conversation_id: int | None = None

    @field_validator("task")
    @classmethod
    def task_must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task must be non-empty")
        return v.strip()


def launch_session_subprocess(
    conn,
    project_id: int,
    task: str,
    *,
    user_task: str | None = None,
    memory_task: str | None = None,
    role: str | None = None,
    system_prompt: str | None = None,
    runtime_override: str | None = None,
    context_files: list[str] | None = None,
    memory_override: str | None = None,
    cache_delegations: bool | None = None,
    cache_max_entries: int | None = None,
    cache_ttl_seconds: int | None = None,
    max_num_delegations: int | None = None,
    schedule_id: int | None = None,
    interactive: bool = False,
    conversation_id: int | None = None,
) -> str:
    """Launch a headless session subprocess. Returns run_id.

    Shared by the HTTP endpoint and the cron scheduler.
    Raises RuntimeError on failure (caller decides HTTP vs log response).
    """
    project = conn.execute(
        "SELECT id, working_dir FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    if not project:
        raise RuntimeError("Project not found")

    working_dir = project["working_dir"]
    if not Path(working_dir).is_dir():
        raise RuntimeError("Project working directory does not exist")

    # Load project config for defaults
    config = load_config(Path(working_dir))
    resolved_role = role or config.orchestrator_role
    isolation = config.isolation

    # Resolve runtime: explicit override > explicit config > role default_agent > config default
    runtime = runtime_override
    if not runtime:
        from strawpot.config import has_explicit_runtime

        if has_explicit_runtime(Path(working_dir)):
            runtime = config.runtime
    if not runtime:
        role_cfg = config.roles.get(resolved_role, {})
        runtime = role_cfg.get("default_agent")
    if not runtime:
        try:
            from strawpot.delegation import _get_default_agent
            from strawhub.resolver import resolve as _resolve

            resolved = _resolve(resolved_role, kind="role")
            runtime = _get_default_agent(resolved["path"])
        except Exception:
            pass
    if not runtime:
        runtime = config.runtime

    # Pre-generate run_id
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    session_dir = str(Path(working_dir) / ".strawpot" / "sessions" / run_id)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """INSERT INTO sessions
           (run_id, project_id, role, runtime, isolation, status,
            started_at, session_dir, task, user_task, schedule_id, interactive, conversation_id)
           VALUES (?, ?, ?, ?, ?, 'starting', ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, project_id, resolved_role, runtime, isolation, now,
         session_dir, task, user_task,
         schedule_id, 1 if interactive else 0, conversation_id),
    )

    # Resolve context files and append to task
    task_text = task
    if context_files:
        files_dir = Path(working_dir) / ".strawpot" / "files"
        resolved: list[str] = []
        for rel_path in context_files:
            fp = (files_dir / rel_path).resolve()
            if not fp.is_relative_to(files_dir.resolve()):
                raise RuntimeError(f"Invalid file path: {rel_path}")
            if not fp.is_file():
                raise RuntimeError(f"File not found: {rel_path}")
            resolved.append(str(fp))
        if resolved:
            listing = "\n".join(f"- {p}" for p in resolved)
            task_text = (
                f"{task_text}\n\n"
                f"<context-files>\n"
                f"The following project files are attached as reference. "
                f"Read them for context:\n{listing}\n"
                f"</context-files>"
            )

    # Build CLI command
    strawpot_cmd = shutil.which("strawpot")
    if strawpot_cmd is None:
        raise RuntimeError("strawpot CLI not found on PATH")

    cmd = [
        strawpot_cmd, "start",
        "--headless",
        "--task", task_text,
        "--run-id", run_id,
    ]
    if role:
        cmd.extend(["--role", role])
    # Always pass the resolved runtime so DB record and CLI agree.
    cmd.extend(["--runtime", runtime])
    if memory_override:
        cmd.extend(["--memory", memory_override])
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    if memory_task:
        cmd.extend(["--memory-task", memory_task])
    if cache_delegations is False:
        cmd.append("--no-cache-delegations")
    if cache_max_entries is not None:
        cmd.extend(["--cache-max-entries", str(cache_max_entries)])
    if cache_ttl_seconds is not None:
        cmd.extend(["--cache-ttl-seconds", str(cache_ttl_seconds)])
    if max_num_delegations is not None:
        cmd.extend(["--max-num-delegations", str(max_num_delegations)])
    if conversation_id is not None:
        cmd.extend(["--group-id", str(conversation_id)])

    # Ensure subprocess can find user-installed tools (claude, etc.)
    # even when the server was started from a limited-PATH context.
    env = os.environ.copy()
    home = Path.home()
    extra_paths = [
        str(home / ".local" / "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]
    existing = env.get("PATH", "")
    env["PATH"] = ":".join(extra_paths) + ":" + existing

    if interactive:
        env["STRAWPOT_ASK_USER_BRIDGE"] = "file"

    # Write stderr to a log file so errors are captured even if the session
    # dir is never created (e.g. config validation failure on startup).
    log_dir = Path(home) / ".strawpot" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stderr_log = log_dir / f"{run_id}.log"

    try:
        stderr_fh = open(stderr_log, "w")
        subprocess.Popen(
            cmd,
            cwd=working_dir,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=stderr_fh,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except OSError:
        stderr_fh.close()
        conn.execute("DELETE FROM sessions WHERE run_id = ?", (run_id,))
        raise RuntimeError("Failed to start session subprocess")

    event_bus.publish(SessionEvent(
        kind="session_started",
        run_id=run_id,
        project_id=project_id,
    ))

    return run_id


@router.post("/sessions", status_code=201)
def launch_session(body: SessionLaunch, conn=Depends(get_db_conn)):
    """Launch a new headless session as a detached subprocess."""
    _ERROR_STATUS = {
        "Project not found": 404,
        "Project working directory does not exist": 422,
    }
    try:
        run_id = launch_session_subprocess(
            conn,
            body.project_id,
            body.task,
            role=body.role,
            system_prompt=body.system_prompt,
            runtime_override=body.overrides.runtime if body.overrides else None,
            memory_override=body.overrides.memory if body.overrides else None,
            cache_delegations=body.overrides.cache_delegations if body.overrides else None,
            cache_max_entries=body.overrides.cache_max_entries if body.overrides else None,
            cache_ttl_seconds=body.overrides.cache_ttl_seconds if body.overrides else None,
            max_num_delegations=body.overrides.max_num_delegations if body.overrides else None,
            context_files=body.context_files,
            interactive=body.interactive,
            conversation_id=body.conversation_id,
        )
    except RuntimeError as e:
        status = _ERROR_STATUS.get(str(e), 500)
        raise HTTPException(status, str(e))

    return {"run_id": run_id, "status": "starting"}


@router.get("/sessions")
def list_all_sessions(
    project_id: int | None = Query(None),
    status: str | None = Query(None),
    since: str | None = Query(None, description="ISO 8601 datetime lower bound"),
    until: str | None = Query(None, description="ISO 8601 datetime upper bound"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    conn=Depends(get_db_conn),
):
    """List sessions across all projects with optional filters and pagination."""
    # Refresh active sessions before listing
    active = conn.execute(
        "SELECT run_id FROM sessions WHERE status IN ('starting', 'running')"
    ).fetchall()
    for r in active:
        _refresh_session_status(conn, r["run_id"])

    clauses: list[str] = []
    params: list = []

    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    else:
        clauses.append("project_id != 0")
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if since is not None:
        clauses.append("started_at >= ?")
        params.append(since)
    if until is not None:
        clauses.append("started_at <= ?")
        params.append(until)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    total = conn.execute(
        f"SELECT count(*) FROM sessions{where}", params
    ).fetchone()[0]

    offset = (page - 1) * per_page
    rows = conn.execute(
        f"SELECT run_id, project_id, role, runtime, isolation, status,"
        f"       started_at, ended_at, duration_ms, exit_code, task, user_task"
        f"  FROM sessions{where} ORDER BY started_at DESC"
        f"  LIMIT ? OFFSET ?",
        [*params, per_page, offset],
    ).fetchall()

    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/projects/{project_id}/sessions")
def list_sessions(
    project_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    conn=Depends(get_db_conn),
):
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    # Refresh active sessions for this project
    active = conn.execute(
        "SELECT run_id FROM sessions WHERE project_id = ? AND status IN ('starting', 'running')",
        (project_id,),
    ).fetchall()
    for r in active:
        _refresh_session_status(conn, r["run_id"])

    total = conn.execute(
        "SELECT count(*) FROM sessions WHERE project_id = ?", (project_id,)
    ).fetchone()[0]

    offset = (page - 1) * per_page
    rows = conn.execute(
        "SELECT run_id, project_id, role, runtime, isolation, status,"
        "       started_at, ended_at, duration_ms, exit_code, task, user_task"
        "  FROM sessions WHERE project_id = ? ORDER BY started_at DESC"
        "  LIMIT ? OFFSET ?",
        (project_id, per_page, offset),
    ).fetchall()

    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/projects/{project_id}/sessions/{run_id}")
def get_session(project_id: int, run_id: str, conn=Depends(get_db_conn)):
    # Refresh status for active sessions before returning
    _refresh_session_status(conn, run_id)

    row = conn.execute(
        "SELECT run_id, project_id, role, runtime, isolation, status,"
        "       started_at, ended_at, duration_ms, exit_code, task, user_task,"
        "       session_dir, interactive"
        "  FROM sessions WHERE project_id = ? AND run_id = ?",
        (project_id, run_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")

    result = {
        k: row[k]
        for k in row.keys()
        if k not in ("session_dir",)
    }
    result["interactive"] = bool(result.get("interactive"))

    session_dir = Path(row["session_dir"])

    # Load agents from session.json
    agents = {}
    session_json = session_dir / "session.json"
    try:
        data = json.loads(session_json.read_text(encoding="utf-8"))
        agents = data.get("agents", {})
    except (OSError, json.JSONDecodeError):
        pass
    result["agents"] = agents

    # Load trace events from trace.jsonl
    events = []
    trace_path = session_dir / "trace.jsonl"
    try:
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        pass
    result["events"] = events

    # Build agent tree from session.json + trace.jsonl
    from strawpot_gui.routers.ws import _build_full_state
    state, _ = _build_full_state(str(session_dir))
    result["tree"] = state.to_dict()

    return result


@router.post("/sessions/{run_id}/stop")
def stop_session(run_id: str, conn=Depends(get_db_conn)):
    """Stop a running session by sending SIGTERM to the orchestrator PID."""
    row = conn.execute(
        "SELECT run_id, status, session_dir, project_id, conversation_id FROM sessions WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")

    if row["status"] not in ("starting", "running"):
        raise HTTPException(
            409, f"Session is not running (status: {row['status']})"
        )

    project_id = row["project_id"]
    conversation_id = row["conversation_id"]

    def _mark_stopped_and_drain() -> dict:
        conn.execute(
            "UPDATE sessions SET status = 'stopped', summary = COALESCE(summary, 'Interrupted') WHERE run_id = ?",
            (run_id,),
        )
        _drain_pending_task(conn, conversation_id)
        event_bus.publish(SessionEvent(kind="session_stopped", run_id=run_id, project_id=project_id))
        return {"run_id": run_id, "status": "stopped"}

    # Read PID from session.json
    session_dir = Path(row["session_dir"])
    session_json = session_dir / "session.json"
    try:
        data = json.loads(session_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # session.json not created yet — session never fully started
        return _mark_stopped_and_drain()

    pid = data.get("pid")
    if pid is None:
        return _mark_stopped_and_drain()

    # Check liveness and send SIGTERM
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        # Process already gone
        return _mark_stopped_and_drain()

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        # Race: died between check and kill
        return _mark_stopped_and_drain()

    conn.execute(
        "UPDATE sessions SET status = 'stopped' WHERE run_id = ?",
        (run_id,),
    )
    _drain_pending_task(conn, conversation_id)
    event_bus.publish(SessionEvent(kind="session_stopped", run_id=run_id, project_id=project_id))
    return {"run_id": run_id, "status": "stopped"}


@router.delete("/sessions/{run_id}")
def delete_session(run_id: str, conn=Depends(get_db_conn)):
    """Delete an archived session (DB row + on-disk files)."""
    row = conn.execute(
        "SELECT run_id, status, session_dir, project_id FROM sessions WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")

    if row["status"] in ("starting", "running"):
        raise HTTPException(409, "Cannot delete a running session — stop it first")

    session_dir = row["session_dir"]
    project_id = row["project_id"]

    # Remove DB row
    conn.execute("DELETE FROM sessions WHERE run_id = ?", (run_id,))
    conn.commit()

    # Remove on-disk session directory
    if session_dir:
        shutil.rmtree(session_dir, ignore_errors=True)

        # Clean up symlinks in archive/ and running/
        strawpot_dir = str(Path(session_dir).parent.parent)
        for subdir in ("archive", "running"):
            link = os.path.join(strawpot_dir, subdir, run_id)
            try:
                os.remove(link)
            except OSError:
                pass

    event_bus.publish(SessionEvent(
        kind="session_deleted",
        run_id=run_id,
        project_id=project_id,
    ))

    return {"ok": True}


_ARTIFACT_HASH_RE = re.compile(r"^[0-9a-f]{12}$")


@router.get("/sessions/{run_id}/artifacts/{artifact_hash}")
def get_artifact(run_id: str, artifact_hash: str, conn=Depends(get_db_conn)):
    """Serve an artifact file by its content hash."""
    if not _ARTIFACT_HASH_RE.match(artifact_hash):
        raise HTTPException(400, "Invalid artifact hash")

    row = conn.execute(
        "SELECT session_dir FROM sessions WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")

    artifact_path = Path(row["session_dir"]) / "artifacts" / artifact_hash
    if not artifact_path.is_file():
        raise HTTPException(404, "Artifact not found")

    try:
        content = artifact_path.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(500, "Failed to read artifact")

    return PlainTextResponse(content)
