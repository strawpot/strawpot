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
                   exit_code = ?, summary = ?
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
    isolation: str | None = None
    merge_strategy: str | None = None


class SessionLaunch(BaseModel):
    project_id: int
    task: str
    role: str | None = None
    overrides: SessionOverrides | None = None

    @field_validator("task")
    @classmethod
    def task_must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task must be non-empty")
        return v.strip()


@router.post("/sessions", status_code=201)
def launch_session(body: SessionLaunch, conn=Depends(get_db_conn)):
    """Launch a new headless session as a detached subprocess."""
    project = conn.execute(
        "SELECT id, working_dir FROM projects WHERE id = ?",
        (body.project_id,),
    ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    working_dir = project["working_dir"]
    if not Path(working_dir).is_dir():
        raise HTTPException(
            422, "Project working directory does not exist"
        )

    # Load project config for defaults
    config = load_config(Path(working_dir))
    role = body.role or config.orchestrator_role
    runtime = config.runtime
    isolation = config.isolation

    if body.overrides:
        if body.overrides.runtime:
            runtime = body.overrides.runtime
        if body.overrides.isolation:
            isolation = body.overrides.isolation

    # Pre-generate run_id
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    session_dir = str(Path(working_dir) / ".strawpot" / "sessions" / run_id)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """INSERT INTO sessions
           (run_id, project_id, role, runtime, isolation, status,
            started_at, session_dir, task)
           VALUES (?, ?, ?, ?, ?, 'starting', ?, ?, ?)""",
        (run_id, body.project_id, role, runtime, isolation, now,
         session_dir, body.task),
    )

    # Build CLI command
    strawpot_cmd = shutil.which("strawpot")
    if strawpot_cmd is None:
        raise HTTPException(500, "strawpot CLI not found on PATH")

    cmd = [
        strawpot_cmd, "start",
        "--headless",
        "--task", body.task,
        "--run-id", run_id,
    ]
    if body.role:
        cmd.extend(["--role", body.role])
    if body.overrides:
        if body.overrides.runtime:
            cmd.extend(["--runtime", body.overrides.runtime])
        if body.overrides.isolation:
            cmd.extend(["--isolation", body.overrides.isolation])
        if body.overrides.merge_strategy:
            cmd.extend(["--merge-strategy", body.overrides.merge_strategy])

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
        raise HTTPException(500, "Failed to start session subprocess")

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
        f"       started_at, ended_at, duration_ms, exit_code, task, summary"
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
def list_sessions(project_id: int, conn=Depends(get_db_conn)):
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

    rows = conn.execute(
        "SELECT run_id, project_id, role, runtime, isolation, status,"
        "       started_at, ended_at, duration_ms, exit_code, task, summary"
        "  FROM sessions WHERE project_id = ? ORDER BY started_at DESC",
        (project_id,),
    ).fetchall()
    return [dict(row) for row in rows]


@router.get("/projects/{project_id}/sessions/{run_id}")
def get_session(project_id: int, run_id: str, conn=Depends(get_db_conn)):
    # Refresh status for active sessions before returning
    _refresh_session_status(conn, run_id)

    row = conn.execute(
        "SELECT run_id, project_id, role, runtime, isolation, status,"
        "       started_at, ended_at, duration_ms, exit_code, task, summary,"
        "       session_dir"
        "  FROM sessions WHERE project_id = ? AND run_id = ?",
        (project_id, run_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")

    result = {
        k: row[k]
        for k in row.keys()
        if k != "session_dir"
    }

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
        "SELECT run_id, status, session_dir FROM sessions WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")

    if row["status"] not in ("starting", "running"):
        raise HTTPException(
            409, f"Session is not running (status: {row['status']})"
        )

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
        return {"run_id": run_id, "status": "stopped"}

    pid = data.get("pid")
    if pid is None:
        # No PID recorded — mark as stopped
        conn.execute(
            "UPDATE sessions SET status = 'stopped' WHERE run_id = ?",
            (run_id,),
        )
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
        return {"run_id": run_id, "status": "stopped"}

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        # Race: died between check and kill
        conn.execute(
            "UPDATE sessions SET status = 'stopped' WHERE run_id = ?",
            (run_id,),
        )
        return {"run_id": run_id, "status": "stopped"}

    conn.execute(
        "UPDATE sessions SET status = 'stopped' WHERE run_id = ?",
        (run_id,),
    )
    return {"run_id": run_id, "status": "stopped"}


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
