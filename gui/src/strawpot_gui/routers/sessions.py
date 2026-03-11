"""Session endpoints."""

import json
import os
import re
import signal
import shutil
import subprocess
import time
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


def _refresh_session_status(conn, run_id: str) -> None:
    """Re-check status for a starting/running session from disk.

    Reads session.json for PID liveness and trace.jsonl for completion.
    Updates the DB row if the status has changed.
    """
    row = conn.execute(
        "SELECT status, session_dir, started_at FROM sessions WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if not row or row["status"] not in ("starting", "running"):
        return

    session_dir = row["session_dir"]

    # If session directory doesn't exist, give subprocess time to create it
    if not os.path.isdir(session_dir):
        started_at = row.get("started_at") if hasattr(row, "get") else None
        if started_at:
            from datetime import datetime, timezone

            age = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(started_at)
            ).total_seconds()
            if age > 15:
                conn.execute(
                    "UPDATE sessions SET status = 'failed' WHERE run_id = ?",
                    (run_id,),
                )
        return

    session_json = os.path.join(session_dir, "session.json")

    # Try to read session.json
    try:
        with open(session_json, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        # session.json not yet written — still starting
        return

    # Check trace for completion
    trace_path = os.path.join(session_dir, "trace.jsonl")
    trace_info = _parse_trace(trace_path)

    if trace_info.get("exit_code") is not None or "ended_at" in trace_info:
        # Session has ended
        exit_code = trace_info.get("exit_code")
        status = "completed" if exit_code == 0 else "failed"
        conn.execute(
            """UPDATE sessions
               SET status = ?, ended_at = ?, duration_ms = ?,
                   exit_code = ?
               WHERE run_id = ?""",
            (
                status,
                trace_info.get("ended_at"),
                trace_info.get("duration_ms"),
                exit_code,
                run_id,
            ),
        )
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

    # Resolve runtime: explicit override > role default_agent > config default
    runtime = runtime_override
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
            started_at, session_dir, task, schedule_id, interactive)
           VALUES (?, ?, ?, ?, ?, 'starting', ?, ?, ?, ?, ?)""",
        (run_id, project_id, resolved_role, runtime, isolation, now,
         session_dir, task, schedule_id, 1 if interactive else 0),
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
    if runtime_override:
        cmd.extend(["--runtime", runtime_override])
    if memory_override:
        cmd.extend(["--memory", memory_override])
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    if cache_delegations is False:
        cmd.append("--no-cache-delegations")
    if cache_max_entries is not None:
        cmd.extend(["--cache-max-entries", str(cache_max_entries)])
    if cache_ttl_seconds is not None:
        cmd.extend(["--cache-ttl-seconds", str(cache_ttl_seconds)])
    if max_num_delegations is not None:
        cmd.extend(["--max-num-delegations", str(max_num_delegations)])

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

    try:
        subprocess.Popen(
            cmd,
            cwd=working_dir,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except OSError:
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
        f"       started_at, ended_at, duration_ms, exit_code, task"
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
        "       started_at, ended_at, duration_ms, exit_code, task"
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
        "       started_at, ended_at, duration_ms, exit_code, task,"
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

    return result


@router.post("/sessions/{run_id}/stop")
def stop_session(run_id: str, conn=Depends(get_db_conn)):
    """Stop a running session by sending SIGTERM to the orchestrator PID."""
    row = conn.execute(
        "SELECT run_id, status, session_dir, project_id FROM sessions WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")

    if row["status"] not in ("starting", "running"):
        raise HTTPException(
            409, f"Session is not running (status: {row['status']})"
        )

    project_id = row["project_id"]

    # Read PID from session.json
    session_dir = Path(row["session_dir"])
    session_json = session_dir / "session.json"
    try:
        data = json.loads(session_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # session.json not created yet — session never fully started
        conn.execute(
            "UPDATE sessions SET status = 'stopped' WHERE run_id = ?",
            (run_id,),
        )
        event_bus.publish(SessionEvent(kind="session_stopped", run_id=run_id, project_id=project_id))
        return {"run_id": run_id, "status": "stopped"}

    pid = data.get("pid")
    if pid is None:
        # No PID recorded — mark as stopped
        conn.execute(
            "UPDATE sessions SET status = 'stopped' WHERE run_id = ?",
            (run_id,),
        )
        event_bus.publish(SessionEvent(kind="session_stopped", run_id=run_id, project_id=project_id))
        return {"run_id": run_id, "status": "stopped"}

    # Check liveness and send SIGTERM
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        # Process already gone
        conn.execute(
            "UPDATE sessions SET status = 'stopped' WHERE run_id = ?",
            (run_id,),
        )
        event_bus.publish(SessionEvent(kind="session_stopped", run_id=run_id, project_id=project_id))
        return {"run_id": run_id, "status": "stopped"}

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        # Race: died between check and kill
        conn.execute(
            "UPDATE sessions SET status = 'stopped' WHERE run_id = ?",
            (run_id,),
        )
        event_bus.publish(SessionEvent(kind="session_stopped", run_id=run_id, project_id=project_id))
        return {"run_id": run_id, "status": "stopped"}

    conn.execute(
        "UPDATE sessions SET status = 'stopped' WHERE run_id = ?",
        (run_id,),
    )
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


class AskUserResponseBody(BaseModel):
    request_id: str
    text: str = ""


@router.post("/sessions/{run_id}/respond")
def respond_to_ask_user(
    run_id: str,
    body: AskUserResponseBody,
    conn=Depends(get_db_conn),
):
    """Write a response to a pending ask_user request."""
    row = conn.execute(
        "SELECT run_id, status, session_dir FROM sessions WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")

    if row["status"] not in ("starting", "running"):
        raise HTTPException(409, f"Session is not active (status: {row['status']})")

    session_dir = Path(row["session_dir"])
    pending_path = session_dir / "ask_user_pending.json"

    if not pending_path.is_file():
        raise HTTPException(404, "No pending ask_user request")

    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(500, "Failed to read pending request")

    if pending.get("request_id") != body.request_id:
        raise HTTPException(409, "request_id does not match pending request")

    response_path = session_dir / "ask_user_response.json"
    resp_data = {
        "request_id": body.request_id,
        "text": body.text,
    }

    tmp_path = str(response_path) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(resp_data, f, indent=2)
    os.replace(tmp_path, str(response_path))

    # Persist the user message to chat history
    chat_path = session_dir / "chat_messages.jsonl"
    entry = json.dumps({
        "id": f"user-{body.request_id}",
        "role": "user",
        "text": body.text,
        "timestamp": time.time(),
    })
    with open(chat_path, "a", encoding="utf-8") as f:
        f.write(entry + "\n")

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
