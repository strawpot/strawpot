"""SQLite database management — schema initialization and connection helpers."""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import Request

logger = logging.getLogger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    working_dir TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    run_id      TEXT PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    runtime     TEXT NOT NULL,
    isolation   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'starting',
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    duration_ms INTEGER,
    exit_code   INTEGER,
    session_dir TEXT NOT NULL,
    task        TEXT,
    summary     TEXT,
    schedule_id INTEGER REFERENCES scheduled_tasks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status  ON sessions(status);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role          TEXT,
    task          TEXT NOT NULL,
    cron_expr     TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    system_prompt TEXT,
    last_run_at   TEXT,
    next_run_at   TEXT,
    last_error    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with recommended settings."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    """Create database file and apply schema if needed."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_db(db_path: str):
    """Context manager yielding a database connection.

    Commits on clean exit, rolls back on exception.
    """
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db_conn(request: Request):
    """FastAPI dependency that yields a database connection."""
    with get_db(request.app.state.db_path) as conn:
        yield conn


# ---------------------------------------------------------------------------
# Session index sync
# ---------------------------------------------------------------------------


def _parse_trace(trace_path: str) -> dict:
    """Extract completion fields from a trace.jsonl file.

    Returns dict with keys: ended_at, duration_ms, exit_code, summary.
    Missing fields are omitted.
    """
    result: dict = {}
    try:
        with open(trace_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = event.get("event")
                data = event.get("data", {})
                if etype == "session_end":
                    result["ended_at"] = event.get("ts")
                    if "duration_ms" in data:
                        result["duration_ms"] = data["duration_ms"]
                elif etype == "delegate_end" and not event.get("parent_span"):
                    result["exit_code"] = data.get("exit_code")
                    result["summary"] = data.get("summary")
    except OSError:
        pass
    return result


def _is_pid_alive(pid: int) -> bool:
    """Check if a process is alive (thin wrapper, no strawpot dependency)."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def sync_sessions(db_path: str) -> None:
    """Scan all registered projects and upsert session rows into gui.db."""
    with get_db(db_path) as conn:
        projects = conn.execute(
            "SELECT id, working_dir FROM projects"
        ).fetchall()

        for project in projects:
            project_id = project["id"]
            working_dir = project["working_dir"]
            _sync_project_sessions(conn, project_id, working_dir)


def _sync_project_sessions(
    conn: sqlite3.Connection, project_id: int, working_dir: str
) -> None:
    """Scan a single project's session directories and upsert rows."""
    strawpot_dir = os.path.join(working_dir, ".strawpot")
    sessions_base = os.path.join(strawpot_dir, "sessions")
    if not os.path.isdir(sessions_base):
        return

    # Scan running sessions (symlinks in .strawpot/running/)
    running_dir = os.path.join(strawpot_dir, "running")
    if os.path.isdir(running_dir):
        for entry in os.listdir(running_dir):
            if not entry.startswith("run_"):
                continue
            session_dir = os.path.join(sessions_base, entry)
            if os.path.isdir(session_dir):
                _upsert_session(conn, project_id, session_dir, is_archived=False)

    # Scan archived sessions (symlinks in .strawpot/archive/)
    archive_dir = os.path.join(strawpot_dir, "archive")
    if os.path.isdir(archive_dir):
        for entry in os.listdir(archive_dir):
            if not entry.startswith("run_"):
                continue
            session_dir = os.path.join(sessions_base, entry)
            if os.path.isdir(session_dir):
                _upsert_session(conn, project_id, session_dir, is_archived=True)


def _upsert_session(
    conn: sqlite3.Connection,
    project_id: int,
    session_dir: str,
    *,
    is_archived: bool,
) -> None:
    """Read session.json + trace.jsonl and upsert a session row."""
    session_file = os.path.join(session_dir, "session.json")
    if not os.path.isfile(session_file):
        return

    try:
        with open(session_file, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.debug("Skipping unreadable session file: %s", session_file)
        return

    run_id = data.get("run_id")
    if not run_id:
        return

    # Extract role from first agent
    agents = data.get("agents", {})
    role = "unknown"
    if agents:
        first_agent = next(iter(agents.values()))
        role = first_agent.get("role", "unknown")

    runtime = data.get("runtime", "unknown")
    isolation = data.get("isolation", "none")
    started_at = data.get("started_at", "")

    # Determine status and parse trace
    trace_path = os.path.join(session_dir, "trace.jsonl")
    trace_info = _parse_trace(trace_path)

    if is_archived:
        exit_code = trace_info.get("exit_code")
        if exit_code is not None and exit_code == 0:
            status = "completed"
        elif exit_code is not None:
            status = "failed"
        elif "ended_at" in trace_info:
            status = "completed"
        else:
            status = "failed"
    else:
        pid = data.get("pid")
        if pid is not None and _is_pid_alive(pid):
            status = "running"
        else:
            status = "stale"

    conn.execute(
        """INSERT OR REPLACE INTO sessions
           (run_id, project_id, role, runtime, isolation, status,
            started_at, ended_at, duration_ms, exit_code, session_dir,
            task, summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            project_id,
            role,
            runtime,
            isolation,
            status,
            started_at,
            trace_info.get("ended_at"),
            trace_info.get("duration_ms"),
            trace_info.get("exit_code"),
            session_dir,
            data.get("task"),
            trace_info.get("summary"),
        ),
    )
